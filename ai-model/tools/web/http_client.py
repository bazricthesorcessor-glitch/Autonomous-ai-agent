# ========================= tools/web/http_client.py =========================
"""
Shared HTTP utilities for all web submodules.
Provides http_get, http_post, html_to_text with SSL verification.
"""

import ipaddress
import re
import socket
import ssl
import urllib.request
import urllib.parse
import urllib.error
from html.parser import HTMLParser

# SSL context: certifi bundle → system default
try:
    import certifi as _certifi
    SSL_CTX = ssl.create_default_context(cafile=_certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

TIMEOUT = 12  # seconds


def _is_private_url(url: str) -> bool:
    """Return True if the URL resolves to a private/loopback IP (SSRF guard)."""
    try:
        host = urllib.parse.urlparse(url).hostname
        if not host:
            return True
        for info in socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM):
            addr = info[4][0]
            if ipaddress.ip_address(addr).is_private:
                return True
    except Exception:
        pass  # DNS failure → let urlopen handle it
    return False


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Block redirects to private/internal IPs."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _is_private_url(newurl):
            raise urllib.error.URLError(
                f"Redirect to private network blocked: {newurl}"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirectHandler)


def http_get(url: str, extra_headers: dict = None) -> str:
    """GET request with SSL verification. Returns response body as string."""
    if _is_private_url(url):
        raise urllib.error.URLError(f"Request to private network blocked: {url}")
    req = urllib.request.Request(url, headers={**HEADERS, **(extra_headers or {})})
    with _opener.open(req, timeout=TIMEOUT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def http_post(url: str, data: dict) -> str:
    """POST url-encoded form data with SSL verification."""
    if _is_private_url(url):
        raise urllib.error.URLError(f"Request to private network blocked: {url}")
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, headers={
        **HEADERS,
        "Content-Type": "application/x-www-form-urlencoded",
    })
    with _opener.open(req, timeout=TIMEOUT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


# ---------------------------------------------------------------------------
# HTML → plain text (no external deps)
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    _SKIP  = {"script", "style", "head", "noscript", "meta", "link", "svg", "path"}
    _BLOCK = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6",
              "li", "tr", "td", "th", "blockquote", "pre", "article",
              "section", "header", "footer", "main", "aside"}

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        if tag in self._BLOCK and self._parts and self._parts[-1] != "\n":
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
        if tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0:
            clean = data.strip()
            if clean:
                self._parts.append(clean + " ")

    def get_text(self) -> str:
        raw = "".join(self._parts)
        return re.sub(r"\n{3,}", "\n\n", raw).strip()


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    return p.get_text()
