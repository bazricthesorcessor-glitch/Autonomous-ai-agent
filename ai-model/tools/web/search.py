# ========================= tools/web/search.py =========================
"""DuckDuckGo web search — HTML parser with DDG Lite fallback, browser_control tertiary fallback."""

import urllib.parse
from html.parser import HTMLParser
from tools.web.http_client import http_post, http_get
from tools.web.browser import open_browser


# ── Primary parser — DuckDuckGo HTML ──────────────────────────────────────────

class _DdgParser(HTMLParser):
    """Extracts title, url, snippet from DuckDuckGo HTML results."""

    def __init__(self):
        super().__init__()
        self.results = []
        self._state  = None
        self._cur    = {}
        self._href   = ""

    def handle_starttag(self, tag, attrs):
        a   = dict(attrs)
        cls = a.get("class", "")
        if tag == "a" and "result__a" in cls:
            self._state = "title"
            self._href  = a.get("href", "")
            self._cur   = {"title": "", "url": self._href, "snippet": ""}
        elif tag == "a" and "result__snippet" in cls:
            self._state = "snippet"

    def handle_endtag(self, tag):
        if tag == "a" and self._state in ("title", "snippet"):
            if self._state == "snippet" and self._cur.get("title"):
                self.results.append({
                    "title":   self._cur["title"].strip(),
                    "url":     self._cur["url"],
                    "snippet": self._cur["snippet"].strip(),
                })
            self._state = None

    def handle_data(self, data):
        if self._state == "title":
            self._cur["title"] += data
        elif self._state == "snippet":
            self._cur["snippet"] += data


# ── Fallback parser — DuckDuckGo Lite ─────────────────────────────────────────

class _DdgLiteParser(HTMLParser):
    """
    Parses https://lite.duckduckgo.com/lite/ — simpler, more stable HTML.
    Result rows alternate: <a class="result-link"> title/url, then snippet <td>.
    """

    def __init__(self):
        super().__init__()
        self.results     = []
        self._in_link    = False
        self._in_snippet = False
        self._cur        = {}

    def handle_starttag(self, tag, attrs):
        a   = dict(attrs)
        cls = a.get("class", "")
        if tag == "a" and "result-link" in cls:
            self._in_link = True
            self._cur = {"title": "", "url": a.get("href", ""), "snippet": ""}
        elif tag == "td" and "result-snippet" in cls and self._cur.get("title"):
            self._in_snippet = True

    def handle_endtag(self, tag):
        if tag == "a" and self._in_link:
            self._in_link = False
        if tag == "td":
            if self._cur.get("title") and self._cur.get("url"):
                if self._cur not in self.results:
                    self.results.append(dict(self._cur))
            self._in_snippet = False

    def handle_data(self, data):
        if self._in_link:
            self._cur["title"] += data
        elif getattr(self, "_in_snippet", False):
            self._cur["snippet"] = self._cur.get("snippet", "") + data


def _search_lite(query: str, max_r: int) -> list:
    """Fallback: query DDG Lite and return result list."""
    try:
        html = http_post("https://lite.duckduckgo.com/lite/", {"q": query, "kl": "us-en"})
    except Exception:
        return []
    parser = _DdgLiteParser()
    parser.feed(html)
    return parser.results[:max_r]


# ── Public function ────────────────────────────────────────────────────────────

def web_search(args: dict) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "[web_search] No 'query' provided."

    max_r      = max(1, min(int(args.get("max_results", 5)), 10))
    open_first = str(args.get("open", "false")).lower() in ("true", "1", "yes")

    # ── Try primary DDG HTML ──────────────────────────────────────────────────
    results = []
    rate_limited = False
    try:
        html = http_post("https://html.duckduckgo.com/html/", {"q": query, "kl": "us-en"})
        if "please try again" in html.lower() or "blocked" in html.lower() or len(html) < 500:
            rate_limited = True
        else:
            parser = _DdgParser()
            parser.feed(html)
            results = parser.results[:max_r]
    except Exception:
        pass

    # ── Fallback: DDG Lite ────────────────────────────────────────────────────
    if not results:
        results = _search_lite(query, max_r)

    if not results:
        # ── Tertiary fallback: browser_control + DuckDuckGo ───────────────────
        # Kicks in when both HTTP endpoints are rate-limited or blocked.
        try:
            from tools import browser_control as _bc
            bc_url = "https://duckduckgo.com/?q=" + urllib.parse.quote_plus(query)
            _bc.run_tool({"action": "open", "url": bc_url})
            bc_text = _bc.run_tool({"action": "get_text", "max_length": 2500})
            if bc_text and len(bc_text.strip()) > 150 and not bc_text.startswith("["):
                return (
                    f"Search results (browser fallback) for: **{query}**\n\n"
                    + bc_text[:2500]
                )
        except Exception:
            pass
        if rate_limited:
            return f"[web_search] DuckDuckGo rate-limited the request for: '{query}'. Try again shortly."
        return f"[web_search] No results found for: '{query}'"

    if open_first:
        open_browser({"url": results[0]["url"]})

    lines = [f"Search results for: **{query}**\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. **{r['title']}**")
        lines.append(f"   {r['url']}")
        if r["snippet"]:
            lines.append(f"   {r['snippet']}")
        lines.append("")

    return "\n".join(lines).strip()
