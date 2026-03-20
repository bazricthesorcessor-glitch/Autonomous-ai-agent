# ========================= tools/cloud_ai.py =========================
"""
Cloud AI tool — asks Claude.ai, ChatGPT, or Gemini via browser automation.

No API keys needed. Uses the browser you're already logged into.
Requires: playwright + Firefox running (browser_control handles this).

How it works:
  1. Opens the AI site in Firefox (headless=False — you can see it)
  2. Types the prompt into the chat input
  3. Submits and polls DOM until response stops streaming
  4. Extracts only the LAST assistant response
  5. Returns the clean text to Avril

Sites supported:
  claude   → https://claude.ai/new
  chatgpt  → https://chatgpt.com
  gemini   → https://gemini.google.com

Usage by planner:
  {"tool": "cloud_ai", "args": {"site": "claude", "prompt": "explain flip-flops for DSD exam"}}
  {"tool": "cloud_ai", "args": {"site": "chatgpt", "prompt": "derive the expression for current gain"}}
  {"tool": "cloud_ai", "args": {"site": "gemini", "prompt": "compare JK and D flip flops"}}

Auto-selection (site not specified): tries claude → chatgpt → gemini in order.
  {"tool": "cloud_ai", "args": {"prompt": "explain this concept in detail"}}

Prerequisites:
  - Firefox must be open and logged into at least one of these sites.
  - If not logged in, the tool returns a login prompt and opens the site.

Limitations:
  - ~10-20 seconds per query (streaming + polling)
  - Site DOM can change — selectors may need updating if sites update their UI
  - Requires browser window to remain on screen (headless=False)
"""

import time
import re
from tools import registry

# ── Per-site configuration ────────────────────────────────────────────────────
#
# Each site config has:
#   url           — where to navigate for a new chat
#   input_sel     — CSS selector for the chat input (contenteditable or textarea)
#   input_type    — "contenteditable" or "textarea"
#   submit_key    — keyboard shortcut to submit ("Enter" or "Shift+Enter" to newline)
#   stop_sel      — selector visible WHILE streaming (disappears when done)
#   response_sel  — CSS selector for the last AI response block
#   login_hint    — text to check if user is not logged in
#   max_wait      — max seconds to wait for response
#   settle_polls  — how many identical polls before we call it done

_SITE_CONFIGS = {
    "claude": {
        "url":          "https://claude.ai/new",
        "input_sel":    'div[contenteditable="true"].ProseMirror, div[contenteditable="true"][data-placeholder]',
        "input_type":   "contenteditable",
        "submit_key":   "Enter",
        "stop_sel":     'button[aria-label="Stop"], button[aria-label="Stop generating"]',
        "response_sel": '[data-is-streaming], .font-claude-message, div[class*="claude-message"]',
        "last_response_js": """
            (() => {
                const msgs = document.querySelectorAll(
                    '[data-is-streaming], .font-claude-message, div[class*="claude-message"], ' +
                    '[data-testid="assistant-message"]'
                );
                if (!msgs.length) return '';
                const last = msgs[msgs.length - 1];
                return last ? last.innerText.trim() : '';
            })()
        """,
        "streaming_js": """
            (() => {
                const stop = document.querySelector('button[aria-label="Stop"], button[aria-label="Stop generating"]');
                if (stop) return true;
                const streaming = document.querySelector('[data-is-streaming="true"]');
                return !!streaming;
            })()
        """,
        "login_hint":   "Log in",
        "max_wait":     90,
        "settle_polls": 3,
    },
    "chatgpt": {
        "url":          "https://chatgpt.com",
        "input_sel":    "div#prompt-textarea, textarea[data-id], div[contenteditable='true'][id='prompt-textarea']",
        "input_type":   "contenteditable",
        "submit_key":   "Enter",
        "stop_sel":     'button[aria-label="Stop generating"], button[data-testid="stop-button"]',
        "response_sel": '[data-message-author-role="assistant"], .markdown.prose',
        "last_response_js": """
            (() => {
                const msgs = document.querySelectorAll('[data-message-author-role="assistant"]');
                if (!msgs.length) {
                    const md = document.querySelectorAll('.markdown.prose, .prose');
                    if (!md.length) return '';
                    return md[md.length - 1].innerText.trim();
                }
                return msgs[msgs.length - 1].innerText.trim();
            })()
        """,
        "streaming_js": """
            (() => {
                const stop = document.querySelector(
                    'button[aria-label="Stop generating"], button[data-testid="stop-button"]'
                );
                return !!stop;
            })()
        """,
        "login_hint":   "Log in",
        "max_wait":     90,
        "settle_polls": 3,
    },
    "gemini": {
        "url":          "https://gemini.google.com",
        "input_sel":    "rich-textarea div[contenteditable='true'], .ql-editor[contenteditable='true'], div[contenteditable='true'][aria-label]",
        "input_type":   "contenteditable",
        "submit_key":   "Enter",
        "stop_sel":     'button[aria-label="Stop response"], mat-icon[data-mat-icon-name="stop_circle"]',
        "response_sel": "model-response, .response-content, .model-response-text",
        "last_response_js": """
            (() => {
                const responses = document.querySelectorAll(
                    'model-response, .response-content, .model-response-text, ' +
                    '[class*="response"] p, message-content'
                );
                if (!responses.length) return '';
                const last = responses[responses.length - 1];
                return last ? last.innerText.trim() : '';
            })()
        """,
        "streaming_js": """
            (() => {
                const stop = document.querySelector(
                    'button[aria-label="Stop response"], .stop-button, ' +
                    '[data-test-id="stop-button"]'
                );
                if (stop && stop.offsetParent !== null) return true;
                const spinner = document.querySelector('.loading-indicator, .progress-spinner');
                return !!(spinner && spinner.offsetParent !== null);
            })()
        """,
        "login_hint":   "Sign in",
        "max_wait":     90,
        "settle_polls": 3,
    },
}

