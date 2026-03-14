# ========================= tools/google/drive.py =========================
"""Google Drive actions: list, search, read, upload, create_folder."""

import os
import mimetypes
from tools.google.auth import build_service


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

_MIME_FILTER = {
    "pdf":    "application/pdf",
    "doc":    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "sheet":  "application/vnd.google-apps.spreadsheet",
    "slides": "application/vnd.google-apps.presentation",
    "folder": "application/vnd.google-apps.folder",
    "image":  "image/",
}


def drive_list(args: dict) -> str:
    drive, err = build_service("drive", "v3")
    if err: return err

    folder_id   = args.get("folder_id", "root")
    max_files   = max(1, min(int(args.get("max", 20)), 100))
    type_filter = args.get("type", "").lower()

    q = f"'{folder_id}' in parents and trashed=false"
    for k, v in _MIME_FILTER.items():
        if k in type_filter:
            q += f" and mimeType contains '{v}'"
            break

    try:
        result = drive.files().list(
            q=q, pageSize=max_files, orderBy="modifiedTime desc",
            fields="files(id,name,mimeType,size,modifiedTime)"
        ).execute()
    except Exception as e:
        return f"[drive_list] {e}"

    files = result.get("files", [])
    if not files:
        return "No files found."

    lines = [f"Google Drive — {len(files)} files  (folder: {folder_id})\n{'='*50}"]
    for f in files:
        size = _fmt_size(int(f.get("size", 0))) if f.get("size") else "—"
        mod  = f.get("modifiedTime", "")[:10]
        mime = f.get("mimeType", "").split("/")[-1]
        lines.append(f"  {f['name']}  ({mime})  {size}  {mod}")
        lines.append(f"    ID: {f['id']}")
    return "\n".join(lines)


def drive_search(args: dict) -> str:
    drive, err = build_service("drive", "v3")
    if err: return err

    query = str(args.get("query", "")).strip()
    if not query:
        return "[drive_search] No 'query' provided."

    max_files = max(1, min(int(args.get("max", 10)), 50))
    try:
        result = drive.files().list(
            q=f"fullText contains '{query}' and trashed=false",
            pageSize=max_files, orderBy="modifiedTime desc",
            fields="files(id,name,mimeType,modifiedTime)"
        ).execute()
    except Exception as e:
        return f"[drive_search] {e}"

    files = result.get("files", [])
    if not files:
        return f"No Drive files found matching: '{query}'"

    lines = [f"Drive search: '{query}' — {len(files)} results\n{'='*50}"]
    for f in files:
        mime = f.get("mimeType", "").split("/")[-1]
        mod  = f.get("modifiedTime", "")[:10]
        lines.append(f"  {f['name']}  ({mime})  {mod}\n    ID: {f['id']}")
    return "\n".join(lines)


def drive_read(args: dict) -> str:
    drive, err = build_service("drive", "v3")
    if err: return err

    file_id = str(args.get("file_id", "")).strip()
    if not file_id:
        return "[drive_read] No 'file_id' provided."

    max_chars = max(1000, min(int(args.get("max_chars", 5000)), 30000))

    try:
        meta = drive.files().get(fileId=file_id, fields="name,mimeType").execute()
    except Exception as e:
        return f"[drive_read] {e}"

    name = meta.get("name", file_id)
    mime = meta.get("mimeType", "")

    if "google-apps.document" in mime:
        try:
            content = drive.files().export(fileId=file_id, mimeType="text/plain").execute()
            text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
        except Exception as e:
            return f"[drive_read] Export failed: {e}"
    elif mime.startswith("text/") or mime == "application/json":
        try:
            import io
            from googleapiclient.http import MediaIoBaseDownload
            fh = io.BytesIO()
            dl = MediaIoBaseDownload(fh, drive.files().get_media(fileId=file_id))
            done = False
            while not done:
                _, done = dl.next_chunk()
            text = fh.getvalue().decode("utf-8", errors="replace")
        except Exception as e:
            return f"[drive_read] Download failed: {e}"
    else:
        return f"[drive_read] Cannot read binary file '{name}' ({mime}) as text."

    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[... truncated at {max_chars} chars]"

    return f"**{name}** (Google Drive)\n{'='*50}\n\n{text}"


def drive_upload(args: dict) -> str:
    drive, err = build_service("drive", "v3")
    if err: return err

    path = str(args.get("path", "")).strip()
    if not path:
        return "[drive_upload] No 'path' provided."
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return f"[drive_upload] File not found: {path}"

    from googleapiclient.http import MediaFileUpload
    name     = os.path.basename(path)
    mime, _  = mimetypes.guess_type(path)
    mime     = mime or "application/octet-stream"
    metadata = {"name": name}
    if args.get("folder_id"):
        metadata["parents"] = [args["folder_id"]]

    try:
        result = drive.files().create(
            body=metadata,
            media_body=MediaFileUpload(path, mimetype=mime),
            fields="id,name,webViewLink"
        ).execute()
        return (
            f"Uploaded: {result['name']}\n"
            f"ID:   {result['id']}\n"
            f"Link: {result.get('webViewLink', '—')}"
        )
    except Exception as e:
        return f"[drive_upload] {e}"


def drive_create_folder(args: dict) -> str:
    drive, err = build_service("drive", "v3")
    if err: return err

    name = str(args.get("name", "")).strip()
    if not name:
        return "[drive_create_folder] No 'name' provided."

    metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if args.get("parent_id"):
        metadata["parents"] = [args["parent_id"]]

    try:
        result = drive.files().create(body=metadata, fields="id,name").execute()
        return f"Folder created: '{result['name']}'\nID: {result['id']}"
    except Exception as e:
        return f"[drive_create_folder] {e}"
