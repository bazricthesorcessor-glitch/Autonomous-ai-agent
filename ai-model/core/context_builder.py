# ========================= core/context_builder.py =========================
import os
from datetime import datetime
import config
from engines import memory_engine

def read_file(path):
    if not os.path.exists(path):
        return ""
    with open(path, "r") as f:
        return f.read()

def get_daily_folders_sorted():
    if not os.path.exists(config.DAILY_DIR):
        return []
    folders = [
        f for f in os.listdir(config.DAILY_DIR)
        if os.path.isdir(os.path.join(config.DAILY_DIR, f))
    ]
    try:
        folders = sorted(folders, reverse=True)  # Newest first
    except:
        pass
    return folders

def collect_raw_logs(folders):
    raw_blocks = []
    for folder in folders[:config.RAW_DAYS_WINDOW]:
        raw_path = os.path.join(config.DAILY_DIR, folder, "raw.log")
        content = read_file(raw_path)
        if content:
            raw_blocks.append(f"\n--- RAW {folder} ---\n{content}")
    return "\n".join(raw_blocks)

def collect_summaries(folders):
    summary_blocks = []
    start = config.RAW_DAYS_WINDOW
    end = config.RAW_DAYS_WINDOW + config.SUMMARY_DAYS_WINDOW

    for folder in folders[start:end]:
        summary_path = os.path.join(config.DAILY_DIR, folder, "summary.txt")
        content = read_file(summary_path)
        if content:
            summary_blocks.append(f"\n--- SUMMARY {folder} ---\n{content}")

    return "\n".join(summary_blocks)

def collect_identity():
    return str(config.safe_load_json(config.IDENTITY_FILE, {}))

def collect_tasks():
    return str(config.safe_load_json(config.TASKS_FILE, {}))

def collect_goals():
    return str(config.safe_load_json(config.GOALS_FILE, {}))

def collect_system_state():
    return str(config.safe_load_json(config.SYSTEM_STATE_FILE, {}))

def collect_vector_memory(user_input):
    results = memory_engine.search_memory(user_input, top_k=3)
    if not results:
        return ""
    return "\n--- VECTOR MEMORY ---\n" + "\n".join(results)

def build_context(user_input):
    folders = get_daily_folders_sorted()

    # 1. Load Data into Variables
    identity = collect_identity()
    system_state = collect_system_state()
    goals = collect_goals()
    tasks = collect_tasks()

    # 2. Collect Logs
    raw_logs = collect_raw_logs(folders)
    summaries = collect_summaries(folders)
    vector_hits = collect_vector_memory(user_input)

    # 3. Assemble Context (NO CURRENT INPUT)
    context = f"""
=== IDENTITY ===
{identity}

=== SYSTEM STATE ===
{system_state}

=== GOALS ===
{goals}

=== TASKS ===
{tasks}

=== RECENT RAW LOGS (Last {config.RAW_DAYS_WINDOW} Days) ===
{raw_logs}

=== MID-TERM SUMMARIES (Days {config.RAW_DAYS_WINDOW+1}-{config.RAW_DAYS_WINDOW+config.SUMMARY_DAYS_WINDOW}) ===
{summaries}

{vector_hits}
"""

    return context.strip()
