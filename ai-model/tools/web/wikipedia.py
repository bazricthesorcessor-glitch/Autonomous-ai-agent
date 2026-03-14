# ========================= tools/web/wikipedia.py =========================
"""Wikipedia article search and summary via the official REST API."""

import json
import urllib.parse
from tools.web.http_client import http_get


def wikipedia(args: dict) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "[wikipedia] No 'query' provided."

    lang = str(args.get("lang", "en")).strip().lower()[:5]
    full = str(args.get("full", "false")).lower() in ("true", "1", "yes")

    # Step 1: find page title via opensearch
    search_url = (
        f"https://{lang}.wikipedia.org/w/api.php?"
        + urllib.parse.urlencode({
            "action":    "opensearch",
            "search":    query,
            "limit":     "3",
            "format":    "json",
            "redirects": "resolve",
        })
    )
    try:
        raw   = http_get(search_url, {"Accept": "application/json"})
        data  = json.loads(raw)
    except Exception as e:
        return f"[wikipedia] Search failed: {e}"

    titles = data[1] if len(data) > 1 else []
    if not titles:
        return f"[wikipedia] No Wikipedia article found for: '{query}'"

    # Step 2: get summary via REST API
    page_title    = titles[0]
    encoded_title = urllib.parse.quote(page_title.replace(" ", "_"))
    summary_url   = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{encoded_title}"

    try:
        summary_raw = http_get(summary_url, {"Accept": "application/json"})
        info = json.loads(summary_raw)
    except Exception as e:
        return f"[wikipedia] Summary fetch failed: {e}"

    if info.get("type") == "disambiguation":
        options = "\n".join(f"  - {t}" for t in titles)
        return (
            f"Wikipedia disambiguation for '{query}':\n{options}\n\n"
            "Try a more specific query."
        )

    title   = info.get("title", page_title)
    extract = info.get("extract", info.get("description", "No summary available."))
    url     = info.get("content_urls", {}).get("desktop", {}).get("page", summary_url)

    if not full and len(extract) > 1500:
        extract = extract[:1500] + "\n[... truncated. Use full=true for complete text]"

    return f"**{title}** — Wikipedia\n\n{extract}\n\nSource: {url}"
