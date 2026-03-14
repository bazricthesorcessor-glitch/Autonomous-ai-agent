# ========================= tools/pdf.py =========================
"""
PDF reading, analysis, and extraction tool.

Actions:
  read     Extract full text from a PDF        [path=..., max_chars=8000]
  pages    Extract specific page range          [path=..., start=1, end=5]
  info     PDF metadata and structure info      [path=...]
  topics   Extract headings and key topics      [path=..., top=20]
  search   Search for a keyword inside PDF      [path=..., keyword=...]
  list     Show all available actions
"""

import os
import re
from collections import Counter


# ---------------------------------------------------------------------------
# Import guard — pypdf is required
# ---------------------------------------------------------------------------
try:
    import pypdf
    _PYPDF_OK = True
except ImportError:
    _PYPDF_OK = False

# ---------------------------------------------------------------------------
# OCR fallback — optional: pytesseract + pdf2image + system tesseract
#   pip install pytesseract pdf2image
#   sudo pacman -S tesseract tesseract-data-eng   (Arch/CachyOS)
# ---------------------------------------------------------------------------
try:
    import pytesseract
    from pdf2image import convert_from_path as _pdf2img
    _OCR_OK = True
except ImportError:
    _OCR_OK = False

_OCR_INSTALL_MSG = (
    "[pdf] Scanned PDF — no text layer found.\n"
    "To enable OCR install:\n"
    "  pip install pytesseract pdf2image\n"
    "  sudo pacman -S tesseract tesseract-data-eng"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_pypdf() -> str | None:
    if not _PYPDF_OK:
        return "[pdf] pypdf is not installed. Run: pip install pypdf"
    return None


def _resolve_path(raw: str) -> str:
    """Expand ~ and make absolute."""
    return os.path.abspath(os.path.expanduser(raw))


def _open_pdf(path: str):
    """Return (reader, None) or (None, error_str)."""
    err = _require_pypdf()
    if err:
        return None, err
    if not path:
        return None, "[pdf] No 'path' provided."
    path = _resolve_path(path)
    if not os.path.exists(path):
        return None, f"[pdf] File not found: {path}"
    if not path.lower().endswith(".pdf"):
        return None, f"[pdf] File does not look like a PDF: {path}"
    try:
        reader = pypdf.PdfReader(path)
        return reader, None
    except Exception as e:
        return None, f"[pdf] Cannot open PDF: {e}"


def _extract_all_text(reader) -> str:
    """Extract text from every page, joined with page markers."""
    parts = []
    for i, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text.strip():
            parts.append(f"--- Page {i} ---\n{text.strip()}")
    return "\n\n".join(parts)


def _ocr_extract(path: str, first_page: int = None, last_page: int = None) -> str:
    """
    Convert PDF pages to images and run tesseract OCR.
    first_page / last_page are 1-based (None = all pages).
    Returns extracted text, or an install-hint string if OCR unavailable.
    """
    if not _OCR_OK:
        return _OCR_INSTALL_MSG
    try:
        kwargs = {}
        if first_page:
            kwargs["first_page"] = first_page
        if last_page:
            kwargs["last_page"] = last_page
        images = _pdf2img(path, **kwargs)
    except Exception as e:
        return f"[pdf] OCR image conversion failed: {e}"

    parts = []
    offset = (first_page or 1)
    for i, img in enumerate(images):
        page_num = offset + i
        try:
            text = pytesseract.image_to_string(img)
        except Exception:
            text = ""
        if text.strip():
            parts.append(f"--- Page {page_num} (OCR) ---\n{text.strip()}")

    return "\n\n".join(parts)


def _looks_like_heading(line: str) -> bool:
    """Heuristic: short, non-empty, ends without period, mostly alphanumeric."""
    line = line.strip()
    if not line or len(line) > 120:
        return False
    if line.endswith(".") or line.endswith(","):
        return False
    # Must have at least one letter
    if not re.search(r"[A-Za-z]", line):
        return False
    # Typical heading patterns
    if re.match(r"^(\d+[\.\d]*\s+|[IVXLC]+\.\s+|[A-Z]\.\s+)", line):
        return True
    # All-caps or Title Case short line
    words = line.split()
    if len(words) <= 8:
        cap_words = sum(1 for w in words if w[0].isupper() if w)
        if cap_words / len(words) >= 0.7:
            return True
    return False


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def _read(args: dict) -> str:
    path = str(args.get("path", "")).strip()
    reader, err = _open_pdf(path)
    if err:
        return err

    max_chars = max(1000, min(int(args.get("max_chars", 8000)), 50000))
    total_pages = len(reader.pages)
    text = _extract_all_text(reader)

    if not text.strip():
        if _OCR_OK:
            text = _ocr_extract(path)
            if not text.strip():
                return f"[pdf] OCR found no text in '{os.path.basename(path)}'."
            ocr_used = True
        else:
            return _OCR_INSTALL_MSG
    else:
        ocr_used = False

    ocr_note = " [OCR via tesseract]" if ocr_used else ""
    header = f"PDF: {os.path.basename(path)} ({total_pages} pages){ocr_note}\n{'='*50}\n\n"
    full = header + text

    if len(full) > max_chars:
        full = full[:max_chars] + f"\n\n[... truncated at {max_chars} chars. Use pages= to read specific sections]"

    return full


def _pages(args: dict) -> str:
    path = str(args.get("path", "")).strip()
    reader, err = _open_pdf(path)
    if err:
        return err

    total = len(reader.pages)
    try:
        start = max(1, int(args.get("start", 1)))
        end   = min(total, int(args.get("end", start + 4)))
    except (ValueError, TypeError):
        return "[pdf] 'start' and 'end' must be page numbers (integers)."

    if start > total:
        return f"[pdf] PDF only has {total} pages. 'start' is out of range."

    parts = []
    for i in range(start - 1, end):
        try:
            text = reader.pages[i].extract_text() or ""
        except Exception:
            text = ""
        parts.append(f"--- Page {i+1} ---\n{text.strip()}")

    # If all pages are empty (scanned PDF), try OCR for this page range
    all_empty = all(p.endswith("---\n") for p in parts)
    ocr_note  = ""
    if all_empty:
        ocr_text = _ocr_extract(path, first_page=start, last_page=end)
        if ocr_text.strip() and not ocr_text.startswith("[pdf]"):
            return (
                f"PDF: {os.path.basename(path)} — Pages {start}–{end} of {total} [OCR]\n"
                + "=" * 50 + "\n\n" + ocr_text
            )
        elif not _OCR_OK:
            ocr_note = f"\n\n{_OCR_INSTALL_MSG}"

    return (
        f"PDF: {os.path.basename(path)} — Pages {start}–{end} of {total}\n"
        + "=" * 50 + "\n\n"
        + "\n\n".join(parts)
        + ocr_note
    )


def _info(args: dict) -> str:
    path = str(args.get("path", "")).strip()
    reader, err = _open_pdf(path)
    if err:
        return err

    total_pages = len(reader.pages)
    meta = reader.metadata or {}

    def _m(key):
        val = meta.get(key, "")
        return str(val).strip() if val else "—"

    # Estimate word count from first 10 pages
    sample_text = ""
    for page in reader.pages[:10]:
        try:
            sample_text += page.extract_text() or ""
        except Exception:
            pass
    word_sample = len(sample_text.split())
    est_words = int(word_sample * (total_pages / min(total_pages, 10)))
    is_encrypted = reader.is_encrypted

    lines = [
        f"File: {os.path.basename(path)}",
        f"Path: {_resolve_path(path)}",
        f"Pages: {total_pages}",
        f"Encrypted: {'Yes' if is_encrypted else 'No'}",
        f"Estimated words: ~{est_words:,}",
        "",
        "Metadata:",
        f"  Title:    {_m('/Title')}",
        f"  Author:   {_m('/Author')}",
        f"  Subject:  {_m('/Subject')}",
        f"  Creator:  {_m('/Creator')}",
        f"  Producer: {_m('/Producer')}",
        f"  Created:  {_m('/CreationDate')}",
        f"  Modified: {_m('/ModDate')}",
    ]

    # Check if text-extractable
    if not is_encrypted:
        first_text = ""
        try:
            first_text = reader.pages[0].extract_text() or ""
        except Exception:
            pass
        lines.append("")
        if first_text.strip():
            lines.append("Text extraction: Supported (text-based PDF)")
        else:
            ocr_status = "OCR available (pytesseract)" if _OCR_OK else "OCR not installed — pip install pytesseract pdf2image"
            lines.append(f"Text extraction: NOT supported (scanned PDF) — {ocr_status}")

    return "\n".join(lines)


def _topics(args: dict) -> str:
    path = str(args.get("path", "")).strip()
    reader, err = _open_pdf(path)
    if err:
        return err

    top_n = max(5, min(int(args.get("top", 20)), 50))
    full_text = _extract_all_text(reader)

    if not full_text.strip():
        return "[pdf] No extractable text found. Cannot detect topics."

    # ── 1. Extract headings ────────────────────────────────────────────────
    headings = []
    for line in full_text.splitlines():
        line = line.strip()
        if _looks_like_heading(line) and line not in headings:
            headings.append(line)
        if len(headings) >= 40:
            break

    # ── 2. Keyword frequency (skip stopwords) ─────────────────────────────
    _STOP = {
        "the","a","an","and","or","but","in","on","at","to","for","of","with",
        "by","from","as","is","was","are","were","be","been","has","have","had",
        "it","its","this","that","these","those","they","we","you","he","she",
        "his","her","their","our","which","who","what","how","when","where","why",
        "not","no","can","will","would","could","should","may","might","also",
        "if","then","than","so","up","out","into","through","about","after","before",
        "any","all","each","more","most","some","such","other","new","use","used",
    }
    words = re.findall(r"\b[a-zA-Z]{4,}\b", full_text.lower())
    filtered = [w for w in words if w not in _STOP]
    freq = Counter(filtered).most_common(top_n)

    # ── Format output ──────────────────────────────────────────────────────
    lines = [f"PDF: {os.path.basename(path)} — Topics & Key Terms\n{'='*50}"]

    if headings:
        lines.append(f"\nHeadings / Sections ({len(headings)} found):")
        for i, h in enumerate(headings, 1):
            lines.append(f"  {i:2}. {h}")
    else:
        lines.append("\nNo clear headings detected.")

    lines.append(f"\nTop {top_n} Keywords (by frequency):")
    for word, count in freq:
        lines.append(f"  {word:<25} {count}×")

    return "\n".join(lines)


def _search(args: dict) -> str:
    path    = str(args.get("path", "")).strip()
    keyword = str(args.get("keyword", "")).strip()
    if not keyword:
        return "[pdf] No 'keyword' provided."

    reader, err = _open_pdf(path)
    if err:
        return err

    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    matches = []
    context_chars = 120

    for i, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        for m in pattern.finditer(text):
            start = max(0, m.start() - context_chars // 2)
            end   = min(len(text), m.end() + context_chars // 2)
            snippet = text[start:end].replace("\n", " ").strip()
            matches.append((i, snippet))

    if not matches:
        return f"[pdf] '{keyword}' not found in {os.path.basename(path)}"

    lines = [
        f"PDF: {os.path.basename(path)} — Search: '{keyword}' ({len(matches)} match{'es' if len(matches) != 1 else ''})\n{'='*50}"
    ]
    for page_num, snippet in matches[:30]:
        lines.append(f"\nPage {page_num}:")
        lines.append(f"  ...{snippet}...")

    if len(matches) > 30:
        lines.append(f"\n[{len(matches) - 30} more matches not shown]")

    return "\n".join(lines)


def _list_actions(_: dict) -> str:
    return (
        "Available pdf actions:\n"
        "  read     Extract full text          [path=..., max_chars=8000]\n"
        "  pages    Specific page range        [path=..., start=1, end=5]\n"
        "  info     Metadata + structure       [path=...]\n"
        "  topics   Headings + key keywords    [path=..., top=20]\n"
        "  search   Find keyword in PDF        [path=..., keyword=...]"
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_ACTIONS = {
    "read":   _read,
    "pages":  _pages,
    "info":   _info,
    "topics": _topics,
    "search": _search,
    "list":   _list_actions,
}


def run_tool(args: dict = None) -> str:
    if args is None:
        args = {}
    action = str(args.get("action", "")).strip().lower()
    if not action:
        return "[pdf] No action specified. Use action='list' to see available tools."
    fn = _ACTIONS.get(action)
    if fn is None:
        return f"[pdf] Unknown action '{action}'. Available: {', '.join(_ACTIONS)}"
    try:
        return fn(args)
    except Exception as e:
        return f"[pdf] Error in '{action}': {e}"
