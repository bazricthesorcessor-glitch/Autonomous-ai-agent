# ========================= tools/computer_use.py =========================
"""
Computer use — screen interaction using MAI-UI vision model.

REMOVED (old pipeline):
  - tesseract OCR-based find_on_screen / click_text
  - YOLO ui_parser scan_screen / click_map / smart_click
  - type_into (OCR-based element finder)

NEW (MAI-UI pipeline):
  mai_ui_act    Send a task description → MAI-UI looks at screen →
                returns best action → auto-executed via ydotool.
                {"action": "mai_ui_act", "task": "click the login button"}
                {"action": "mai_ui_act", "task": "type 'hello' in the search box"}

KEPT (unchanged helpers):
  focus_window  Bring app to foreground (hyprctl)
  open_url      Launch Firefox with a URL
  type_text     Type text at current cursor position (ydotool)
  press_key     Press a key or shortcut (ydotool)
  screenshot    Fullscreen capture + OCR summary
  click_element Click a pre-saved named pixel position
  save_position Save current cursor pos to ui_positions.json
  list_positions List all saved positions
"""

import os
import json as _json
import time
import subprocess
import hashlib

import config

_CU_PNG        = os.path.join(config.SCREENSHOT_DIR, "_cu_screen.png")
_CU_VERIFY_PNG = os.path.join(config.SCREENSHOT_DIR, "_cu_verify.png")
_UI_MAP_PATH   = os.path.join(os.path.dirname(__file__), "ui_positions.json")


# ── Persistent position map ───────────────────────────────────────────────────

def _load_map() -> dict:
    try:
        with open(_UI_MAP_PATH, "r") as f:
            return _json.load(f)
    except Exception:
        return {}


def _save_map(data: dict) -> None:
    with open(_UI_MAP_PATH, "w") as f:
        _json.dump(data, f, indent=2)


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _capture_fullscreen(path: str) -> bool:
    try:
        subprocess.run(["grim", path],
                       check=True, capture_output=True, timeout=8)
        return True
    except Exception:
        return False


def _ydotool(*cmd) -> str:
    try:
        r = subprocess.run(
            ["ydotool"] + list(cmd),
            capture_output=True, text=True, timeout=5
        )
        return "ok" if r.returncode == 0 else (r.stderr.strip() or "unknown error")
    except FileNotFoundError:
        return "Error: ydotool not found — run: sudo ydotoold"
    except subprocess.TimeoutExpired:
        return "Error: ydotool timed out"
    except Exception as e:
        return f"Error: {e}"


