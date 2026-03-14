# ========================= tools/browser_control.py =========================
"""
Browser automation via Playwright — Layer 1 (DOM control).

This is the most reliable way to interact with websites.
Uses the browser's own DOM instead of OCR/coordinate guessing.

Actions:
  open          Navigate to a URL (launches browser if needed)
                {"action": "open", "url": "https://youtube.com"}

  click         Click an element by CSS selector or text content
                {"action": "click", "selector": "input[name='search_query']"}
                {"action": "click", "text": "Sign in"}

  type          Type text into a focused element or a specific selector
                {"action": "type", "selector": "input[name='search_query']", "text": "coconut oil"}
                {"action": "type", "text": "coconut oil"}  ← types into currently focused element

  press         Press a keyboard key
                {"action": "press", "key": "Enter"}

  get_text      Get visible text from the page or a specific element
                {"action": "get_text"}
                {"action": "get_text", "selector": "#results"}

  get_elements  List interactive elements on the page (forms, buttons, links, inputs)
                {"action": "get_elements"}
                {"action": "get_elements", "filter": "input"}

  screenshot    Take a screenshot of the current page
                {"action": "screenshot"}

  scroll        Scroll the page
                {"action": "scroll", "direction": "down"}
                {"action": "scroll", "direction": "up", "amount": 500}

  wait          Wait for an element to appear
                {"action": "wait", "selector": "#search-results", "timeout": 10}

  close         Close the browser
                {"action": "close"}

  eval_js       Run JavaScript on the page (advanced)
                {"action": "eval_js", "script": "document.title"}

Typical workflow for "search YouTube for coconut oil":
  1. open         url=https://youtube.com
  2. click        selector=input[name='search_query']
  3. type         text=coconut oil
  4. press        key=Enter
  5. get_text     selector=#contents   ← read search results

Design:
  - Single persistent browser instance (reused across calls)
  - Headless=False so the user sees the browser on screen
  - Firefox (Playwright-managed)
  - Falls through to computer_use.py (OCR layer) for desktop apps
"""

import os
import json
import time
import threading

import config

_SCREENSHOT_PATH = os.path.join(config.SCREENSHOT_DIR, "_browser.png")

# ── Persistent browser state (singleton) ────────────────────────────────────

_lock = threading.Lock()
_playwright = None
_browser = None
_context = None
_page = None


def _ensure_browser():
    """Launch browser if not already running. Returns the active page."""
    global _playwright, _browser, _context, _page

    with _lock:
        # Already running and page is still open
        if _page is not None:
            try:
                _ = _page.url  # quick health check
                return _page
            except Exception:
                # Page or browser died — restart
                _cleanup_unlocked()

        from playwright.sync_api import sync_playwright

        _playwright = sync_playwright().start()
        _browser = _playwright.firefox.launch(
            headless=False,
        )
        _context = _browser.new_context(
            viewport={"width": 1280, "height": 900},
        )
        _page = _context.new_page()
        return _page


def _cleanup_unlocked():
    """Internal cleanup (caller must hold _lock)."""
    global _playwright, _browser, _context, _page
    try:
        if _page:
            _page.close()
    except Exception:
        pass
    try:
        if _context:
            _context.close()
    except Exception:
        pass
    try:
        if _browser:
            _browser.close()
    except Exception:
        pass
    try:
        if _playwright:
            _playwright.stop()
    except Exception:
        pass
    _playwright = _browser = _context = _page = None


def _close_browser():
    """Public close — acquires lock."""
    with _lock:
        _cleanup_unlocked()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _find_by_text(page, text: str, click: bool = False):
    """
    Find an element by visible text. Tries multiple strategies:
    1. getByText (Playwright built-in)
    2. getByRole with name
    3. CSS contains-text selectors
    """
    strategies = [
        lambda: page.get_by_text(text, exact=False).first,
        lambda: page.get_by_role("button", name=text).first,
        lambda: page.get_by_role("link", name=text).first,
        lambda: page.get_by_placeholder(text).first,
        lambda: page.get_by_label(text).first,
    ]
    for strategy in strategies:
        try:
            el = strategy()
            if el.is_visible(timeout=2000):
                if click:
                    el.click(timeout=5000)
                return el
        except Exception:
            continue
    return None


