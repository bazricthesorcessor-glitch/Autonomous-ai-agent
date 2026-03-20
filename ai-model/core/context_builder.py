# ========================= core/context_builder.py =========================
import os
import threading
from datetime import datetime
import config
from engines import memory_engine
from engines import fact_engine
from core.context_enricher import build_user_context, format_for_prompt

# Cap per day of raw log — avoids context explosion from old verbose days
_MAX_RAW_CHARS_PER_DAY = getattr(config, 'MAX_RAW_TOKENS_PER_DAY', 8000)

# Hard cap on total context length to prevent bloated LLM prompts
_MAX_CONTEXT_CHARS = 12000

# Track the last screen hash that was injected — prevents OCR flood.
_last_injected_screen_hash: str | None = None
_screen_lock = threading.Lock()


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
    except Exception:
        pass
    return folders


def collect_raw_logs(folders):
    """Today (5000 chars) + yesterday (3000) + day before (2000). Recency-weighted."""
    raw_blocks = []
    budgets = [5000, 3000, 2000]
    for i, folder in enumerate(folders[:3]):
        budget   = budgets[i] if i < len(budgets) else 1500
        raw_path = os.path.join(config.DAILY_DIR, folder, "raw.log")
        content  = read_file(raw_path)
        if not content:
            continue
        lines = [
            l for l in content.split('\n')
            if '[SCHEDULED GOAL' not in l and 'No module named' not in l
        ]
        content = '\n'.join(lines).strip()
        if not content:
            continue
        if len(content) > budget:
            content = "...[truncated]...\n" + content[-budget:]
        raw_blocks.append(f"[{folder}]\n{content}")
    return "\n".join(raw_blocks)


def collect_summaries(folders):
    summary_blocks = []
    # Start after the 2 raw-log days, cover days 3-10
    for folder in folders[2:10]:
        summary_path = os.path.join(config.DAILY_DIR, folder, "summary.txt")
        content = read_file(summary_path)
        if content:
            summary_blocks.append(f"[{folder}] {content[:500]}")
            continue
        # Fallback: if no summary yet, read tail of raw.log
        raw_path = os.path.join(config.DAILY_DIR, folder, "raw.log")
        raw_content = read_file(raw_path)
        if raw_content:
            tail = raw_content[-1500:] if len(raw_content) > 1500 else raw_content
            summary_blocks.append(f"[{folder}] (raw) {tail}")
    return "\n".join(summary_blocks)


def collect_identity():
    """Return identity as readable text, not a raw dict."""
    data = config.safe_load_json(config.IDENTITY_FILE, {})
    if not data:
        return ""
    parts = []
    if data.get("ai_name"):
        parts.append(f"You are {data['ai_name']}.")
    if data.get("creator"):
        parts.append(f"You were created by {data['creator']}.")
    if data.get("user"):
        parts.append(f"Your user's name is {data['user']}.")
    if data.get("system"):
        parts.append(f"System: {data['system']}.")
    if data.get("purpose"):
        parts.append(f"Purpose: {data['purpose']}.")
    return " ".join(parts)


def collect_tasks():
    data = config.safe_load_json(config.TASKS_FILE, {"active": [], "completed": []})
    active = data.get("active", [])
    if not active:
        return ""
    lines = []
    for t in active:
        steps_done = sum(1 for s in t.get("steps", []) if s.get("status") == "done")
        total = len(t.get("steps", []))
        lines.append(f"- [{t['id']}] {t['title']} ({steps_done}/{total} steps)")
    return "Active tasks:\n" + "\n".join(lines)


def collect_facts():
    try:
        active = fact_engine.get_active_facts()
        if not active:
            return ""
        lines = [f"- {k}: {v}" for k, v in active.items()]
        return "Known facts about user:\n" + "\n".join(lines)
    except Exception:
        return ""


def collect_goals():
    """Return goals as readable text, not a raw dict."""
    data = config.safe_load_json(config.GOALS_FILE, {})
    goals = data.get("goals", [])
    if not goals:
        return ""
    return "Goals: " + "; ".join(goals)


def collect_system_state():
    """Return system state as readable text."""
    data = config.safe_load_json(config.SYSTEM_STATE_FILE, {})
    if not data:
        return ""
    parts = []
    for k, v in data.items():
        if v is not None:
            parts.append(f"{k}: {v}")
    return ", ".join(parts) if parts else ""


def collect_vector_memory(user_input):
    results = memory_engine.search_memory(user_input, top_k=3)
    if not results:
        return ""
    return "Relevant memories:\n" + "\n".join(f"- {r}" for r in results)


def collect_remember():
    """Inject pending reminders and shopping lists into context."""
    try:
        from tools import remember as rem_tool
        result = rem_tool.run_tool({"action": "list"})
        if result and "Koi reminder" not in result:
            return f"[Pending reminders/lists]\n{result}"
    except Exception:
        pass
    return ""


def collect_screen_cache():
    """Return the most recent screen OCR snapshot only when the content has changed."""
    global _last_injected_screen_hash

    path = getattr(config, 'SCREEN_CACHE_FILE', None)
    if not path or not os.path.exists(path):
        return ""
    try:
        data = config.safe_load_json(path, {})
        text       = data.get("last_screen_text", "")
        ts         = data.get("timestamp", "")
        new_hash   = data.get("screen_hash", "")

        if not text or not ts:
            return ""

        with _screen_lock:
            if new_hash and new_hash == _last_injected_screen_hash:
                return ""
            _last_injected_screen_hash = new_hash

        return f"Screen [{ts}]: {text[:800]}"
    except Exception:
        pass
    return ""


def build_context(user_input):
    """Build a concise memory context string for the LLM.

    The output is meant to be injected as a system-level reference — not
    as a user message that gets echoed back.  Keep it compact."""
    folders = get_daily_folders_sorted()

    parts = []

    # Rich time/schedule context from enricher
    user_ctx = build_user_context()
    parts.append(format_for_prompt(user_ctx))

    # Identity
    identity = collect_identity()
    if identity:
        parts.append(identity)

    # Known facts
    facts = collect_facts()
    if facts:
        parts.append(facts)

    # Pending reminders / shopping lists / errands
    remember_items = collect_remember()
    if remember_items:
        parts.append(remember_items)

    # Active tasks
    tasks = collect_tasks()
    if tasks:
        parts.append(tasks)

    # Recent conversation history (today + yesterday only)
    raw_logs = collect_raw_logs(folders)
    if raw_logs:
        parts.append(f"Recent conversations:\n{raw_logs}")

    # Summaries from older days
    summaries = collect_summaries(folders)
    if summaries:
        parts.append(f"Older summaries:\n{summaries}")

    # Vector memory search
    vector_hits = collect_vector_memory(user_input)
    if vector_hits:
        parts.append(vector_hits)

    # Screen cache
    screen_snap = collect_screen_cache()
    if screen_snap:
        parts.append(screen_snap)

    context = "\n\n".join(parts)

    # Hard cap — keep only the tail (most recent/relevant info)
    if len(context) > _MAX_CONTEXT_CHARS:
        # Keep the first section (identity + time + facts) and truncate logs
        header_end = context.find("Recent conversations:")
        if header_end > 0:
            header = context[:header_end]
            remaining_budget = _MAX_CONTEXT_CHARS - len(header)
            tail = context[header_end:]
            if len(tail) > remaining_budget:
                tail = "...[truncated]...\n" + tail[-remaining_budget:]
            context = header + tail
        else:
            context = context[:_MAX_CONTEXT_CHARS]

    return context.strip()
