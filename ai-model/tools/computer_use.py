# ========================= tools/computer_use.py =========================
"""
Computer use — high-level screen interaction for browser/app automation.

Actions:
  click_element   Look up a pre-saved pixel position and click it (most reliable)
                  {"action": "click_element", "site": "youtube.com", "element": "search_bar"}

  save_position   Read current cursor pos (hyprctl cursorpos) and save to map
                  {"action": "save_position", "site": "youtube.com", "element": "search_bar"}

  list_positions  Show all saved positions
                  {"action": "list_positions"}
                  {"action": "list_positions", "site": "youtube.com"}

  focus_window    Bring app to foreground (do this before find_on_screen!)
                  {"action": "focus_window", "app": "firefox"}

  find_on_screen  Capture fullscreen, OCR with bounding boxes, return x,y of text
                  {"action": "find_on_screen", "text": "Search"}

  click_text      Find text on screen and click it (OCR-based, fallback when no saved pos)
                  {"action": "click_text", "text": "Search"}

  open_url        Open a URL in Firefox (launches new window or new tab)
                  {"action": "open_url", "url": "https://youtube.com"}

  type_text       Type text at current cursor position
                  {"action": "type_text", "text": "coconut oil"}

  press_key       Press a key or shortcut
                  {"action": "press_key", "key": "Return"}
                  {"action": "press_key", "key": "ctrl+l"}

  screenshot      Fullscreen capture + OCR (to verify what's on screen)
                  {"action": "screenshot"}

Typical workflow for "search YouTube for coconut oil":
  1. open_url       url=https://youtube.com
  2. focus_window   app=firefox
  3. press_key      key=slash   ← YouTube shortcut: '/' focuses search bar
  4. type_text      text=coconut oil
  5. press_key      key=Return

Alternative using mouse (if keyboard shortcut not available):
  3. click_text     text=Search   ← OCR finds search bar, moves mouse, clicks

Notes:
  - Requires ydotoold running: sudo ydotoold
  - Requires grim (Wayland screen capture) and tesseract (OCR)
  - find_on_screen uses tesseract TSV output for per-word bounding boxes
"""

import os
import json as _json
import time
import subprocess
import hashlib

import config

# Dedicated temp screenshot for computer_use (won't replace the main screenshot.png)
_CU_PNG = os.path.join(config.SCREENSHOT_DIR, "_cu_screen.png")
_CU_VERIFY_PNG = os.path.join(config.SCREENSHOT_DIR, "_cu_verify.png")

# Persistent map of named pixel positions per site/app
_UI_MAP_PATH = os.path.join(os.path.dirname(__file__), "ui_positions.json")


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
    """Use grim to capture the full screen. Returns True on success."""
    try:
        subprocess.run(
            ["grim", path],
            check=True, capture_output=True, timeout=8
        )
        return True
    except Exception:
        return False


def _tesseract_tsv(png_path: str) -> str:
    """Run tesseract with TSV (bounding box) output. Returns raw TSV or ''."""
    try:
        result = subprocess.run(
            ["tesseract", png_path, "stdout", "--psm", "3", "tsv"],
            capture_output=True, text=True, check=True, timeout=30
        )
        return result.stdout
    except Exception:
        return ""


def _find_coords(query: str, min_x=0, max_x=99999, min_y=0, max_y=99999) -> tuple | None:
    """
    Capture fullscreen, OCR with TSV bounding boxes, find `query`.
    Optional region: min_x/max_x/min_y/max_y restrict which part of the screen to search.
    Returns (cx, cy, matched_word, confidence) or None.
    TSV columns (0-indexed): level page_num block_num par_num line_num word_num
                              left top width height conf text
    """
    if not _capture_fullscreen(_CU_PNG):
        return None

    tsv = _tesseract_tsv(_CU_PNG)
    if not tsv:
        return None

    q = query.strip().lower()
    best       = None
    best_score = -1

    for line in tsv.strip().split('\n')[1:]:   # skip header row
        parts = line.split('\t')
        if len(parts) < 12:
            continue
        try:
            conf = float(parts[10])
            word = parts[11].strip().lower()
        except (ValueError, IndexError):
            continue

        if conf < 20 or not word:
            continue

        # Only exact or contiguous-substring matches — no fuzzy letter-set tricks.
        # This prevents words like "chainsmokers" (which share letters with "search")
        # from matching the wrong element.
        if q == word:
            score = 100
        elif len(q) >= 3 and len(word) >= 3 and (q in word or word in q):
            # Penalise large length difference so "searchbar" ranks below "search"
            score = 80 - abs(len(q) - len(word))
        else:
            continue

        if score > best_score:
            try:
                cx = int(parts[6]) + int(parts[8]) // 2   # left + width/2
                cy = int(parts[7]) + int(parts[9]) // 2   # top  + height/2
                # Skip if outside the requested region
                if not (min_x <= cx <= max_x and min_y <= cy <= max_y):
                    continue
                best_score = score
                best = (cx, cy, word, conf)
            except ValueError:
                continue

    return best if best_score > 0 else None


