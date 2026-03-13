# ========================= engines/janitor.py =========================
import os
import config
from engines import summarizer

def run_maintenance():
    print("Running Maintenance Cycle...")

    # 1. Trigger Summarization for old logs
    summarizer.run_summarization()

    # 2. Check for oversized raw logs (Safety)
    # (This prevents a single day from exploding the context)
    check_raw_log_limits()

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
