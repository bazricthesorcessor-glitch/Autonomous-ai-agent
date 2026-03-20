# ========================= tools/daily_log.py =========================
"""
Daily log tool — Avril's structured homework and checkin tracker.

Writes to memory/daily_log.json. Keyed by date (YYYY-MM-DD).
context_enricher.py reads this to know pending homework count and
whether today's post-college checkin has been done.

Actions:
  add_homework    — store a homework item for today
                    {"action": "add_homework", "subject": "MATHS",
                     "task": "integration assignment", "deadline": "2026-03-17"}

  mark_done       — mark a homework item done by id
                    {"action": "mark_done", "id": "hw_abc123"}

  mark_all_done   — mark every pending item done (use when Divyansh says "sab ho gaya")
                    {"action": "mark_all_done"}

  add_weak_area   — store something Divyansh didn't understand today
                    {"action": "add_weak_area", "subject": "DSD", "topic": "flip-flops"}

  set_checkin_done — mark that today's post-college checkin is complete
                     {"action": "set_checkin_done"}

  set_mood        — store today's detected mood/energy
                    {"action": "set_mood", "mood": "tired"}

  get_today       — return today's full log as readable text
                    {"action": "get_today"}

  get_pending     — return only pending homework items
                    {"action": "get_pending"}

  list_weak_areas — return weak areas noted this week
                    {"action": "list_weak_areas", "days": 7}
"""

import json
import os
import uuid
from datetime import datetime, date, timedelta

import config

DAILY_LOG_PATH = os.path.join(config.MEMORY_DIR, "daily_log.json")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load() -> dict:
    """Load the full daily log. Returns {} if missing or corrupt."""
    return config.safe_load_json(DAILY_LOG_PATH, {})


def _save(data: dict):
    """Atomic save to daily_log.json."""
    os.makedirs(os.path.dirname(DAILY_LOG_PATH), exist_ok=True)
    tmp = DAILY_LOG_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, DAILY_LOG_PATH)
    except Exception as e:
        print(f"[DailyLog] Save failed: {e}")


def _today_str() -> str:
    return date.today().isoformat()


def _get_or_create_today(data: dict) -> dict:
    """Return today's log entry, creating it if it doesn't exist."""
    today = _today_str()
    if today not in data:
        data[today] = {
            "date":         today,
            "homework":     [],
            "weak_areas":   [],
            "mood":         None,
            "checkin_done": False,
            "notes":        [],
            "created_at":   datetime.now().isoformat(),
        }
    return data[today]


# ── Action handlers ───────────────────────────────────────────────────────────

def _add_homework(args: dict) -> str:
    subject  = args.get("subject", "").strip().upper()
    task     = args.get("task", "").strip()
    deadline = args.get("deadline", "").strip()

    if not subject or not task:
        return "[DailyLog] 'subject' aur 'task' dono chahiye."

    data     = _load()
    today    = _get_or_create_today(data)
    hw_id    = "hw_" + uuid.uuid4().hex[:6]

    item = {
        "id":       hw_id,
        "subject":  subject,
        "task":     task,
        "deadline": deadline,
        "done":     False,
        "added_at": datetime.now().isoformat(),
    }
    today["homework"].append(item)
    _save(data)

    deadline_str = f" (deadline: {deadline})" if deadline else ""
    return f"Homework note kar li — {subject}: {task}{deadline_str}. [{hw_id}]"


def _mark_done(args: dict) -> str:
    hw_id = args.get("id", "").strip()
    if not hw_id:
        return "[DailyLog] 'id' chahiye. Pehle get_pending se IDs dekho."

    data  = _load()
    today = _get_or_create_today(data)

    for item in today["homework"]:
        if item["id"] == hw_id:
            item["done"]    = True
            item["done_at"] = datetime.now().isoformat()
            _save(data)
            return f"{item['subject']}: {item['task']} — done mark kar diya."

    return f"[DailyLog] ID '{hw_id}' nahi mila aaj ke homework mein."


def _mark_all_done(args: dict) -> str:
    data   = _load()
    today  = _get_or_create_today(data)
    now    = datetime.now().isoformat()
    count  = 0

    for item in today["homework"]:
        if not item.get("done"):
            item["done"]    = True
            item["done_at"] = now
            count += 1

    _save(data)
    if count == 0:
        return "Pehle se sab done tha!"
    return f"Sab {count} homework item(s) done mark kar diye. Aaj ka kaam khatam!"


