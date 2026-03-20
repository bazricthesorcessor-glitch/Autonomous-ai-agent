# ========================= tools/web/research.py =========================
"""
Deep research pipeline — multi-source, multi-step.

Runs the full pipeline automatically in one planner step:
  Step 1: DuckDuckGo search → 5 snippets + URLs
  Step 2: Fetch top N article pages (2000 chars each)
  Step 3: Wikipedia summary for background context
  Step 4: Return combined context for LLM synthesis

Usage:
  {"tool": "web", "args": {"action": "deep_research", "query": "flip flops vs latches DSD"}}
  {"tool": "web", "args": {"action": "deep_research", "query": "current divider formula", "max_sources": 2}}

Parameters:
  query          (required) — the research topic
  max_sources    (default 3, max 5) — number of article pages to fetch

Returns a combined context string. Avril synthesizes the final answer.
"""

import re

from tools.web.search    import web_search
from tools.web.fetch     import fetch_page
from tools.web.wikipedia import wikipedia


_MAX_OUTPUT = 8000   # chars — keeps response within phi4-mini context window

# Skip these domains when extracting fetch URLs from search results
_SKIP_DOMAINS = frozenset({
    'duckduckgo.com', 'google.com', 'bing.com', 'yahoo.com',
    'reddit.com/search', 'twitter.com', 'x.com',
})


def deep_research(args: dict) -> str:
    """Multi-source research: search → fetch top sources → Wikipedia → combined context."""
    query = str(args.get("query", "")).strip()
    if not query:
        return "[deep_research] No 'query' provided."

    max_sources = max(1, min(int(args.get("max_sources", 3)), 5))

    parts = []

    # ── Step 1: DuckDuckGo search ─────────────────────────────────────────────
    search_result = web_search({"query": query, "max_results": 5})
    parts.append(f"## Search snippets\n{search_result}")

    # ── Step 2: Extract URLs and fetch article text ───────────────────────────
    raw_urls = re.findall(r'https?://[^\s\)\]\"\'<>]+', search_result)

    seen: set = set()
    unique_urls: list = []
    for u in raw_urls:
        u = u.rstrip('.,;)')
        if u in seen:
            continue
        if any(d in u for d in _SKIP_DOMAINS):
            continue
        if u.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.pdf', '.svg', '.webp')):
            continue
        seen.add(u)
        unique_urls.append(u)

    fetched = 0
    for url in unique_urls[:max_sources * 2]:   # try extra in case some fail/JS-only
        if fetched >= max_sources:
            break
        result = fetch_page({"url": url, "max_chars": 2000})
        # skip errors, JS-shell redirects, and suspiciously short pages
        if result.startswith("[fetch_page]") or len(result.strip()) < 200:
            continue
        parts.append(f"## Source {fetched + 1}: {url}\n{result}")
        fetched += 1

    # ── Step 3: Wikipedia background ─────────────────────────────────────────
    wiki = wikipedia({"query": query, "full": "false"})
    if not wiki.startswith("[wikipedia]"):
        parts.append(f"## Wikipedia\n{wiki}")
        wiki_ok = True
    else:
        wiki_ok = False

    # ── Step 4: Combine and truncate ─────────────────────────────────────────
    combined = "\n\n".join(parts)
    if len(combined) > _MAX_OUTPUT:
        combined = combined[:_MAX_OUTPUT] + "\n\n[... research truncated at 8000 chars]"

    source_count = fetched + (1 if wiki_ok else 0)
    header = f"[deep_research] Query: '{query}' | Sources: {source_count}\n\n"
    return header + combined
