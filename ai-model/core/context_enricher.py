# ========================= core/context_enricher.py =========================
"""
User context enricher — runs before every turn and builds a rich UserContext
that gets injected into the planner system prompt.

Covers:
  - Current time, day, time-of-day
  - Exam proximity and strictness mode (normal → exam_eve)
  - Today's college schedule
  - Pending homework count from daily_log.json
  - Whether the post-college checkin was done today
  - Free-day detection
"""

import os
import json
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional

import config

# ── Paths ─────────────────────────────────────────────────────────────────────
_SCHEDULE_PATH   = os.path.join(config.MEMORY_DIR, "schedule.json")
_DAILY_LOG_PATH  = os.path.join(config.MEMORY_DIR, "daily_log.json")
_PREP_PATH       = os.path.join(config.MEMORY_DIR, "prep_status.json")
_REMEMBER_PATH   = os.path.join(config.MEMORY_DIR, "remember.json")

# Public aliases (used by context_builder + task imports)
SCHEDULE_PATH  = _SCHEDULE_PATH
DAILY_LOG_PATH = _DAILY_LOG_PATH
REMEMBER_PATH  = _REMEMBER_PATH


# ── UserContext dataclass ─────────────────────────────────────────────────────

@dataclass
class UserContext:
    timestamp: str = ""
    day_of_week: str = ""          # "Monday", …
    hour: int = 0
    time_of_day: str = ""          # morning | afternoon | evening | night
    is_exam_week: bool = False
    is_free_day: bool = False
    days_to_next_exam: int = 999
    next_exam_subject: str = ""
    next_exam_date: str = ""
    strictness_mode: str = "normal"
    strictness_label: str = ""
    allow_entertainment: bool = True
    bedtime_override: Optional[str] = None
    wake_override: Optional[str] = None
    todays_college_ends: str = ""
    home_by: str = ""
    todays_periods: list = field(default_factory=list)
    pending_homework_count: int = 0
    pending_homework_items: list = field(default_factory=list)
    checkin_done_today: bool = False
    daily_checkin_time: str = ""
    due_reminders: list = field(default_factory=list)
    due_errands: list = field(default_factory=list)
    detected_mode: str = "general"  # study | relax | work | general (legacy compat)

    # ── Live system state (populated every turn from tools/system_state.py) ───
    focused_app:        str   = ""   # "firefox", "code", "kate" …
    focused_title:      str   = ""   # full window title
    open_apps:          list  = field(default_factory=list)
    media_playing:      bool  = False
    media_title:        str   = ""   # "Moon Princess"
    media_artist:       str   = ""   # "One Piece"
    media_player:       str   = ""   # "vlc", "firefox" …
    media_status:       str   = ""   # "Playing" | "Paused"
    audio_running:      bool  = False
    audio_apps:         list  = field(default_factory=list)
    volume_pct:         int   = 0
    system_state_raw:   str   = ""   # full to_context_block() string


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_schedule() -> dict:
    return config.safe_load_json(_SCHEDULE_PATH, {})


def _load_daily_log() -> dict:
    return config.safe_load_json(_DAILY_LOG_PATH, {})


def _time_of_day(hour: int) -> str:
    if hour < 6:
        return "night"
    elif hour < 12:
        return "morning"
    elif hour < 17:
        return "afternoon"
    elif hour < 21:
        return "evening"
    else:
        return "night"


def _get_next_exam(schedule: dict, today: date) -> tuple[int, str, str]:
    """Returns (days_to_exam, subject_name, exam_date_str). Looks at upcoming dates only."""
    min_days = 999
    next_subject = ""
    next_date_str = ""

    for exam_group in schedule.get("exams", []):
        for exam in exam_group.get("dates", []):
            try:
                exam_date = datetime.strptime(exam["date"], "%Y-%m-%d").date()
                days = (exam_date - today).days
                if 0 <= days < min_days:
                    min_days = days
                    next_subject = exam.get("subject", exam.get("code", ""))
                    next_date_str = exam["date"]
            except (KeyError, ValueError):
                continue

    return min_days, next_subject, next_date_str


def _get_strictness(schedule: dict, days_to_exam: int) -> dict:
    """Match days_to_exam to the tightest strictness level in the ramp."""
    ramp = schedule.get("strictness_ramp", [])
    # Sort ascending by days_to_exam, pick tightest (smallest) threshold that covers current days
    matched = {"mode": "normal", "label": "Normal", "allow_entertainment": True,
               "bedtime_override": None, "wake_override": None, "description": ""}
    for level in sorted(ramp, key=lambda x: x["days_to_exam"]):
        if days_to_exam <= level["days_to_exam"]:
            matched = level
            break
    return matched


# ── Public API ────────────────────────────────────────────────────────────────

