# ========================= tools/web/fetch.py =========================
"""Fetch a URL and return readable text or text+links (scrape)."""

import urllib.error
from html.parser import HTMLParser
from tools.web.http_client import http_get, html_to_text


class _LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href and href.startswith(("http://", "https://")):
                self.links.append(href)


def fetch_page(args: dict) -> str:
    """Fetch a URL and return clean readable text."""
    url = str(args.get("url", "")).strip()
    if not url:
        return "[fetch_page] No 'url' provided."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    max_chars = max(500, min(int(args.get("max_chars", 3000)), 10000))

    try:
        html = http_get(url)
    except urllib.error.HTTPError as e:
        return f"[fetch_page] HTTP {e.code}: {e.reason} — {url}"
    except urllib.error.URLError as e:
        return f"[fetch_page] Connection failed: {e.reason}"
    except Exception as e:
        return f"[fetch_page] Error: {e}"

    text = html_to_text(html)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[... truncated at {max_chars} chars]"

    return f"**{url}**\n\n{text}"


def scrape_page(args: dict) -> str:
    """Fetch a URL and return text + extracted external links."""
    url = str(args.get("url", "")).strip()
    if not url:
        return "[scrape_page] No 'url' provided."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    max_chars = max(500, min(int(args.get("max_chars", 2000)), 8000))
    max_links = int(args.get("max_links", 10))

    try:
        html = http_get(url)
    except urllib.error.HTTPError as e:
        return f"[scrape_page] HTTP {e.code}: {e.reason} — {url}"
    except urllib.error.URLError as e:
        return f"[scrape_page] Connection failed: {e.reason}"
    except Exception as e:
        return f"[scrape_page] Error: {e}"

    text = html_to_text(html)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[... truncated]"

    # Deduplicated links
    lp = _LinkExtractor()
    lp.feed(html)
    seen, unique = set(), []
    for lnk in lp.links:
        if lnk not in seen:
            seen.add(lnk)
            unique.append(lnk)

    links_section = ""
    if unique:
        shown = unique[:max_links]
        links_section = "\n\n**Links found:**\n" + "\n".join(f"  - {l}" for l in shown)
        if len(unique) > max_links:
            links_section += f"\n  ... and {len(unique) - max_links} more"

    return f"**{url}**\n\n{text}{links_section}"
