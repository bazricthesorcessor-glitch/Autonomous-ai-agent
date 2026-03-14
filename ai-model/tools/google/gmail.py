# ========================= tools/google/gmail.py =========================
"""
Gmail tool — read, search, and send emails via existing Google OAuth.

Actions:
  gmail_list     List recent emails               [max=10, label=INBOX]
  gmail_read     Read an email by ID              [message_id=...]
  gmail_send     Send an email                    [to=..., subject=..., body=...]
  gmail_search   Search emails (Gmail query)      [query=..., max=10]

Setup:
  Requires Gmail scope — if you haven't re-authenticated since this was added:
    1. Delete ai-model/config/google_token.json
    2. Run google.run_tool({"action": "auth"})  (opens browser once)
"""

import base64
import email as _email_lib
from email.mime.text import MIMEText
from tools.google.auth import build_service


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_gmail():
    """Return (service, error_str)."""
    return build_service("gmail", "v1")


def _header(msg_payload, name: str) -> str:
    """Extract a header value from a Gmail message payload."""
    for h in msg_payload.get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _get_body(payload: dict, mime_type: str = "text/plain") -> str:
    """Recursively extract the plaintext (or html) body from a Gmail payload."""
    if payload.get("mimeType", "").startswith(mime_type):
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        result = _get_body(part, mime_type)
        if result:
            return result

    return ""


def _fmt_message(msg: dict, snippet_only: bool = True) -> str:
    """Format a Gmail message for display."""
    payload = msg.get("payload", {})
    subject = _header(payload, "Subject") or "(no subject)"
    sender  = _header(payload, "From")   or "(unknown)"
    date    = _header(payload, "Date")   or ""
    msg_id  = msg.get("id", "")

    if snippet_only:
        snippet = msg.get("snippet", "")
        return f"  ID: {msg_id}\n  From: {sender}\n  Subject: {subject}\n  Date: {date}\n  Preview: {snippet[:120]}"

    body = _get_body(payload) or _get_body(payload, "text/html") or "(no body)"
    # Trim very long bodies
    if len(body) > 3000:
        body = body[:3000] + "\n\n[... truncated at 3000 chars]"
    return (
        f"ID:      {msg_id}\n"
        f"From:    {sender}\n"
        f"Subject: {subject}\n"
        f"Date:    {date}\n"
        + "─" * 50 + "\n"
        + body.strip()
    )


# ── Actions ───────────────────────────────────────────────────────────────────

def gmail_list(args: dict) -> str:
    """List recent emails from a label (default: INBOX)."""
    svc, err = _build_gmail()
    if err:
        return err

    max_r  = max(1, min(int(args.get("max", 10)), 50))
    label  = str(args.get("label", "INBOX")).upper()

    try:
        result = svc.users().messages().list(
            userId="me", maxResults=max_r, labelIds=[label]
        ).execute()
    except Exception as e:
        return f"[gmail] list failed: {e}"

    messages = result.get("messages", [])
    if not messages:
        return f"No messages found in {label}."

    lines = [f"Gmail — {label} ({len(messages)} messages):"]
    for m in messages:
        try:
            full = svc.users().messages().get(
                userId="me", id=m["id"], format="full"
            ).execute()
            lines.append("\n" + _fmt_message(full, snippet_only=True))
        except Exception:
            lines.append(f"\n  ID: {m['id']}  (could not fetch details)")

    return "\n".join(lines)


def gmail_read(args: dict) -> str:
    """Read a specific email by message ID."""
    message_id = str(args.get("message_id", "")).strip()
    if not message_id:
        return "[gmail] No 'message_id' provided."

    svc, err = _build_gmail()
    if err:
        return err

    try:
        msg = svc.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()
    except Exception as e:
        return f"[gmail] read failed: {e}"

    return _fmt_message(msg, snippet_only=False)


def gmail_send(args: dict) -> str:
    """Send an email."""
    to      = str(args.get("to", "")).strip()
    subject = str(args.get("subject", "(no subject)")).strip()
    body    = str(args.get("body", "")).strip()

    if not to:
        return "[gmail] No 'to' address provided."
    if not body:
        return "[gmail] No 'body' provided."

    svc, err = _build_gmail()
    if err:
        return err

    mime_msg = MIMEText(body, "plain", "utf-8")
    mime_msg["to"]      = to
    mime_msg["subject"] = subject
    raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")

    try:
        sent = svc.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        return f"Email sent. Message ID: {sent.get('id', '?')}"
    except Exception as e:
        return f"[gmail] send failed: {e}"


def gmail_search(args: dict) -> str:
    """Search Gmail using Gmail query syntax (e.g. 'from:alice subject:report')."""
    query = str(args.get("query", "")).strip()
    if not query:
        return "[gmail] No 'query' provided."

    max_r = max(1, min(int(args.get("max", 10)), 50))

    svc, err = _build_gmail()
    if err:
        return err

    try:
        result = svc.users().messages().list(
            userId="me", q=query, maxResults=max_r
        ).execute()
    except Exception as e:
        return f"[gmail] search failed: {e}"

    messages = result.get("messages", [])
    if not messages:
        return f"No emails found for: '{query}'"

    lines = [f"Gmail search: '{query}'  ({len(messages)} results)"]
    for m in messages:
        try:
            full = svc.users().messages().get(
                userId="me", id=m["id"], format="full"
            ).execute()
            lines.append("\n" + _fmt_message(full, snippet_only=True))
        except Exception:
            lines.append(f"\n  ID: {m['id']}  (could not fetch details)")

    return "\n".join(lines)
