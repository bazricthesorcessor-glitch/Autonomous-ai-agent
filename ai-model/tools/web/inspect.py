# ========================= tools/web/inspect.py =========================
"""
HTML page inspector — fetches a URL and extracts its interactive structure.

Actions:
  inspect_page   Full structural map of a page   [url=..., max_links=20]
  find_forms     Extract all forms and their fields
  find_buttons   List all clickable buttons / submit inputs
  find_links     List navigation links and anchors
  find_headings  Page heading hierarchy (h1–h3)

Unlike fetch_page (which returns text), inspect_page returns the *structure*:
what buttons exist, what forms ask for, what navigation looks like.
Useful for web automation, form-filling, and UI understanding.
"""

import urllib.error
from html.parser import HTMLParser
from tools.web.http_client import http_get


# ── HTML parser ───────────────────────────────────────────────────────────────

class _Inspector(HTMLParser):
    """Single-pass parser that collects page structure into categorised lists."""

    def __init__(self):
        super().__init__()
        self.title       = ""
        self.description = ""
        self.headings    = []        # (level, text)
        self.forms       = []        # list of form dicts
        self.buttons     = []        # standalone buttons (outside forms)
        self.nav_links   = []        # links inside <nav>
        self.all_links   = []        # all <a href> links

        self._in_title   = False
        self._in_nav     = False
        self._nav_depth  = 0
        self._cur_form   = None
        self._cur_head   = None      # (level, chars accumulated)
        self._in_button  = False
        self._cur_btn    = ""
        self._cur_link   = None      # current <a> entry being parsed (for text capture)
        self._buf        = ""        # generic text buffer for other tags

    # ── tag open ─────────────────────────────────────────────────────────────

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)

        if tag == "title":
            self._in_title = True; return

        if tag == "meta":
            name = a.get("name", "").lower()
            if name == "description":
                self.description = a.get("content", "")[:200]
            return

        if tag in ("h1", "h2", "h3"):
            self._cur_head = (tag, ""); return

        if tag == "nav":
            self._in_nav = True; self._nav_depth += 1; return
        if tag == "form":
            self._cur_form = {
                "action":  a.get("action", "(none)"),
                "method":  a.get("method", "get").upper(),
                "id":      a.get("id", ""),
                "name":    a.get("name", ""),
                "fields":  [],
            }; return

        if tag in ("input", "select", "textarea") and self._cur_form is not None:
            ftype  = a.get("type", "text" if tag == "input" else tag).lower()
            fname  = a.get("name", "") or a.get("id", "") or f"({tag})"
            fphdr  = a.get("placeholder", "") or a.get("label", "")
            freq   = "required" in a
            if ftype not in ("hidden", "submit", "button", "reset", "image"):
                self._cur_form["fields"].append({
                    "type": ftype, "name": fname,
                    "placeholder": fphdr, "required": freq,
                })
            elif ftype in ("submit", "button"):
                val = a.get("value", "Submit")
                self._cur_form["fields"].append({"type": "submit", "value": val})
            return

        if tag == "button":
            btype = a.get("type", "button").lower()
            if self._cur_form is not None:
                self._cur_form["fields"].append({
                    "type": f"button[{btype}]",
                    "value": a.get("value", ""),
                })
            else:
                self._in_button = True; self._cur_btn = ""; return

        if tag == "a":
            href = a.get("href", "").strip()
            text_hint = a.get("aria-label", "") or a.get("title", "")
            if href and href not in ("#", "javascript:void(0)", "javascript:;"):
                entry = {"href": href, "label": text_hint}
                if self._in_nav:
                    self.nav_links.append(entry)
                self.all_links.append(entry)
                self._cur_link = entry  # capture text children for label
            return

    # ── tag close ────────────────────────────────────────────────────────────

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False; return

        if tag in ("h1", "h2", "h3") and self._cur_head:
            lvl, txt = self._cur_head
            if txt.strip():
                self.headings.append((lvl, txt.strip()[:120]))
            self._cur_head = None; return

        if tag == "nav":
            self._nav_depth = max(0, self._nav_depth - 1)
            if self._nav_depth == 0:
                self._in_nav = False
            return

        if tag == "form" and self._cur_form is not None:
            self.forms.append(self._cur_form)
            self._cur_form = None; return

        if tag == "button" and self._in_button:
            if self._cur_btn.strip():
                self.buttons.append(self._cur_btn.strip()[:80])
            self._in_button = False; self._cur_btn = ""; return

        if tag == "a" and self._cur_link is not None:
            # Normalise label — strip whitespace, cap length
            self._cur_link["label"] = self._cur_link.get("label", "").strip()[:120]
            self._cur_link = None

    # ── text ──────────────────────────────────────────────────────────────────

    def handle_data(self, data):
        if self._in_title:
            self.title += data; return
        if self._cur_head:
            self._cur_head = (self._cur_head[0], self._cur_head[1] + data); return
        if self._in_button:
            self._cur_btn += data; return
        # Capture text content of <a> tags as link labels (when no aria-label/title)
        if self._cur_link is not None and not self._cur_link.get("label"):
            self._cur_link["label"] = self._cur_link.get("label", "") + data


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch_and_parse(url: str):
    """Return (inspector, error_str)."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        html = http_get(url)
    except urllib.error.HTTPError as e:
        return None, f"[inspect] HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return None, f"[inspect] Connection failed: {e.reason}"
    except Exception as e:
        return None, f"[inspect] Error: {e}"

    ins = _Inspector()
    try:
        ins.feed(html)
    except Exception:
        pass  # partial parse is fine
    return ins, None


def _fmt_field(f: dict) -> str:
    parts = [f"  [{f.get('type','?')}]", f.get('name','')]
    if f.get("placeholder"):
        parts.append(f"  ← \"{f['placeholder']}\"")
    if f.get("required"):
        parts.append("  (required)")
    if f.get("value") and f.get("type") in ("submit", "button[submit]", "button[button]"):
        parts.append(f"  \"{f['value']}\"")
    return "    " + " ".join(p for p in parts if p.strip())


# ── Actions ───────────────────────────────────────────────────────────────────

def inspect_page(args: dict) -> str:
    """Full structural overview: title, description, headings, forms, buttons, nav."""
    url = str(args.get("url", "")).strip()
    if not url:
        return "[inspect] No 'url' provided."
    max_links = int(args.get("max_links", 20))

    ins, err = _fetch_and_parse(url)
    if err:
        return err

    lines = [f"Page Inspection: {url}", "=" * 60]

    # ── Meta ───────────────────────────────────────────────────────────────
    lines.append(f"\nTitle:       {ins.title.strip() or '(none)'}")
    if ins.description:
        lines.append(f"Description: {ins.description}")

    # ── Headings ───────────────────────────────────────────────────────────
    if ins.headings:
        lines.append(f"\nHeadings ({len(ins.headings)}):")
        for lvl, text in ins.headings[:20]:
            indent = "  " * (int(lvl[1]) - 1)
            lines.append(f"  {indent}<{lvl}> {text}")
    else:
        lines.append("\nHeadings: none found")

    # ── Forms ──────────────────────────────────────────────────────────────
    if ins.forms:
        lines.append(f"\nForms ({len(ins.forms)}):")
        for i, form in enumerate(ins.forms, 1):
            label = form["name"] or form["id"] or f"form-{i}"
            lines.append(f"  Form {i}: {label}  [{form['method']} → {form['action']}]")
            for field in form["fields"]:
                lines.append(_fmt_field(field))
    else:
        lines.append("\nForms: none found")

    # ── Standalone Buttons ─────────────────────────────────────────────────
    if ins.buttons:
        lines.append(f"\nStandalone Buttons ({len(ins.buttons)}):")
        for btn in ins.buttons[:15]:
            lines.append(f"  [button] {btn}")

    # ── Navigation ─────────────────────────────────────────────────────────
    nav = ins.nav_links or ins.all_links[:max_links]
    if nav:
        label = "Navigation links" if ins.nav_links else "Links (no <nav> tag found)"
        shown = nav[:max_links]
        lines.append(f"\n{label} ({len(shown)} of {len(nav)}):")
        for lnk in shown:
            lbl = f"  {lnk['label']}  →  " if lnk.get("label") else "  "
            lines.append(f"{lbl}{lnk['href']}")

    return "\n".join(lines)


def find_forms(args: dict) -> str:
    """Return all forms with field details."""
    url = str(args.get("url", "")).strip()
    if not url:
        return "[inspect] No 'url' provided."
    ins, err = _fetch_and_parse(url)
    if err:
        return err
    if not ins.forms:
        return f"No forms found on {url}"
    lines = [f"Forms on {url}:", "=" * 60]
    for i, form in enumerate(ins.forms, 1):
        label = form["name"] or form["id"] or f"form-{i}"
        lines.append(f"\nForm {i}: {label}")
        lines.append(f"  Submit to: {form['method']} {form['action']}")
        if form["fields"]:
            lines.append("  Fields:")
            for field in form["fields"]:
                lines.append(_fmt_field(field))
    return "\n".join(lines)


def find_buttons(args: dict) -> str:
    """Return all buttons and submit inputs."""
    url = str(args.get("url", "")).strip()
    if not url:
        return "[inspect] No 'url' provided."
    ins, err = _fetch_and_parse(url)
    if err:
        return err
    items = []
    for form in ins.forms:
        for f in form["fields"]:
            if "submit" in f.get("type", "") or "button" in f.get("type", ""):
                items.append(f"[{f['type']}] {f.get('value') or f.get('name','')}")
    for btn in ins.buttons:
        items.append(f"[button] {btn}")
    if not items:
        return f"No buttons found on {url}"
    return f"Buttons on {url} ({len(items)}):\n" + "\n".join(f"  {b}" for b in items)


def find_links(args: dict) -> str:
    """Return navigation links and all <a href> links."""
    url = str(args.get("url", "")).strip()
    if not url:
        return "[inspect] No 'url' provided."
    max_links = int(args.get("max_links", 30))
    ins, err = _fetch_and_parse(url)
    if err:
        return err
    links = ins.all_links[:max_links]
    if not links:
        return f"No links found on {url}"
    nav_hrefs = {l["href"] for l in ins.nav_links}
    lines = [f"Links on {url} ({len(links)}):", "=" * 60]
    for lnk in links:
        tag = " [nav]" if lnk["href"] in nav_hrefs else ""
        lbl = f" ({lnk['label']})" if lnk.get("label") else ""
        lines.append(f"  {lnk['href']}{lbl}{tag}")
    return "\n".join(lines)


def find_headings(args: dict) -> str:
    """Return page heading hierarchy (h1–h3)."""
    url = str(args.get("url", "")).strip()
    if not url:
        return "[inspect] No 'url' provided."
    ins, err = _fetch_and_parse(url)
    if err:
        return err
    if not ins.headings:
        return f"No headings found on {url}"
    lines = [f"Headings on {url}:", "=" * 60]
    for lvl, text in ins.headings:
        indent = "  " * (int(lvl[1]) - 1)
        lines.append(f"  {indent}<{lvl}> {text}")
    return "\n".join(lines)