def build_user_context(now: datetime = None) -> UserContext:
    """Build a rich UserContext from current time + schedule + daily log."""
    if now is None:
        now = datetime.now()

    today = now.date()
    today_str = today.isoformat()
    day_lower = now.strftime("%A").lower()
    hour = now.hour

    ctx = UserContext(
        timestamp=now.strftime("%A, %B %d %Y at %I:%M %p"),
        day_of_week=now.strftime("%A"),
        hour=hour,
        time_of_day=_time_of_day(hour),
    )

    schedule = _load_schedule()

    # ── Today's college schedule ───────────────────────────────────────────────
    today_sched = schedule.get("college_schedule", {}).get(day_lower, {})
    ctx.todays_college_ends   = today_sched.get("college_ends", "")
    ctx.home_by               = today_sched.get("home_by", "")
    ctx.daily_checkin_time    = today_sched.get("daily_checkin_time", "")
    ctx.todays_periods        = today_sched.get("periods", [])
    # Free day = weekend or explicitly partial-free with no periods
    is_weekend = day_lower in ("saturday", "sunday")
    is_partial_free = today_sched.get("is_partial_free", False)
    has_no_periods = not ctx.todays_periods
    ctx.is_free_day = is_weekend or (is_partial_free and has_no_periods)

    # Check explicit free days list
    if today_str in schedule.get("free_days", []):
        ctx.is_free_day = True

    # ── Exam proximity ─────────────────────────────────────────────────────────
    min_days, next_subject, next_date_str = _get_next_exam(schedule, today)
    ctx.days_to_next_exam = min_days
    ctx.next_exam_subject = next_subject
    ctx.next_exam_date = next_date_str
    ctx.is_exam_week = min_days <= 7

    # ── Strictness mode ────────────────────────────────────────────────────────
    strictness = _get_strictness(schedule, min_days)
    ctx.strictness_mode = strictness.get("mode", "normal")
    ctx.strictness_label = strictness.get("label", "")
    ctx.allow_entertainment = strictness.get("allow_entertainment", True)
    ctx.bedtime_override = strictness.get("bedtime_override")
    ctx.wake_override = strictness.get("wake_override")

    # ── Pending homework from daily_log ────────────────────────────────────────
    try:
        daily = _load_daily_log()
        today_log = daily.get(today_str, {})
        pending = [h for h in today_log.get("homework", []) if not h.get("done", False)]
        ctx.pending_homework_count = len(pending)
        ctx.pending_homework_items = pending
        ctx.checkin_done_today = today_log.get("checkin_done", False)
    except Exception:
        pass

    # ── Due reminders + errands from remember.json ─────────────────────────────
    try:
        if os.path.exists(_REMEMBER_PATH):
            with open(_REMEMBER_PATH) as _f:
                rem_data = _f.read().strip()
            rem = json.loads(rem_data) if rem_data else {}
            now_h, now_m = hour, now.minute

            for r in rem.get("reminders", []):
                if r.get("done"):
                    continue
                if r.get("datetime"):
                    try:
                        dt = datetime.fromisoformat(r["datetime"])
                        if (dt.date() - today).days <= 0:
                            ctx.due_reminders.append(r)
                    except Exception:
                        pass
                elif r.get("date") and r.get("recurs") == "yearly":
                    try:
                        md = r["date"][5:]
                        ed = date.fromisoformat(f"{today.year}-{md}")
                        days_away = (ed - today).days
                        if days_away in r.get("remind_days_before", [1, 0]):
                            ctx.due_reminders.append({**r, "days_away": days_away})
                    except Exception:
                        pass

            for e in rem.get("errands", []):
                if e.get("done"):
                    continue
                if e.get("remind_date") != today_str:
                    continue
                if e.get("remind_at"):
                    try:
                        h_e, m_e = map(int, e["remind_at"].split(":"))
                        diff = abs((now_h * 60 + now_m) - (h_e * 60 + m_e))
                        if diff <= 2:
                            ctx.due_errands.append(e)
                    except Exception:
                        pass
    except Exception:
        pass

    # ── Legacy detected_mode (backward compat with simple callers) ─────────────
    if ctx.strictness_mode in ("critical", "exam_eve", "strict"):
        ctx.detected_mode = "study"
    elif ctx.is_free_day:
        ctx.detected_mode = "relax"
    elif ctx.todays_periods:
        ctx.detected_mode = "work"
    else:
        ctx.detected_mode = "general"

    # ── Live system state ─────────────────────────────────────────────────────
    try:
        from tools.system_state import get_snapshot
        snap = get_snapshot()

        ctx.focused_app    = snap.window.focused_class or snap.window.focused_app
        ctx.focused_title  = snap.window.focused_title
        ctx.open_apps      = list(dict.fromkeys(snap.window.all_apps))

        ctx.media_playing  = snap.media.playing
        ctx.media_title    = snap.media.title
        ctx.media_artist   = snap.media.artist
        ctx.media_player   = snap.media.player
        ctx.media_status   = snap.media.status

        ctx.audio_running  = snap.audio.running
        ctx.audio_apps     = snap.audio.active_apps
        ctx.volume_pct     = snap.audio.volume_pct

        ctx.system_state_raw = snap.to_context_block()
    except Exception:
        pass   # system state is best-effort, never block the turn

    return ctx