_SITE_ORDER = ["claude", "chatgpt", "gemini"]


# ── Core helpers ──────────────────────────────────────────────────────────────

def _bc(action: str, **kwargs) -> str:
    """Shorthand for browser_control.run_tool."""
    return registry.run("browser_control", {"action": action, **kwargs})


def _js(script: str) -> str:
    """Evaluate JavaScript in the current page."""
    return _bc("eval_js", script=script)


def _check_login(site: str, cfg: dict) -> bool:
    """Return True if user appears to be logged in."""
    try:
        page_text = _bc("get_text", max_length=500)
        hint = cfg.get("login_hint", "Log in")
        if hint.lower() in page_text.lower() and len(page_text) < 1000:
            return False
        return True
    except Exception:
        return True


def _type_into_contenteditable(selector: str, text: str) -> str:
    """
    Type text into a contenteditable div.
    Playwright's fill() doesn't work on contenteditable — need click + keyboard.type.
    """
    result = _bc("click", selector=selector)
    if "not found" in result.lower() or "error" in result.lower():
        return result
    time.sleep(0.3)

    _js("document.execCommand('selectAll', false, null);")
    time.sleep(0.1)

    chunk_size = 200
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        _bc("type", text=chunk)
        time.sleep(0.05)

    return "Typed into contenteditable"


def _wait_for_response(cfg: dict, prompt_len: int) -> str:
    """
    Poll the page until the AI stops streaming and the response stabilises.

    Strategy:
      1. Wait for streaming indicator to appear (AI started responding)
      2. Poll response text every 2 seconds
      3. When text hasn't changed for settle_polls consecutive polls → done
      4. Hard timeout at max_wait seconds
    """
    max_wait     = cfg.get("max_wait",     90)
    settle       = cfg.get("settle_polls", 3)
    streaming_js = cfg["streaming_js"]
    response_js  = cfg["last_response_js"]

    # Phase 1: wait up to 8s for streaming to START
    started = False
    for _ in range(8):
        time.sleep(1)
        try:
            is_streaming = _js(streaming_js)
            if str(is_streaming).lower() == "true":
                started = True
                break
            text = _js(response_js)
            if text and len(text.strip()) > 20:
                started = True
                break
        except Exception:
            pass

    if not started:
        try:
            text = _js(response_js)
            if text and len(text.strip()) > 20:
                return _clean_response(text)
        except Exception:
            pass
        return "[cloud_ai] Response did not start within 8 seconds. Site may need login or layout changed."

    # Phase 2: wait for streaming to FINISH (text stable)
    prev_text    = ""
    stable_count = 0
    deadline     = time.time() + max_wait

    while time.time() < deadline:
        time.sleep(2)
        try:
            is_streaming = _js(streaming_js)
            current_text = _js(response_js)
        except Exception:
            continue

        current_text = (current_text or "").strip()

        if current_text == prev_text and current_text:
            stable_count += 1
            if stable_count >= settle and str(is_streaming).lower() != "true":
                return _clean_response(current_text)
        else:
            stable_count = 0

        prev_text = current_text

        if str(is_streaming).lower() != "true" and current_text:
            time.sleep(1.5)
            try:
                final = _js(response_js)
                return _clean_response((final or "").strip() or current_text)
            except Exception:
                return _clean_response(current_text)

    last = (_js(response_js) or "").strip()
    if last:
        return _clean_response(last) + "\n[Note: response may be incomplete — timeout]"
    return "[cloud_ai] Timed out waiting for response."


