import subprocess
import os
import re
import json
import hashlib
from datetime import datetime
import config


# ── Stable paths inside ai-model/screenshot/ ──────────────────────────────────
# screenshot_new.png  — captured here first; old screenshot.png still exists
#                       while OCR runs (zero gap guarantee).
# screenshot.png      — live screenshot; replaced atomically after OCR is done.
# ocr.txt             — latest clean OCR text; replaced atomically.
_SS_NEW  = os.path.join(config.SCREENSHOT_DIR, "screenshot_new.png")
_SS_LIVE = os.path.join(config.SCREENSHOT_DIR, "screenshot.png")
_OCR_TXT = os.path.join(config.SCREENSHOT_DIR, "ocr.txt")


def _get_active_window_geometry():
    """
    Get active window position+size via hyprctl.
    Returns a grim-compatible geometry string like '100,200 800x600', or None on failure.
    """
    try:
        result = subprocess.run(
            ["hyprctl", "-j", "activewindow"],
            capture_output=True, text=True, timeout=2
        )
        data = json.loads(result.stdout)
        at = data.get("at", [0, 0])
        size = data.get("size", [0, 0])
        if size[0] > 100 and size[1] > 100:
            return f"{at[0]},{at[1]} {size[0]}x{size[1]}"
    except Exception:
        pass
    return None


def _is_noise_line(line):
    """
    Return True if a line is almost certainly UI chrome noise and not task content.
    Catches: clock (14:30), very short fragments, symbol-heavy garbled OCR.
    """
    s = line.strip()
    if not s:
        return True
    # Clock patterns: 14:30, 2:30 PM, 22:15:00
    if re.fullmatch(r'\d{1,2}:\d{2}(:\d{2})?(\s*(AM|PM))?', s, re.IGNORECASE):
        return True
    # Date fragments like "Mon 10 Mar" or "March 10" - taskbar date chips
    if re.fullmatch(r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}(\s+\w+)?', s, re.IGNORECASE):
        return True
    # Too short to be meaningful
    if len(s) < 4:
        return True
    # Mostly non-letter characters (icons, separators, garbled symbols)
    letter_ratio = sum(1 for c in s if c.isalpha()) / len(s)
    if len(s) > 6 and letter_ratio < 0.25:
        return True
    return False


def run_tool(args):
    """
    Screenshot + OCR tool.

    Args (dict):
      mode: "active_window" (default) — captures only the focused window.
            "fullscreen"              — captures entire screen.

    Files written to ai-model/screenshot/:
      screenshot_new.png → screenshot.png  (atomic replace after OCR)
      ocr.txt                               (atomic replace with new text)

    Old screenshot.png remains readable while OCR is running.
    """
    mode = "active_window"
    if isinstance(args, dict):
        mode = args.get("mode", "active_window")

    # --- 1. Capture to screenshot_new.png ---
    # Old screenshot.png is NOT touched yet — it stays valid during OCR.
    capture_cmd = ["grim"]
    label = "FULLSCREEN"

    if mode == "active_window":
        geometry = _get_active_window_geometry()
        if geometry:
            capture_cmd += ["-g", geometry]
            label = "ACTIVE_WINDOW"
        else:
            label = "FULLSCREEN (fallback)"

    capture_cmd.append(_SS_NEW)

    try:
        with open(os.devnull, 'w') as devnull:
            subprocess.run(capture_cmd, check=True, stdout=devnull, stderr=devnull)
    except FileNotFoundError:
        return "Error: 'grim' not found. Requires a Wayland session with grim installed."
    except subprocess.CalledProcessError:
        return "Error: Screen capture failed."

    # --- 2. OCR (screenshot_new.png; old screenshot.png still alive) ---
    try:
        result = subprocess.run(
            ["tesseract", _SS_NEW, "stdout", "--psm", "6"],
            capture_output=True, text=True, check=True
        )
        extracted_text = result.stdout.strip()
    except FileNotFoundError:
        _try_remove(_SS_NEW)
        return "Error: 'tesseract' not found. Run: sudo pacman -S tesseract tesseract-data-eng"
    except subprocess.CalledProcessError:
        _try_remove(_SS_NEW)
        return "Error: OCR processing failed."

    # --- 3. Filter noise ---
    lines = [line.strip() for line in extracted_text.split('\n')]
    clean_lines = [line for line in lines if not _is_noise_line(line)]

    if not clean_lines:
        _try_remove(_SS_NEW)
        return f"[SCREEN - {label}] Captured but no readable content found."

    clean_text = "\n".join(clean_lines)

    # --- 4. Hash check — skip cache update if text unchanged ---
    new_hash = hashlib.sha256(clean_text.encode()).hexdigest()
    old_cache = config.safe_load_json(config.SCREEN_CACHE_FILE, {})
    old_hash  = old_cache.get("screen_hash", "")

    text_changed = (new_hash != old_hash)

    # --- 5. Atomic replace: screenshot.png ← screenshot_new.png ---
    # os.replace is atomic on POSIX — the old file is never "gone" from FS.
    os.replace(_SS_NEW, _SS_LIVE)

    # --- 6. Write ocr.txt (atomic via temp+replace) ---
    ocr_tmp = _OCR_TXT + ".tmp"
    try:
        with open(ocr_tmp, "w", encoding="utf-8") as f:
            f.write(clean_text)
        os.replace(ocr_tmp, _OCR_TXT)
    except Exception:
        pass

    # --- 7. Update perception cache ---
    try:
        cache = {
            "last_screen_text": clean_text[:3000],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": label,
            "screen_hash": new_hash,
            "changed": text_changed,   # context_builder reads this flag
        }
        os.makedirs(os.path.dirname(config.SCREEN_CACHE_FILE), exist_ok=True)
        with open(config.SCREEN_CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass  # Cache write failure should never block OCR result

    unchanged_note = "" if text_changed else " [UNCHANGED]"
    return f"[SCREEN - {label}{unchanged_note}]\n{clean_text[:2000]}"


def _try_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
