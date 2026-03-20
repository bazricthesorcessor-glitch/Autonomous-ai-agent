# ========================= engines/janitor.py =========================
import json
import os
import re
import time
from datetime import date, timedelta

import config
from engines import summarizer


# ── Internal helper ───────────────────────────────────────────────────────────

def _atomic_save(data: dict, path: str):
    """Atomic JSON save via tmp → replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# ── Maintenance orchestrator ──────────────────────────────────────────────────

def run_maintenance():
    print("Running Maintenance Cycle...")

    # 1. Trigger summarisation for old logs
    summarizer.run_summarization()

    # 2. Check for oversized raw logs (safety)
    check_raw_log_limits()

    # 3. Clear stale screenshots to keep perception storage bounded
    cleanup_old_screenshots()

    # 4. Clean up done reminders, errands, shopping items
    cleanup_remember()

    # 5. Remove daily_log entries older than 14 days
    cleanup_daily_log()

    # 6. Scan logs and update behavioural patterns
    update_behavioral_patterns()

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


def cleanup_remember():
    """Remove done errands + done non-recurring reminders + done shopping items."""
    try:
        from tools import remember as rem_tool
        result = rem_tool.run_tool({"action": "clear_done"})
        print(f"[Janitor] {result}")
    except Exception as e:
        print(f"[Janitor] cleanup_remember failed: {e}")


def cleanup_old_screenshots():
    keep = {
        "screenshot.png",
        "ocr.txt",
        "screen_map.json",
        "_ui_parse.png",
        "_browser.png",
        "_cu_screen.png",
        "_cu_verify.png",
        "_vision_locate.png",
        "_vision_grid.png",
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


# ── Step 5: daily_log cleanup ─────────────────────────────────────────────────

def cleanup_daily_log(keep_days: int = 14):
    """
    Delete daily_log.json date-keys older than keep_days days.
    Recent entries are preserved so context_enricher can read pending homework.
    """
    path = config.DAILY_LOG_FILE
    data = config.safe_load_json(path, {})

    cutoff   = (date.today() - timedelta(days=keep_days)).isoformat()
    old_keys = [k for k in list(data.keys()) if len(k) == 10 and k < cutoff]

    if not old_keys:
        print("[Janitor] daily_log: nothing to clean.")
        return

    for k in old_keys:
        del data[k]

    _atomic_save(data, path)
    print(f"[Janitor] daily_log: removed {len(old_keys)} entries older than {keep_days} days.")


# ── Step 6: behavioural patterns update ──────────────────────────────────────

def _read_raw_logs(since_date: str, max_days: int = 7) -> list:
    """
    Read raw.log files from DAILY_DIR.
    Returns list of (date_str, day_of_week, text) for days between since_date and yesterday.
    """
    today   = date.today()
    results = []
    for i in range(1, max_days + 1):
        d_date = today - timedelta(days=i)
        d_str  = d_date.isoformat()
        if d_str <= since_date:
            break
        path = os.path.join(config.DAILY_DIR, d_str, "raw.log")
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                text = f.read()
            results.append((d_str, d_date.strftime("%A"), text))
        except Exception:
            continue
    return results


def update_behavioral_patterns():
    """
    Scan recent raw logs + daily_log.json and update behavioral_patterns.json.

    Patterns updated:
      five_more_minutes    — count trigger phrase occurrences in logs
      homework_denial      — "kar liya" claims vs actual daily_log done status
      dsd_avoidance        — DSD items left pending vs other subjects
      late_night_thursday  — log activity after 22:00 on Thursdays
    """
    bp_path   = config.BEHAVIORAL_FILE
    bp        = config.safe_load_json(bp_path, {})
    patterns  = {p["id"]: p for p in bp.get("patterns", [])}
    last_scan = bp.get("last_scan_date", "2000-01-01")
    today_str = date.today().isoformat()

    if last_scan >= today_str:
        print("[Janitor] behavioral_patterns: already scanned today.")
        return

    logs      = _read_raw_logs(since_date=last_scan, max_days=7)
    daily_log = config.safe_load_json(config.DAILY_LOG_FILE, {})

    if not logs:
        print("[Janitor] behavioral_patterns: no new logs to scan.")
        bp["last_scan_date"] = today_str
        _atomic_save(bp, bp_path)
        return

    # ── 1. five_more_minutes ──────────────────────────────────────────────────
    fmm         = patterns.get("five_more_minutes", {})
    fmm_triggers = [
        "bas 5 minute", "5 more minutes", "just 5 min",
        "thodi der", "thoda wait", "bas thodi der",
    ]
    new_hits = 0
    for _d, _dow, text in logs:
        t = text.lower()
        for trigger in fmm_triggers:
            new_hits += len(re.findall(re.escape(trigger), t))
    if new_hits:
        fmm["observed_count"] = fmm.get("observed_count", 0) + new_hits
        fmm["last_observed"]  = logs[0][0]
    patterns["five_more_minutes"] = fmm

    # ── 2. homework_denial ────────────────────────────────────────────────────
    # Heuristic: when user says "kar liya / ho gaya" on a day that had homework,
    # check if all items were actually done → true, else → false (bluffed).
    hd      = patterns.get("homework_denial", {})
    denials = [
        "kar liya", "already did", "ho gaya",
        "done ho gaya", "sab kar li", "kar di", "khatam",
    ]
    for d_str, _dow, text in logs:
        day_entry = daily_log.get(d_str, {})
        hw        = day_entry.get("homework", [])
        if not hw:
            continue
        if not any(trigger in text.lower() for trigger in denials):
            continue
        pending = [h for h in hw if not h.get("done")]
        hd["observed_count"] = hd.get("observed_count", 0) + 1
        hd["last_observed"]  = d_str
        if not pending:
            hd["true_count"] = hd.get("true_count", 0) + 1
        else:
            hd["false_count"] = hd.get("false_count", 0) + 1
            bp.setdefault("claim_history", []).append({
                "date":          d_str,
                "pending_items": [f"{h['subject']}: {h['task']}" for h in pending],
            })
            bp["claim_history"] = bp["claim_history"][-20:]
        tc    = hd.get("true_count",  0)
        fc    = hd.get("false_count", 0)
        total = tc + fc
        if total:
            hd["accuracy_pct"] = round((tc / total) * 100)
    patterns["homework_denial"] = hd

    # ── 3. dsd_avoidance ──────────────────────────────────────────────────────
    # Which subjects are consistently left pending by end of day?
    da          = patterns.get("dsd_avoidance", {})
    dsd_pending = 0
    all_pending = 0
    for d_str, _dow, _text in logs:
        for item in daily_log.get(d_str, {}).get("homework", []):
            if not item.get("done"):
                all_pending += 1
                if "DSD" in item.get("subject", "").upper():
                    dsd_pending += 1
    if dsd_pending:
        da["observed_count"] = da.get("observed_count", 0) + dsd_pending
        da["last_observed"]  = today_str
        da.setdefault("avoidance_events", []).append({
            "date":          today_str,
            "dsd_pending":   dsd_pending,
            "total_pending": all_pending,
            "dsd_rate_pct":  round((dsd_pending / max(all_pending, 1)) * 100),
        })
        da["avoidance_events"] = da["avoidance_events"][-10:]
    patterns["dsd_avoidance"] = da

    # ── 4. late_night_thursday ────────────────────────────────────────────────
    # Check for raw log activity on Thursdays timestamped ≥ 22:00.
    ln = patterns.get("late_night_thursday", {})
    for d_str, dow, text in logs:
        if dow != "Thursday":
            continue
        if re.search(r'\[' + re.escape(d_str) + r' (2[2-9]|23):\d{2}', text):
            ln["observed_count"] = ln.get("observed_count", 0) + 1
            ln["last_observed"]  = d_str
    patterns["late_night_thursday"] = ln

    # ── Save ──────────────────────────────────────────────────────────────────
    bp["patterns"]       = list(patterns.values())
    bp["last_scan_date"] = today_str
    _atomic_save(bp, bp_path)
    print(
        f"[Janitor] behavioral_patterns: scanned {len(logs)} day(s), "
        f"updated {len(patterns)} patterns."
    )
