# ========================= engines/goal_scheduler.py =========================
"""
Autonomous Goal Scheduler — makes Avril proactive.

Reads memory/goals.json for "scheduled" goal entries.
Each entry has:
  id                — unique identifier
  prompt            — what to ask the agent loop (for agent goals)
  interval_minutes  — how often to run (interval-based goals)
  trigger_time      — "HH:MM" clock time to fire once per day (clock-based goals)
  enabled           — if false, skip
  last_run          — ISO timestamp of last execution (updated after each run)

  Voice-only notification goals (no agent loop) also support:
  voice_only        — true
  message           — TTS message text
  mood              — normal | sad | crying | firm
  action            — notify | tts_notify | tts_volume_lower | shutdown

The scheduler runs in a background daemon thread.
It wakes every CHECK_INTERVAL_SECONDS and fires any goals that are due.

Usage:
    from engines.goal_scheduler import GoalScheduler
    scheduler = GoalScheduler()
    scheduler.start()
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
import config

# 30s gives ±30s accuracy on clock-triggered events — good enough for bedtime/alarm.
CHECK_INTERVAL_SECONDS = 30


class GoalScheduler:
    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        """Start the background scheduler thread (daemon — dies with main process)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="GoalScheduler")
        self._thread.start()
        print("[GoalScheduler] Started.")

    def stop(self):
        """Signal the scheduler to stop after the current sleep cycle."""
        self._stop_event.set()
        print("[GoalScheduler] Stop requested.")

    # ── Internal loop ─────────────────────────────────────────────────────────

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                print(f"[GoalScheduler] Uncaught error in tick: {e}")
            self._stop_event.wait(CHECK_INTERVAL_SECONDS)

    def _tick(self):
        """Check all scheduled goals and fire any that are due."""
        # Respect the global autonomous mode flag — skip entire tick if disabled
        try:
            from core import autonomous_mode
            if not autonomous_mode.is_enabled():
                return
        except Exception:
            pass  # If module unavailable, proceed normally

        data = config.safe_load_json(config.GOALS_FILE, {})
        scheduled = data.get("scheduled", [])
        if not scheduled:
            return

        changed = False
        for goal in scheduled:
            if not goal.get("enabled", True):
                continue
            if self._is_due(goal):
                print(f"[GoalScheduler] Firing goal: {goal['id']}")
                goal["last_run"] = datetime.now(timezone.utc).isoformat()
                changed = True
                threading.Thread(
                    target=self._run_and_log,
                    args=(goal.copy(),),
                    daemon=True,
                    name=f"Goal-{goal['id']}",
                ).start()

        if changed:
            try:
                with open(config.GOALS_FILE, "w") as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                print(f"[GoalScheduler] Failed to update goals.json: {e}")

    def _is_due(self, goal: dict) -> bool:
        """
        Return True if the goal should fire now.

        Supports three scheduling modes:
          1. trigger_time "HH:MM" — fires once per day at that clock time
          2. trigger_time "DYNAMIC" — reads daily_checkin_time from schedule.json
          3. interval_minutes     — fires every N minutes (original behavior)
        """
        trigger_time = goal.get("trigger_time")

        # Resolve DYNAMIC trigger_time from today's college schedule
        if trigger_time == "DYNAMIC":
            try:
                with open(config.MEMORY_DIR + "/schedule.json") as _f:
                    sched = json.load(_f)
                day = datetime.now().strftime("%A").lower()
                trigger_time = (
                    sched.get("college_schedule", {})
                    .get(day, {})
                    .get("daily_checkin_time", "16:00")
                ) or "16:00"
            except Exception:
                trigger_time = "16:00"

        if trigger_time:
            return self._is_clock_due(goal, trigger_time)

        # Interval-based scheduling (original logic)
        last_run = goal.get("last_run")
        if not last_run:
            return True

        interval_minutes = goal.get("interval_minutes", 60)
        try:
            last_dt = datetime.fromisoformat(last_run)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            elapsed_minutes = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
            return elapsed_minutes >= interval_minutes
        except Exception:
            return True

    def _is_clock_due(self, goal: dict, trigger_time: str) -> bool:
        """
        Check if a clock-based goal should fire right now.
        Fire window: [trigger_time, trigger_time + CHECK_INTERVAL_SECONDS)
        """
        now = datetime.now()

        try:
            h, m = (int(x) for x in trigger_time.split(":"))
        except (ValueError, AttributeError):
            return False

        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        # Use timedelta so the window correctly spans across second=0 to +30s
        from datetime import timedelta
        window_end = target + timedelta(seconds=CHECK_INTERVAL_SECONDS)

        if not (target <= now < window_end):
            return False

        # Did we already run it today at or after trigger_time?
        last_run = goal.get("last_run")
        if last_run:
            try:
                last_dt = datetime.fromisoformat(last_run)
                if last_dt.tzinfo is not None:
                    offset = last_dt.utcoffset()
                    last_dt = (last_dt - offset).replace(tzinfo=None) if offset else last_dt.replace(tzinfo=None)
                if last_dt.date() == now.date() and last_dt >= target:
                    return False
            except Exception:
                pass

        return True

    def _run_and_log(self, goal: dict):
        """Execute a goal and log the result (meant to run in its own thread)."""
        if goal.get("voice_only"):
            self._run_voice_goal(goal)
            return
        try:
            result = self._run_goal(goal)
            self._log_result(goal["id"], goal.get("prompt", ""), result)
        except Exception as e:
            print(f"[GoalScheduler] Goal '{goal['id']}' thread error: {e}")

    def _run_voice_goal(self, goal: dict):
        """Execute a voice notification goal: TTS + optional system action."""
        message = goal.get("message", "")
        mood = goal.get("mood", "normal")
        action = goal.get("action", "notify")

        print(f"[GoalScheduler] Voice goal '{goal['id']}': mood={mood} action={action}")
        if not message:
            return

        try:
            from core.voice import speak_and_play
            speak_and_play(message, mood=mood)
        except Exception as e:
            print(f"[GoalScheduler] TTS failed: {e}")

        try:
            self._execute_bedtime_action(action, goal)
        except Exception as e:
            print(f"[GoalScheduler] Bedtime action '{action}' failed: {e}")

        self._log_result(goal["id"], f"[Voice] {message}", f"mood={mood}, action={action}")

    def _execute_bedtime_action(self, action: str, goal: dict):
        """Execute a bedtime system action after TTS has been dispatched."""
        import subprocess as _sp

        if action in ("notify", "tts_notify"):
            icon = "Avril 🌙" if action == "tts_notify" else "Avril"
            timeout = "15000" if action == "tts_notify" else "10000"
            try:
                _sp.Popen(["notify-send", "-t", timeout, icon, goal.get("message", "")])
            except Exception:
                pass

        elif action == "tts_volume_lower":
            try:
                _sp.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "75%"])
            except Exception:
                pass
            try:
                _sp.Popen(["notify-send", "-t", "20000", "Avril", goal.get("message", "")])
            except Exception:
                pass

        elif action == "shutdown":
            try:
                _sp.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "100%"])
            except Exception:
                pass
            time.sleep(4)  # let TTS finish playing
            try:
                _sp.run(["hyprctl", "dispatch", "exit"])
            except Exception as e:
                print(f"[GoalScheduler] Shutdown command failed: {e}")

    def _run_goal(self, goal: dict) -> str:
        """Execute one scheduled goal through the full agent loop."""
        from core import agent_loop
        from core import context_builder

        prompt = goal.get("prompt", "Check system status.")
        try:
            memory_ctx = context_builder.build_context(prompt)
            persona = (
                f"You are {config.AI_NAME}, an autonomous AI assistant. "
                "You are running a scheduled background task — not responding to a user. "
                "Be concise, take action if needed, and log what you did."
            )
            result = agent_loop.run_turn(prompt, persona, memory_ctx)
            return result
        except Exception as e:
            return f"[GoalScheduler] Error running goal '{goal['id']}': {e}"

    def _log_result(self, goal_id: str, prompt: str, result: str):
        """Append the goal run result to today's raw log."""
        try:
            log_path = config.get_raw_log_path()
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry = (
                f"\n{config.LOG_DELIMITER}\n"
                f"[SCHEDULED GOAL: {goal_id}] {ts}\n"
                f"Prompt: {prompt}\n"
                f"Result: {result[:500]}\n"
                f"{config.LOG_DELIMITER}\n"
            )
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            print(f"[GoalScheduler] Failed to write log: {e}")