def _screen_hash(png_path: str) -> str:
    try:
        with open(png_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return ""


def _verify_action(action_desc: str, pre_hash: str) -> str:
    if not pre_hash:
        return ""
    time.sleep(0.5)
    _capture_fullscreen(_CU_VERIFY_PNG)
    post_hash = _screen_hash(_CU_VERIFY_PNG)
    if not post_hash:
        return ""
    if pre_hash != post_hash:
        return f" [verified: screen changed after {action_desc}]"
    return f" [warning: screen unchanged after {action_desc} — action may have failed]"


def _pre_snapshot() -> str:
    _capture_fullscreen(_CU_VERIFY_PNG)
    return _screen_hash(_CU_VERIFY_PNG)


def _get_window_region(app_class: str = "firefox"):
    """Return (min_x, max_x, min_y, max_y) of the named window via hyprctl."""
    try:
        r = subprocess.run(
            ["hyprctl", "-j", "clients"],
            capture_output=True, text=True, timeout=3
        )
        clients = _json.loads(r.stdout)
        for c in clients:
            if app_class.lower() in c.get("class", "").lower():
                at   = c.get("at",   [0, 0])
                size = c.get("size", [0, 0])
                if size[0] > 50 and size[1] > 50:
                    return at[0], at[0] + size[0], at[1], at[1] + size[1]
    except Exception:
        pass
    return 0, 99999, 0, 99999


# ── MAI-UI action executor ────────────────────────────────────────────────────

def _execute_mai_action(act: dict, pre_hash: str = "") -> str:
    """
    Take a parsed MAI-UI action dict and execute it via ydotool.
    Returns a human-readable result string.
    """
    kind = str(act.get("action", "")).lower()

    if kind == "click":
        cx = int(act.get("x", 0))
        cy = int(act.get("y", 0))
        if cx <= 0 or cy <= 0:
            return f"[MAI-UI] Invalid click coords: {act}"
        out = _ydotool("mousemove", "--absolute", "-x", str(cx), "-y", str(cy))
        if out != "ok":
            return f"Mouse move to ({cx},{cy}) failed: {out}"
        time.sleep(0.25)
        out = _ydotool("click", "0xC0")
        if out != "ok":
            return f"Click failed: {out}"
        time.sleep(0.1)
        verify = _verify_action("mai_ui click", pre_hash)
        return f"MAI-UI clicked at ({cx}, {cy}){verify}"

    elif kind == "type":
        text = str(act.get("text", ""))
        if not text:
            return "[MAI-UI] type action missing 'text'"
        out = _ydotool("type", "--", text)
        if out != "ok":
            return f"MAI-UI type failed: {out}"
        verify = _verify_action("mai_ui type", pre_hash)
        return f"MAI-UI typed: '{text}'{verify}"

    elif kind == "scroll":
        direction = str(act.get("direction", "down")).lower()
        amount    = int(act.get("amount", 3))
        # ydotool scroll: positive = down, negative = up
        delta = amount if direction == "down" else -amount
        out = _ydotool("mousemove", "--absolute", "-x", "960", "-y", "600")
        _ydotool("scroll", "--", "0", str(delta * 3))
        return f"MAI-UI scrolled {direction} by {amount}"

    elif kind == "press":
        key = str(act.get("key", ""))
        if not key:
            return "[MAI-UI] press action missing 'key'"
        out = _ydotool("key", key)
        if out != "ok":
            return f"MAI-UI key press failed: {out}"
        return f"MAI-UI pressed key: {key}"

    elif kind == "ask_user":
        question = str(act.get("question", act.get("text", "MAI-UI needs clarification")))
        return f"[MAI-UI ask_user] {question}"

    elif kind == "done":
        return "MAI-UI: task is already complete (no action needed)"

    elif kind == "error":
        return f"[MAI-UI] {act.get('message', 'unknown error')}"

    else:
        return f"[MAI-UI] Unknown action type: {kind} — raw: {act}"


# ── Public tool dispatcher ────────────────────────────────────────────────────

def run_tool(args: dict = None) -> str:
    if args is None:
        args = {}

    action = str(args.get("action", "")).strip().lower()

    # ── mai_ui_act ────────────────────────────────────────────────────────────
    # The primary new action: describe a task → MAI-UI figures out what to do.
    if action == "mai_ui_act":
        task = str(args.get("task", "")).strip()
        if not task:
            return "Error: 'task' parameter is required"

        from tools import vision as _vision
        pre = _pre_snapshot()
        result_json = _vision.run_tool({"action": "act", "task": task})
        try:
            act = _json.loads(result_json)
        except Exception:
            return f"[MAI-UI] Could not parse vision response: {result_json}"

        return _execute_mai_action(act, pre)

    # ── focus_window ──────────────────────────────────────────────────────────
    elif action == "focus_window":
        app = str(args.get("app", "firefox")).strip()
        for selector in (f"class:{app}", app):
            try:
                r = subprocess.run(
                    ["hyprctl", "dispatch", "focuswindow", selector],
                    capture_output=True, text=True, timeout=3
                )
                if r.returncode == 0:
                    time.sleep(0.3)
                    return f"Focused: {app}"
            except Exception:
                pass
        return f"Could not focus window: {app}"

    # ── open_url ──────────────────────────────────────────────────────────────
    elif action == "open_url":
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
            return f"Opened Firefox: {url}  (tab is now active)"
        except FileNotFoundError:
            pass
        try:
            subprocess.Popen(["firefox", "--new-window", url])
            time.sleep(4.0)
            return f"Launched Firefox: {url}"
        except FileNotFoundError:
            pass
        return "Could not open URL: Firefox is not installed or not in PATH"

    # ── type_text ─────────────────────────────────────────────────────────────
    elif action == "type_text":
        text = str(args.get("text", ""))
        if not text:
            return "Error: 'text' parameter is required"
        pre = _pre_snapshot()
        out = _ydotool("type", "--", text)
        if out != "ok":
            return f"Type failed: {out}"
        verify = _verify_action("type_text", pre)
        return f"Text typed{verify}"

    # ── press_key ─────────────────────────────────────────────────────────────
    elif action == "press_key":
        key = str(args.get("key", "")).strip()
        if not key:
            return "Error: 'key' parameter is required"
        pre = _pre_snapshot()
        out = _ydotool("key", key)
        if out != "ok":
            return f"Key press failed: {out}"
        verify = _verify_action("press_key", pre)
        return f"Key pressed: {key}{verify}"

    # ── screenshot ────────────────────────────────────────────────────────────
    elif action == "screenshot":
        from tools import screenshot as ss
        return ss.run_tool({"mode": "fullscreen"})

    # ── click_element ─────────────────────────────────────────────────────────
    elif action == "click_element":
        site    = str(args.get("site", "")).strip().lower()
        element = str(args.get("element", "")).strip().lower()
        if not site or not element:
            return "Error: 'site' and 'element' are required"
        ui_map = _load_map()
        pos = ui_map.get(site, {}).get(element)
        if not pos:
            return (
                f"No saved position for '{site}' → '{element}'. "
                f"Move your mouse there and run: save_position site={site} element={element}"
            )
        cx, cy = int(pos["x"]), int(pos["y"])
        note = pos.get("note", "")
        pre = _pre_snapshot()
        out = _ydotool("mousemove", "--absolute", "-x", str(cx), "-y", str(cy))
        if out != "ok":
            return f"Mouse move to ({cx},{cy}) failed: {out}"
        time.sleep(0.25)
        out = _ydotool("click", "0xC0")
        if out != "ok":
            return f"Click failed: {out}"
        time.sleep(0.1)
        verify = _verify_action("click_element", pre)
        return f"Clicked '{element}' on {site} at ({cx}, {cy}){verify}" + (f"  [{note}]" if note else "")

    # ── save_position ─────────────────────────────────────────────────────────
    elif action == "save_position":
        site    = str(args.get("site", "")).strip().lower()
        element = str(args.get("element", "")).strip().lower()
        note    = str(args.get("note", "")).strip()
        if not site or not element:
            return "Error: 'site' and 'element' are required"
        try:
            r = subprocess.run(
                ["hyprctl", "cursorpos"],
                capture_output=True, text=True, timeout=3
            )
            xy = r.stdout.strip().replace(" ", "")
            x_str, y_str = xy.split(",")
            cx, cy = int(x_str), int(y_str)
        except Exception as e:
            return f"Could not read cursor position: {e}"
        ui_map = _load_map()
        if site not in ui_map:
            ui_map[site] = {}
        ui_map[site][element] = {"x": cx, "y": cy, "note": note or element}
        _save_map(ui_map)
        return f"Saved: {site} → {element} = ({cx}, {cy})"

    # ── list_positions ────────────────────────────────────────────────────────
    elif action == "list_positions":
        site_filter = str(args.get("site", "")).strip().lower()
        ui_map = _load_map()
        lines = []
        for s, elements in ui_map.items():
            if s.startswith("_"):
                continue
            if site_filter and site_filter not in s:
                continue
            for el, pos in elements.items():
                note = pos.get("note", "")
                lines.append(f"  {s}  →  {el}  ({pos['x']}, {pos['y']})" +
                              (f"  # {note}" if note else ""))
        if not lines:
            return "No positions saved yet. Use save_position to add entries."
        return "Saved UI positions:\n" + "\n".join(lines)

    else:
        return (
            f"Unknown action: '{action}'. "
            "Available: mai_ui_act, focus_window, open_url, type_text, press_key, "
            "screenshot, click_element, save_position, list_positions"
        )