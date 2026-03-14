# ========================= engines/goal_scheduler.py =========================
"""
Autonomous Goal Scheduler — makes Avril proactive.

Reads memory/goals.json for "scheduled" goal entries.
Each entry has:
  id                — unique identifier
  prompt            — what to ask the agent loop
  interval_minutes  — how often to run
  enabled           — if false, skip
  last_run          — ISO timestamp of last execution (updated after each run)

The scheduler runs in a background daemon thread.
It wakes every CHECK_INTERVAL seconds and fires any goals that are due.

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

# How often the scheduler loop wakes up to check for due goals.
# Shorter = more responsive; longer = less overhead.
CHECK_INTERVAL_SECONDS = 60


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
                # Mark as run immediately to prevent re-firing while executing
                goal["last_run"] = datetime.now(timezone.utc).isoformat()
                changed = True
                # Execute in a separate thread so we don't block the scheduler
                threading.Thread(
                    target=self._run_and_log,
                    args=(goal.copy(),),
                    daemon=True,
                    name=f"Goal-{goal['id']}",
                ).start()

        if changed:
            # Write updated last_run timestamps back to goals.json
            try:
                with open(config.GOALS_FILE, "w") as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                print(f"[GoalScheduler] Failed to update goals.json: {e}")

    def _is_due(self, goal: dict) -> bool:
        """Return True if the goal should fire now."""
        last_run = goal.get("last_run")
        if not last_run:
            return True  # Never run — fire immediately on first check

        interval_minutes = goal.get("interval_minutes", 60)
        try:
            last_dt = datetime.fromisoformat(last_run)
            # Make timezone-aware if naive
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            elapsed_minutes = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
            return elapsed_minutes >= interval_minutes
        except Exception:
            return True  # Parse failure — fire to be safe

    def _run_and_log(self, goal: dict):
        """Execute a goal and log the result (meant to run in its own thread)."""
        try:
            result = self._run_goal(goal)
            self._log_result(goal["id"], goal["prompt"], result)
        except Exception as e:
            print(f"[GoalScheduler] Goal '{goal['id']}' thread error: {e}")

    def _run_goal(self, goal: dict) -> str:
        """Execute one scheduled goal through the full agent loop."""
        # Late import avoids circular dependency at module load time.
        from core import agent_loop
        from core import context_builder

        prompt = goal.get("prompt", "Check system status.")
        try:
            memory_ctx = context_builder.build_context(prompt)
            # Use a neutral system persona so goals don't conflict with user persona
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