def _add_weak_area(args: dict) -> str:
    subject = args.get("subject", "").strip().upper()
    topic   = args.get("topic", "").strip()

    if not subject or not topic:
        return "[DailyLog] 'subject' aur 'topic' chahiye."

    data  = _load()
    today = _get_or_create_today(data)

    entry = {
        "subject":  subject,
        "topic":    topic,
        "date":     _today_str(),
        "noted_at": datetime.now().isoformat(),
    }
    today["weak_areas"].append(entry)
    _save(data)
    return f"Note kar li — {subject} mein '{topic}' samajhna baaki hai."


def _set_checkin_done(args: dict) -> str:
    data  = _load()
    today = _get_or_create_today(data)
    today["checkin_done"] = True
    _save(data)
    return "Aaj ka checkin done mark kar diya."


def _set_mood(args: dict) -> str:
    mood = args.get("mood", "").strip().lower()
    if not mood:
        return "[DailyLog] 'mood' field chahiye."

    data  = _load()
    today = _get_or_create_today(data)
    today["mood"] = mood
    _save(data)
    return f"Mood note kar li — {mood}."


def _get_today(args: dict) -> str:
    data  = _load()
    today = data.get(_today_str(), {})

    if not today:
        return "Aaj ka koi log nahi hai abhi. Post-college checkin abhi tak nahi hua."

    lines = [f"Aaj ka log ({_today_str()}):"]

    checkin = today.get("checkin_done", False)
    lines.append(f"  Checkin: {'done' if checkin else 'pending'}")

    mood = today.get("mood")
    if mood:
        lines.append(f"  Mood: {mood}")

    hw = today.get("homework", [])
    if hw:
        lines.append(f"\n  Homework ({len(hw)} items):")
        for item in hw:
            status = "done" if item.get("done") else "pending"
            dl     = f" [{item['deadline']}]" if item.get("deadline") else ""
            lines.append(f"    [{status}] [{item['id']}] {item['subject']}: {item['task']}{dl}")
    else:
        lines.append("\n  Homework: kuch nahi add hua abhi.")

    weak = today.get("weak_areas", [])
    if weak:
        lines.append(f"\n  Samajh nahi aaya ({len(weak)} topics):")
        for w in weak:
            lines.append(f"    - {w['subject']}: {w['topic']}")

    return "\n".join(lines)


def _get_pending(args: dict) -> str:
    data    = _load()
    today   = data.get(_today_str(), {})
    pending = [h for h in today.get("homework", []) if not h.get("done")]

    if not pending:
        return "Aaj ka saara homework done hai!"

    lines = [f"Pending homework ({len(pending)}):"]
    for item in pending:
        dl = f" (deadline: {item['deadline']})" if item.get("deadline") else ""
        lines.append(f"  [{item['id']}] {item['subject']}: {item['task']}{dl}")
    return "\n".join(lines)


def _list_weak_areas(args: dict) -> str:
    days  = int(args.get("days", 7))
    data  = _load()
    today = date.today()
    result = []

    for i in range(days):
        d_str = (today - timedelta(days=i)).isoformat()
        entry = data.get(d_str, {})
        for w in entry.get("weak_areas", []):
            result.append(f"  [{d_str}] {w['subject']}: {w['topic']}")

    if not result:
        return f"Pichle {days} din mein koi weak area note nahi hua."

    return f"Weak areas (last {days} days):\n" + "\n".join(result)


# ── Dispatcher ────────────────────────────────────────────────────────────────

_ACTIONS = {
    "add_homework":     _add_homework,
    "mark_done":        _mark_done,
    "mark_all_done":    _mark_all_done,
    "add_weak_area":    _add_weak_area,
    "set_checkin_done": _set_checkin_done,
    "set_mood":         _set_mood,
    "get_today":        _get_today,
    "get_pending":      _get_pending,
    "list_weak_areas":  _list_weak_areas,
}


def run_tool(args: dict = None) -> str:
    if args is None:
        args = {}
    action = str(args.get("action", "")).strip().lower()
    if not action:
        return (
            "[DailyLog] Action chahiye. Available:\n"
            "  add_homework, mark_done, mark_all_done,\n"
            "  add_weak_area, set_checkin_done, set_mood,\n"
            "  get_today, get_pending, list_weak_areas"
        )
    fn = _ACTIONS.get(action)
    if fn is None:
        return f"[DailyLog] Unknown action '{action}'. Available: {', '.join(_ACTIONS)}"
    try:
        return fn(args)
    except Exception as e:
        return f"[DailyLog] Error in '{action}': {e}"
