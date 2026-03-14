"""Structured perception tool for AVRIL.

Vision never performs actions directly. It only answers perception questions.

Actions:
  locate            Locate a UI element and return coordinates as JSON
  page_state        Capture OCR state and classify it as LOADING / READY / ERROR
  wait_ready        Poll page_state until READY or ERROR
  monitor_response  Poll OCR until text stops changing for several cycles
"""

from __future__ import annotations

import json
import time

import config
from tools import screenshot, ui_parser

_ERROR_HINTS = (
    "error", "failed", "not found", "denied", "unavailable", "offline",
    "try again", "went wrong", "exception",
)

_LOADING_HINTS = (
    "loading", "please wait", "just a moment", "redirecting", "checking",
    "signing in", "generating", "thinking", "processing",
)


def _json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


def _get_cached_screen() -> dict:
    return config.safe_load_json(config.SCREEN_CACHE_FILE, {})


def _classify_page_state(text: str) -> str:
    normalized = (text or "").strip().lower()
    if any(token in normalized for token in _ERROR_HINTS):
        return "ERROR"
    if not normalized or any(token in normalized for token in _LOADING_HINTS):
        return "LOADING"
    return "READY"


def _capture(mode: str = "active_window") -> dict:
    screenshot.run_tool({"mode": mode})
    return _get_cached_screen()


def _locate(args: dict) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return _json({"error": "'query' parameter is required"})

    app_hint = str(args.get("app", "")).strip()
    confidence = float(args.get("confidence", 0.25))
    if app_hint:
        from tools.computer_use import _get_window_region
        min_x, max_x, min_y, max_y = _get_window_region(app_hint)
        elements = ui_parser.parse_screen(min_x, max_x, min_y, max_y, confidence)
    else:
        elements = ui_parser.parse_screen(confidence=confidence)

    found = ui_parser.find_element(query, elements)
    if not found:
        return _json({"query": query, "state": "NOT_FOUND"})

    return _json({
        "query": query,
        "state": "FOUND",
        "type": found.get("type", "unknown"),
        "text": found.get("text", ""),
        "coordinates": [found.get("click_x", found.get("cx")), found.get("click_y", found.get("cy"))],
        "confidence": found.get("conf", 0),
    })


def _page_state(args: dict) -> str:
    mode = str(args.get("mode", "active_window")).strip() or "active_window"
    cache = _capture(mode)
    text = cache.get("last_screen_text", "")
    state = _classify_page_state(text)
    return _json({
        "state": state,
        "mode": cache.get("mode", mode),
        "changed": cache.get("changed", False),
        "text_excerpt": text[:500],
        "timestamp": cache.get("timestamp", ""),
    })


def _wait_ready(args: dict) -> str:
    mode = str(args.get("mode", "active_window")).strip() or "active_window"
    interval = max(0.5, float(args.get("interval", config.PERCEPTION_POLL_INTERVAL)))
    timeout = max(interval, float(args.get("timeout", 12)))
    deadline = time.time() + timeout
    last = {"state": "LOADING"}
    polls = 0

    while time.time() < deadline:
        last = json.loads(_page_state({"mode": mode}))
        polls += 1
        if last.get("state") in {"READY", "ERROR"}:
            last["polls"] = polls
            return _json(last)
        time.sleep(interval)

    last["polls"] = polls
    last["timed_out"] = True
    return _json(last)


def _monitor_response(args: dict) -> str:
    mode = str(args.get("mode", "active_window")).strip() or "active_window"
    interval = max(0.5, float(args.get("interval", config.PERCEPTION_POLL_INTERVAL)))
    stable_polls = max(2, int(args.get("stable_polls", config.RESPONSE_STABLE_POLLS)))
    timeout = max(interval, float(args.get("timeout", 18)))
    deadline = time.time() + timeout
    last_text = ""
    unchanged = 0
    polls = 0

    while time.time() < deadline:
        cache = _capture(mode)
        text = (cache.get("last_screen_text", "") or "").strip()
        polls += 1
        if any(token in text.lower() for token in _ERROR_HINTS):
            return _json({"state": "ERROR", "polls": polls, "text_excerpt": text[:500]})
        if text and text == last_text:
            unchanged += 1
        else:
            unchanged = 0
        last_text = text
        if text and unchanged >= stable_polls:
            return _json({"state": "COMPLETE", "polls": polls, "text_excerpt": text[:500]})
        time.sleep(interval)

    return _json({"state": "GENERATING", "polls": polls, "text_excerpt": last_text[:500], "timed_out": True})


def run_tool(args: dict = None) -> str:
    if args is None:
        args = {}

    action = str(args.get("action", "page_state")).strip().lower()
    if action == "locate":
        return _locate(args)
    if action == "page_state":
        return _page_state(args)
    if action == "wait_ready":
        return _wait_ready(args)
    if action == "monitor_response":
        return _monitor_response(args)
    return _json({"error": f"Unknown action: {action}"})