def _get_window_region(app_class: str = "firefox"):
    """
    Ask Hyprland for the bounding box of the first matching window.
    Returns (min_x, max_x, min_y, max_y) or (0, 99999, 0, 99999) on failure.
    """
    try:
        r = subprocess.run(
            ["hyprctl", "-j", "clients"],
            capture_output=True, text=True, timeout=3
        )
        import json as _json
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


def _ydotool(*cmd) -> str:
    """Run a ydotool command. Returns 'ok' or an error string."""
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


# ── Action Verifier ──────────────────────────────────────────────────────────
# After mutating actions (click, type, press_key), capture a verification
# screenshot and compare its hash to the pre-action screenshot.  If the screen
# didn't change, the action probably failed silently.

def _screen_hash(png_path: str) -> str:
    """Return a fast hash of the screenshot file (or '' on failure)."""
    try:
        with open(png_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return ""


def _verify_action(action_desc: str, pre_hash: str) -> str:
    """Take a post-action screenshot, compare hash, return a verification note.

    Returns a short string like ' [verified: screen changed]' or
    ' [warning: screen unchanged — action may have failed]'.
    """
    if not pre_hash:
        return ""
    time.sleep(0.5)  # give the GUI a moment to react
    _capture_fullscreen(_CU_VERIFY_PNG)
    post_hash = _screen_hash(_CU_VERIFY_PNG)
    if not post_hash:
        return ""
    if pre_hash != post_hash:
        return f" [verified: screen changed after {action_desc}]"
    return f" [warning: screen unchanged after {action_desc} — action may have failed]"


def _pre_snapshot() -> str:
    """Capture the screen and return its hash (for before/after comparison)."""
    _capture_fullscreen(_CU_VERIFY_PNG)
    return _screen_hash(_CU_VERIFY_PNG)


# ── Public tool dispatcher ────────────────────────────────────────────────────

def run_tool(args: dict = None) -> str:
    if args is None:
        args = {}

    action = str(args.get("action", "")).strip().lower()

    # ── find_on_screen ────────────────────────────────────────────────────
    if action == "find_on_screen":
        text    = str(args.get("text", "")).strip()
        if not text:
            return "Error: 'text' parameter is required"
        # Optional manual region override; otherwise use Firefox window bounds
        app_hint = str(args.get("app", "firefox"))
        min_x, max_x, min_y, max_y = _get_window_region(app_hint)
        # Allow manual overrides
        min_x = int(args.get("min_x", min_x))
        max_x = int(args.get("max_x", max_x))
        min_y = int(args.get("min_y", min_y))
        max_y = int(args.get("max_y", max_y))
        # Retry up to 3 times — handles pages still loading
        match = None
        for attempt in range(3):
            match = _find_coords(text, min_x, max_x, min_y, max_y)
            if match:
                break
            if attempt < 2:
                time.sleep(1.5)
        if match:
            cx, cy, word, conf = match
            return f"Found '{word}' at ({cx}, {cy})  [OCR confidence: {conf:.0f}]"
        return (
            f"Not found: '{text}' in {app_hint} window after 3 attempts. "
            "Take a screenshot to confirm the page is loaded."
        )

    # ── click_text ────────────────────────────────────────────────────────
    elif action == "click_text":
        text = str(args.get("text", "")).strip()
        if not text:
            return "Error: 'text' parameter is required"
        # Use Firefox window bounds to restrict OCR region — avoids hitting
        # VS Code / other tiled windows that share the same screen space
        app_hint = str(args.get("app", "firefox"))
        min_x, max_x, min_y, max_y = _get_window_region(app_hint)
        min_x = int(args.get("min_x", min_x))
        max_x = int(args.get("max_x", max_x))
        min_y = int(args.get("min_y", min_y))
        max_y = int(args.get("max_y", max_y))
        # Retry up to 4 times with 1.5s gap — handles pages still loading
        match = None
        for attempt in range(4):
            match = _find_coords(text, min_x, max_x, min_y, max_y)
            if match:
                break
            if attempt < 3:
                time.sleep(1.5)
        if not match:
            return (
                f"Could not find '{text}' in {app_hint} window after 4 attempts. "
                "Take a screenshot to check what's visible, then retry."
            )
        cx, cy, word, conf = match
        pre = _pre_snapshot()
        out = _ydotool("mousemove", "--absolute", "-x", str(cx), "-y", str(cy))
        if out != "ok":
            return f"Mouse move to ({cx},{cy}) failed: {out}"
        time.sleep(0.25)   # let Hyprland register the move before clicking
        out = _ydotool("click", "0xC0")   # 0xC0 = left button DOWN + UP (full click)
        if out != "ok":
            return f"Click failed: {out}"
        time.sleep(0.1)    # brief pause after click — let focus settle
        verify = _verify_action("click_text", pre)
        return f"Moved mouse to '{word}' at ({cx}, {cy}) and clicked{verify}"

    # ── focus_window ──────────────────────────────────────────────────────
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

    # ── open_url ──────────────────────────────────────────────────────────
    elif action == "open_url":
        url = str(args.get("url", "")).strip()
        if not url:
            return "Error: 'url' parameter is required"
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        # Use `firefox URL` — if Firefox is already running this opens the URL
        # in a new focused tab in the existing window (most reliable approach)
        try:
            subprocess.Popen(["firefox", url])
            time.sleep(3.5)   # wait for tab to open and page to start loading
            # Focus Firefox so subsequent screenshot/find_on_screen sees it
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

        # Firefox not open — launch a new window
        try:
            subprocess.Popen(["firefox", "--new-window", url])
            time.sleep(4.0)   # cold-start is slower
            for selector in ("class:firefox", "firefox"):
                try:
                    subprocess.run(
                        ["hyprctl", "dispatch", "focuswindow", selector],
                        capture_output=True, text=True, timeout=3
                    )
                    break
                except Exception:
                    pass
            return f"Launched Firefox: {url}"
        except FileNotFoundError:
            pass
        return f"Could not open URL: Firefox is not installed or not in PATH"

    # ── type_text ─────────────────────────────────────────────────────────
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

    # ── press_key ─────────────────────────────────────────────────────────
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

    # ── screenshot ────────────────────────────────────────────────────────
    elif action == "screenshot":
        from tools import screenshot as ss
        return ss.run_tool({"mode": "fullscreen"})

    # ── click_element ─────────────────────────────────────────────────────
    # Looks up a pre-saved pixel position in ui_positions.json.
    # Much more reliable than OCR — no guessing, goes straight to the right spot.
    # {"action": "click_element", "site": "youtube.com", "element": "search_bar"}
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

    # ── save_position ─────────────────────────────────────────────────────
    # Reads current cursor pos via hyprctl and saves it to ui_positions.json.
    # {"action": "save_position", "site": "youtube.com", "element": "search_bar"}
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
            # output: "X, Y" e.g. "709, 122"
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

    # ── list_positions ────────────────────────────────────────────────────
    # Shows every saved position.
    # {"action": "list_positions"}  or  {"action": "list_positions", "site": "youtube.com"}
    elif action == "list_positions":
        site_filter = str(args.get("site", "")).strip().lower()
        ui_map = _load_map()
        lines = []
        for s, elements in ui_map.items():
            if s.startswith("_"):
                continue                # skip _note, _resolution meta keys
            if site_filter and site_filter not in s:
                continue
            for el, pos in elements.items():
                note = pos.get("note", "")
                lines.append(f"  {s}  →  {el}  ({pos['x']}, {pos['y']})" +
                              (f"  # {note}" if note else ""))
        if not lines:
            return "No positions saved yet. Use save_position to add entries."
        return "Saved UI positions:\n" + "\n".join(lines)

    # ── scan_screen ──────────────────────────────────────────────────────
    # Build the structured element map: every visible UI element with bounding box.
    # {"action": "scan_screen"}  or  {"action": "scan_screen", "app": "firefox"}
    elif action == "scan_screen":
        from tools import screen_map
        app_hint = str(args.get("app", "firefox"))
        min_x, max_x, min_y, max_y = _get_window_region(app_hint)
        elements = screen_map.scan(min_x, max_x, min_y, max_y)
        return screen_map.format_map(elements)

    # ── click_map ────────────────────────────────────────────────────────
    # Find an element in the last scan_screen result and click its center.
    # ALWAYS run scan_screen first, then click_map.
    # {"action": "click_map", "text": "Search"}
    elif action == "click_map":
        text = str(args.get("text", "")).strip()
        if not text:
            return "Error: 'text' parameter is required"
        from tools import screen_map
        el = screen_map.find_element(text)
        if not el:
            return (
                f"Element '{text}' not found in screen map. "
                "Run scan_screen first to refresh the map."
            )
        cx, cy = el["cx"], el["cy"]
        pre = _pre_snapshot()
        out = _ydotool("mousemove", "--absolute", "-x", str(cx), "-y", str(cy))
        if out != "ok":
            return f"Mouse move to ({cx},{cy}) failed: {out}"
        time.sleep(0.25)
        out = _ydotool("click", "0xC0")
        if out != "ok":
            return f"Click failed: {out}"
        time.sleep(0.1)
        verify = _verify_action("click_map", pre)
        return (
            f"Clicked \"{el['text']}\" [{el.get('type','?')}] "
            f"at ({cx}, {cy})  size {el['w']}×{el['h']}{verify}"
        )

    else:
        return (
            f"Unknown action: '{action}'. "
            "Available: scan_screen, click_map, click_element, save_position, "
            "list_positions, find_on_screen, click_text, open_url, focus_window, "
            "type_text, press_key, screenshot"
        )