def _clean_response(text: str) -> str:
    """Strip UI chrome, copy buttons, and other noise from scraped text."""
    if not text:
        return ""
    noise_patterns = [
        r'Copy code\n',
        r'Copy\n',
        r'Retry\n',
        r'Edit\n',
        r'\d+ of \d+\n',
        r'Regenerate response\n',
        r'Stop generating\n',
        r'Stop response\n',
        r'Like\nDislike\n',
        r'^\s*\d+\s*$',
    ]
    for pat in noise_patterns:
        text = re.sub(pat, '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    return text.strip()


# ── Main ask function ─────────────────────────────────────────────────────────

def _ask_site(site: str, prompt: str) -> str:
    """Ask a single AI site. Returns response text or error string."""
    cfg = _SITE_CONFIGS.get(site)
    if not cfg:
        return f"[cloud_ai] Unknown site '{site}'."

    nav_result = _bc("open", url=cfg["url"])
    if "error" in nav_result.lower():
        return f"[cloud_ai] Could not open {site}: {nav_result}"

    time.sleep(3)

    if not _check_login(site, cfg):
        return (
            f"[cloud_ai] Not logged into {site}. "
            f"Please log in at {cfg['url']} in Firefox, then try again."
        )

    input_sel   = cfg["input_sel"]
    found_input = False
    for sel in input_sel.split(", "):
        sel          = sel.strip()
        click_result = _bc("click", selector=sel)
        if "not found" not in click_result.lower() and "error" not in click_result.lower():
            found_input = True
            break

    if not found_input:
        _js("document.querySelector('[contenteditable]')?.focus()")
        time.sleep(0.3)

    if cfg.get("input_type") == "contenteditable":
        type_result = _type_into_contenteditable(input_sel.split(",")[0].strip(), prompt)
    else:
        type_result = _bc("type", selector=input_sel.split(",")[0].strip(), text=prompt)

    if "error" in type_result.lower():
        return f"[cloud_ai] Could not type prompt into {site}: {type_result}"

    time.sleep(0.5)
    _bc("press", key=cfg["submit_key"])
    time.sleep(0.5)

    return _wait_for_response(cfg, len(prompt))


# ── Public tool dispatcher ────────────────────────────────────────────────────

def run_tool(args: dict = None) -> str:
    if args is None:
        args = {}

    prompt = str(args.get("prompt", "")).strip()
    if not prompt:
        return (
            "[cloud_ai] 'prompt' is required.\n"
            "Usage: {\"tool\": \"cloud_ai\", \"args\": {\"site\": \"claude\", \"prompt\": \"your question\"}}\n"
            "Sites: claude, chatgpt, gemini\n"
            "Omit 'site' to auto-select."
        )

    site = str(args.get("site", "")).strip().lower()

    aliases = {
        "claude.ai":         "claude",
        "anthropic":         "claude",
        "chatgpt.com":       "chatgpt",
        "openai":            "chatgpt",
        "gpt":               "chatgpt",
        "gemini.google.com": "gemini",
        "google":            "gemini",
        "bard":              "gemini",
    }
    site = aliases.get(site, site)

    if site and site in _SITE_CONFIGS:
        return _ask_site(site, prompt)

    if not site:
        errors = []
        for s in _SITE_ORDER:
            result = _ask_site(s, prompt)
            if not result.startswith("[cloud_ai]"):
                return result
            errors.append(f"{s}: {result}")
        return (
            "[cloud_ai] All sites failed. Make sure Firefox is open and you're logged in.\n"
            + "\n".join(errors)
        )

    return f"[cloud_ai] Unknown site '{site}'. Available: claude, chatgpt, gemini"
