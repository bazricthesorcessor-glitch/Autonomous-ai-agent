# ========================= engines/janitor.py =========================
import os
import time
import config
from engines import summarizer

def run_maintenance():
    print("Running Maintenance Cycle...")

    # 1. Trigger Summarization for old logs
    summarizer.run_summarization()

    # 2. Check for oversized raw logs (Safety)
    # (This prevents a single day from exploding the context)
    check_raw_log_limits()

    # 3. Clear stale screenshots to keep perception storage bounded
    cleanup_old_screenshots()

    print("Maintenance Complete.")

def check_raw_log_limits():
    if not os.path.exists(config.DAILY_DIR):
        return

    # Simple check: if today's raw log is too big, warn or truncate.
    # For now, we will just warn.
    today_raw = config.get_raw_log_path()
    if os.path.exists(today_raw):
        size = os.path.getsize(today_raw)
        # Approx 4 chars per token. 8000 tokens ~ 32KB text.
        if size > 100000: # 100KB warning threshold
            print(f"Warning: Today's log is large ({size} bytes). Consider starting a new session.")


def cleanup_old_screenshots():
    keep = {
        "screenshot.png",
        "ocr.txt",
        "screen_map.json",
        "_ui_parse.png",
        "_browser.png",
        "_cu_screen.png",
        "_cu_verify.png",
    }
    cutoff = time.time() - config.SCREENSHOT_RETENTION_SECONDS
    if not os.path.isdir(config.SCREENSHOT_DIR):
        return

    for name in os.listdir(config.SCREENSHOT_DIR):
        path = os.path.join(config.SCREENSHOT_DIR, name)
        if not os.path.isfile(path):
            continue
        if name in keep:
            continue
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            continue
