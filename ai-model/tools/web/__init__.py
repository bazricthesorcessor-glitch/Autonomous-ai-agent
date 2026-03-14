# ========================= tools/web/__init__.py =========================
"""
Web browser automation tools — package entry point.

Structure:
  tools/web/
    __init__.py      ← this file (dispatcher)
    http_client.py   ← shared SSL-aware HTTP helpers + HTML-to-text
    browser.py       ← open_browser (Firefox only)
    search.py        ← web_search   (DuckDuckGo HTML + Lite fallback)
    fetch.py         ← fetch_page, scrape_page
    wikipedia.py     ← wikipedia    (REST API, no key)
    inspect.py       ← inspect_page, find_forms, find_buttons, find_links, find_headings

Usage:
  from tools import web
  web.run_tool({"action": "web_search",    "query": "python news"})
  web.run_tool({"action": "open_browser",  "url": "github.com"})
  web.run_tool({"action": "fetch_page",    "url": "https://example.com"})
  web.run_tool({"action": "scrape_page",   "url": "https://python.org"})
  web.run_tool({"action": "wikipedia",     "query": "quantum computing"})
  web.run_tool({"action": "inspect_page",  "url": "https://example.com"})
  web.run_tool({"action": "find_forms",    "url": "https://example.com"})
  web.run_tool({"action": "find_buttons",  "url": "https://example.com"})
  web.run_tool({"action": "find_links",    "url": "https://example.com"})
  web.run_tool({"action": "find_headings", "url": "https://example.com"})
  web.run_tool({"action": "list"})
"""

from tools.web.browser   import open_browser
from tools.web.search    import web_search
from tools.web.fetch     import fetch_page, scrape_page
from tools.web.wikipedia import wikipedia
from tools.web.inspect   import (
    inspect_page, find_forms, find_buttons, find_links, find_headings
)


def _list_actions(_: dict) -> str:
    return (
        "Web tools  (tools/web/)\n"
        "  open_browser    Open URL in detected browser   [url, private=false]          → browser.py\n"
        "  web_search      DuckDuckGo + Lite fallback     [query, max_results=5]        → search.py\n"
        "  fetch_page      Readable page text             [url, max_chars=3000]         → fetch.py\n"
        "  scrape_page     Text + external links          [url, max_chars=2000]         → fetch.py\n"
        "  wikipedia       Wikipedia summary              [query, lang=en, full=false]  → wikipedia.py\n"
        "  inspect_page    Full page structure map        [url, max_links=20]           → inspect.py\n"
        "  find_forms      All forms & input fields       [url]                         → inspect.py\n"
        "  find_buttons    All buttons & submits          [url]                         → inspect.py\n"
        "  find_links      All navigation links           [url, max_links=30]           → inspect.py\n"
        "  find_headings   Heading hierarchy h1–h3        [url]                         → inspect.py"
    )


_ACTIONS = {
    "open_browser":  open_browser,
    "web_search":    web_search,
    "fetch_page":    fetch_page,
    "scrape_page":   scrape_page,
    "wikipedia":     wikipedia,
    "inspect_page":  inspect_page,
    "find_forms":    find_forms,
    "find_buttons":  find_buttons,
    "find_links":    find_links,
    "find_headings": find_headings,
    "list":          _list_actions,
}


def run_tool(args: dict = None) -> str:
    if args is None:
        args = {}
    action = str(args.get("action", "")).strip().lower()
    if not action:
        return "[web] No action specified. Use action='list' to see available tools."
    fn = _ACTIONS.get(action)
    if fn is None:
        return f"[web] Unknown action '{action}'. Available: {', '.join(_ACTIONS)}"
    try:
        return fn(args)
    except Exception as e:
        return f"[web] Error in '{action}': {e}"