def _safe_selector(page, selector: str, timeout: int = 5000):
    """Wait for selector and return the element, or None."""
    try:
        page.wait_for_selector(selector, timeout=timeout)
        return page.query_selector(selector)
    except Exception:
        return None


# ── Public tool dispatcher ───────────────────────────────────────────────────

def run_tool(args: dict = None) -> str:
    if args is None:
        args = {}

    action = str(args.get("action", "")).strip().lower()

    # ── open ─────────────────────────────────────────────────────────────
    if action == "open":
        url = str(args.get("url", "")).strip()
        if not url:
            return "Error: 'url' parameter is required"
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            page = _ensure_browser()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Extra wait for dynamic sites like YouTube
            time.sleep(1)
            return f"Opened: {page.url}  (title: {page.title()})"
        except Exception as e:
            return f"Error opening {url}: {e}"

    # ── click ────────────────────────────────────────────────────────────
    elif action == "click":
        selector = str(args.get("selector", "")).strip()
        text = str(args.get("text", "")).strip()
        if not selector and not text:
            return "Error: 'selector' or 'text' parameter is required"

        try:
            page = _ensure_browser()

            if selector:
                el = _safe_selector(page, selector)
                if el:
                    el.click()
                    return f"Clicked: {selector}"
                # Fallback: try text match
                if not text:
                    return f"Element not found: {selector}"

            if text:
                el = _find_by_text(page, text, click=True)
                if el:
                    return f"Clicked element with text: '{text}'"
                return f"No visible element found with text: '{text}'"
        except Exception as e:
            return f"Click error: {e}"

    # ── type ─────────────────────────────────────────────────────────────
    elif action == "type":
        text = str(args.get("text", ""))
        selector = str(args.get("selector", "")).strip()
        clear = args.get("clear", True)

        if not text:
            return "Error: 'text' parameter is required"

        try:
            page = _ensure_browser()

            if selector:
                el = _safe_selector(page, selector)
                if not el:
                    return f"Element not found: {selector}"
                if clear:
                    el.fill("")
                el.fill(text)
                return f"Typed into {selector}: '{text}'"
            else:
                # Type into currently focused element
                page.keyboard.type(text, delay=50)
                return f"Typed: '{text}'"
        except Exception as e:
            return f"Type error: {e}"

    # ── press ────────────────────────────────────────────────────────────
    elif action == "press":
        key = str(args.get("key", "")).strip()
        if not key:
            return "Error: 'key' parameter is required"
        try:
            page = _ensure_browser()
            page.keyboard.press(key)
            return f"Pressed: {key}"
        except Exception as e:
            return f"Press error: {e}"

    # ── get_text ─────────────────────────────────────────────────────────
    elif action == "get_text":
        selector = str(args.get("selector", "")).strip()
        max_len = int(args.get("max_length", 3000))

        try:
            page = _ensure_browser()
            if selector:
                el = _safe_selector(page, selector, timeout=5000)
                if not el:
                    return f"Element not found: {selector}"
                txt = el.inner_text()
            else:
                txt = page.inner_text("body")

            if len(txt) > max_len:
                txt = txt[:max_len] + f"\n... (truncated, {len(txt)} chars total)"
            return txt.strip() or "(empty)"
        except Exception as e:
            return f"get_text error: {e}"

    # ── get_elements ─────────────────────────────────────────────────────
    elif action == "get_elements":
        filter_type = str(args.get("filter", "")).strip().lower()
        max_items = int(args.get("max", 40))

        try:
            page = _ensure_browser()
            # Build a selector for interactive elements
            selectors = {
                "input": "input:visible, textarea:visible",
                "button": "button:visible, [role='button']:visible, input[type='submit']:visible",
                "link": "a[href]:visible",
                "form": "form:visible",
            }

            if filter_type and filter_type in selectors:
                css = selectors[filter_type]
            else:
                css = "a[href]:visible, button:visible, input:visible, textarea:visible, select:visible, [role='button']:visible"

            elements = page.query_selector_all(css)
            lines = []
            for i, el in enumerate(elements[:max_items]):
                tag = el.evaluate("e => e.tagName.toLowerCase()")
                etype = el.get_attribute("type") or ""
                name = el.get_attribute("name") or ""
                placeholder = el.get_attribute("placeholder") or ""
                aria = el.get_attribute("aria-label") or ""
                href = el.get_attribute("href") or ""
                text = (el.inner_text() or "").strip()[:60]

                desc_parts = [f"<{tag}"]
                if etype:
                    desc_parts.append(f' type="{etype}"')
                if name:
                    desc_parts.append(f' name="{name}"')
                if placeholder:
                    desc_parts.append(f' placeholder="{placeholder}"')
                if aria:
                    desc_parts.append(f' aria-label="{aria}"')
                if href:
                    short_href = href[:80] + ("..." if len(href) > 80 else "")
                    desc_parts.append(f' href="{short_href}"')
                desc_parts.append(">")
                if text:
                    desc_parts.append(f" {text}")

                lines.append(f"  {i+1}. {''.join(desc_parts)}")

            total = len(elements)
            header = f"[{total} interactive elements"
            if total > max_items:
                header += f", showing first {max_items}"
            header += "]"
            return header + "\n" + "\n".join(lines) if lines else "No interactive elements found"
        except Exception as e:
            return f"get_elements error: {e}"

    # ── screenshot ───────────────────────────────────────────────────────
    elif action == "screenshot":
        try:
            page = _ensure_browser()
            page.screenshot(path=_SCREENSHOT_PATH, full_page=False)
            title = page.title()
            url = page.url
            return f"Screenshot saved: {_SCREENSHOT_PATH}\nPage: {title}\nURL: {url}"
        except Exception as e:
            return f"Screenshot error: {e}"

    # ── scroll ───────────────────────────────────────────────────────────
    elif action == "scroll":
        direction = str(args.get("direction", "down")).strip().lower()
        amount = int(args.get("amount", 400))
        try:
            page = _ensure_browser()
            delta = amount if direction == "down" else -amount
            page.mouse.wheel(0, delta)
            time.sleep(0.3)
            return f"Scrolled {direction} by {amount}px"
        except Exception as e:
            return f"Scroll error: {e}"

    # ── wait ─────────────────────────────────────────────────────────────
    elif action == "wait":
        selector = str(args.get("selector", "")).strip()
        timeout = int(args.get("timeout", 10)) * 1000
        if not selector:
            return "Error: 'selector' parameter is required"
        try:
            page = _ensure_browser()
            page.wait_for_selector(selector, timeout=timeout)
            return f"Element appeared: {selector}"
        except Exception as e:
            return f"Timeout waiting for '{selector}': {e}"

    # ── close ────────────────────────────────────────────────────────────
    elif action == "close":
        _close_browser()
        return "Browser closed"

    # ── eval_js ──────────────────────────────────────────────────────────
    elif action == "eval_js":
        script = str(args.get("script", "")).strip()
        if not script:
            return "Error: 'script' parameter is required"
        try:
            page = _ensure_browser()
            result = page.evaluate(script)
            return str(result)
        except Exception as e:
            return f"JS eval error: {e}"

    else:
        return (
            f"Unknown action: '{action}'. "
            "Available: open, click, type, press, get_text, get_elements, "
            "screenshot, scroll, wait, close, eval_js"
        )
