# ========================= tools/browser_control.py =========================
"""
Browser control — lightweight stub (Playwright removed).

Browser interactions now go through MAI-UI in computer_use.py / vision.py.
This module is kept as a stub so web/search.py and registry.py don't crash.

Available actions (thin wrappers — no DOM, no Playwright):
  open      Open a URL in Firefox via subprocess
            {"action": "open", "url": "https://youtube.com"}

  close     No-op (kept for compatibility)

  page_state  Returns "UNKNOWN" (no DOM polling available)

  screenshot  Takes a grim screenshot, returns path

  get_text  Returns a message directing to use vision.read_screen instead

All other actions (click, type, press, get_elements, eval_js, scroll, wait)
now return guidance to use computer_use.mai_ui_act instead.
"""

import os
import time
import subprocess

import config

_SCREENSHOT_PATH = os.path.join(config.SCREENSHOT_DIR, "_browser.png")


def run_tool(args: dict = None) -> str:
    if args is None:
        args = {}

    action = str(args.get("action", "")).strip().lower()

    # ── open ─────────────────────────────────────────────────────────────────
    if action == "open":
        url = str(args.get("url", "")).strip()
        if not url:
            return "Error: 'url' parameter is required"
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            subprocess.Popen(["firefox", url])
            time.sleep(3.5)
            for selector in ("class:firefox", "firefox"):
                try:
                    subprocess.run(
                        ["hyprctl", "dispatch", "focuswindow", selector],
                        capture_output=True, text=True, timeout=3
                    )
                    break
                except Exception:
                    pass
            return f"Opened: {url}"
        except Exception as e:
            return f"Error opening URL: {e}"

    # ── screenshot ────────────────────────────────────────────────────────────
    elif action == "screenshot":
        try:
            subprocess.run(["grim", _SCREENSHOT_PATH],
                           check=True, capture_output=True, timeout=8)
            return f"Screenshot saved: {_SCREENSHOT_PATH}"
        except Exception as e:
            return f"Screenshot failed: {e}"

    # ── page_state ────────────────────────────────────────────────────────────
    elif action == "page_state":
        # No DOM available — try OCR heuristic via vision
        try:
            from tools import vision
            return vision.run_tool({"action": "page_state"})
        except Exception:
            return "UNKNOWN"

    # ── close ─────────────────────────────────────────────────────────────────
    elif action == "close":
        return "Browser close: no persistent browser session (Playwright removed)"

    # ── get_text ──────────────────────────────────────────────────────────────
    elif action == "get_text":
        # Fallback: OCR the screen
        try:
            from tools import vision
            return vision.run_tool({"action": "read_screen"})
        except Exception as e:
            return f"[browser_control] get_text fallback failed: {e}"

    # ── get_elements ──────────────────────────────────────────────────────────
    elif action == "get_elements":
        try:
            from tools import vision
            return vision.run_tool({"action": "list_elements"})
        except Exception as e:
            return f"[browser_control] get_elements fallback failed: {e}"

    # ── click / type / press / scroll / wait / eval_js ────────────────────────
    elif action in ("click", "type", "press", "scroll", "wait", "eval_js"):
        return (
            f"[browser_control] Playwright removed. "
            f"Use computer_use with action='mai_ui_act' and describe your task. "
            f"Example: {{\"action\": \"mai_ui_act\", \"task\": \"click the sign in button\"}}"
        )

    else:
        return (
            f"[browser_control] Unknown action '{action}'. "
            "Available: open, screenshot, page_state, close, get_text, get_elements"
        )