def format_for_prompt(ctx: UserContext) -> str:
    """Format UserContext as an injected block for the LLM planner."""
    mode_desc = {
        "normal":      "Normal day. Be warm and helpful.",
        "prep_start":  "3 weeks to exams. Mention revision casually. Still friendly.",
        "prep_active": "2 weeks to exams. More serious about study reminders.",
        "strict":      "1 week to exams. Firm on study time. No entertainment unless homework done.",
        "critical":    "3 days to exams. Maximum strictness. Do not accept excuses.",
        "exam_eve":    "EXAM TOMORROW. Force sleep at 10pm. Only light revision allowed.",
    }

    lines = [
        "[AVRIL CONTEXT]",
        f"Time: {ctx.timestamp}",
        f"Day: {ctx.day_of_week} ({ctx.time_of_day})",
        f"Mode: {ctx.strictness_mode} — {mode_desc.get(ctx.strictness_mode, '')}",
    ]

    if ctx.days_to_next_exam <= 21:
        lines.append(
            f"Exam alert: {ctx.next_exam_subject} on {ctx.next_exam_date} "
            f"({ctx.days_to_next_exam} days away)"
        )

    if not ctx.allow_entertainment:
        lines.append("Entertainment: BLOCKED until homework is done.")

    if ctx.pending_homework_count > 0:
        items_str = ", ".join(
            f"{h.get('subject','?')}: {h.get('task','?')}"
            for h in ctx.pending_homework_items[:3]
        )
        lines.append(f"Pending homework ({ctx.pending_homework_count}): {items_str}")

    if ctx.is_free_day:
        lines.append("Today is a free day / holiday.")
    elif ctx.todays_college_ends:
        lines.append(
            f"Today college ends: {ctx.todays_college_ends}, home by ~{ctx.home_by}"
        )
        if ctx.todays_periods:
            subjects_today = ", ".join(p["subject"] for p in ctx.todays_periods)
            lines.append(f"Today's subjects: {subjects_today}")

    if not ctx.checkin_done_today and ctx.home_by and not ctx.is_free_day:
        lines.append("Post-college checkin: NOT yet done today.")
    elif ctx.daily_checkin_time and not ctx.checkin_done_today:
        lines.append(f"Post-college checkin due at: {ctx.daily_checkin_time}")

    # Due reminders / errands
    for r in ctx.due_reminders[:2]:
        title = r.get("title") or r.get("person", "")
        days  = r.get("days_away", 0)
        msg   = f"REMINDER DUE: {title}" + (f" in {days} days" if days else " TODAY")
        lines.append(msg)
    for e in ctx.due_errands[:2]:
        lines.append(f"ERRAND DUE NOW: {e.get('task', '')}")

    if ctx.bedtime_override:
        lines.append(f"Bedtime tonight: {ctx.bedtime_override} (exam mode override).")

    # Live system state — always show if populated
    if ctx.system_state_raw:
        lines.append("")
        lines.append(ctx.system_state_raw)

    return "\n".join(lines)


def get_strictness_mode(schedule: dict = None) -> dict:
    """Convenience: return current strictness config dict (used by goal_scheduler)."""
    if schedule is None:
        schedule = _load_schedule()
    today = date.today()
    min_days, _, _ = _get_next_exam(schedule, today)
    return _get_strictness(schedule, min_days)


def get_days_to_next_exam() -> int:
    """Return days until next exam. Used by alarm and bedtime logic."""
    schedule = _load_schedule()
    today = date.today()
    min_days, _, _ = _get_next_exam(schedule, today)
    return min_days


def calculate_wake_time(schedule: dict = None) -> str:
    """
    Return the actual wake time based on exam proximity and prep status.
    Used by the morning alarm goal.
    """
    if schedule is None:
        schedule = _load_schedule()

    today = date.today()
    days_to_exam, next_subject, _ = _get_next_exam(schedule, today)

    base = schedule.get("morning", {}).get("base_wake_time", "05:30")

    # Check for post-exam reward window
    for exam_group in schedule.get("exams", []):
        try:
            series_end = datetime.strptime(exam_group["series_end"], "%Y-%m-%d").date()
            days_since_end = (today - series_end).days
            reward_days = exam_group.get("post_exam_reward_days", 0)
            if 0 <= days_since_end < reward_days:
                return exam_group.get("post_exam_wake", "08:00")
        except (KeyError, ValueError):
            continue

    # Exam proximity adjustments
    if days_to_exam == 1:
        # Check prep status
        prep = config.safe_load_json(_PREP_PATH, {})
        subject_key = next_subject.lower().replace(" ", "_")
        completion = prep.get(subject_key, {}).get("completion_pct", 100)
        if completion < 80:
            return "04:30"
        return "04:45"

    if days_to_exam <= 3:
        return "04:45"
    if days_to_exam <= 7:
        return "05:00"

    return base
