"""
engines/task_manager.py

Persistent task tracking. Tasks survive server restarts.

Structure in memory/tasks.json:
{
  "active":    [ {task}, ... ],
  "completed": [ {task}, ... ]
}

A task looks like:
{
  "id":          "ab12cd34",
  "title":       "Fix wifi driver",
  "description": "Full goal text including context Divyansh provided",
  "credentials": {"wifi_ssid": "MyWifi", "wifi_password": "hunter2"},
  "steps":       [ {"step": "...", "result": "...", "status": "done", "at": "..."} ],
  "status":      "in_progress" | "completed" | "abandoned",
  "created_at":  "2026-03-10 14:00",
  "last_updated":"2026-03-10 14:12"
}
"""

import json
import os
import uuid
import tempfile
import threading
from datetime import datetime

import config

TASKS_PATH = config.TASKS_FILE
_RESULT_TRIM = 400   # Characters to keep from each step result in stored history
_MAX_COMPLETED = 100  # Keep only the most recent completed/abandoned tasks
_task_lock = threading.Lock()


def _load() -> dict:
    if not os.path.exists(TASKS_PATH):
        return {"active": [], "completed": []}
    try:
        with open(TASKS_PATH, "r") as f:
            content = f.read().strip()
        if not content:
            return {"active": [], "completed": []}
        return json.loads(content)
    except Exception:
        return {"active": [], "completed": []}


def _save(data: dict):
    # Prune completed list to cap
    completed = data.get("completed", [])
    if len(completed) > _MAX_COMPLETED:
        data["completed"] = completed[-_MAX_COMPLETED:]
    dir_name = os.path.dirname(TASKS_PATH) or '.'
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, TASKS_PATH)
    except Exception:
        os.unlink(tmp)
        raise


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ─── Public API ────────────────────────────────────────────────────────────────

def create_task(
    title: str,
    description: str,
    credentials: dict = None,
    category: str = "task_request",
    plan: list | None = None,
) -> str:
    """Create a new in-progress task. Returns the task id."""
    with _task_lock:
        data = _load()
        task = {
            "id":           str(uuid.uuid4())[:8],
            "title":        title,
            "description":  description,
            "credentials":  credentials or {},
            "category":     category,
            "plan":         plan or [],
            "steps":        [],
            "status":       "in_progress",
            "created_at":   _now(),
            "last_updated": _now(),
        }
        data["active"].append(task)
        _save(data)
        print(f"[TaskManager] Created task {task['id']}: {title}")
        return task["id"]


def get_active_task() -> dict | None:
    """Return the first in-progress task, or None."""
    data = _load()
    for task in data.get("active", []):
        if task.get("status") == "in_progress":
            return task
    return None


def get_active_tasks() -> list:
    """Return ALL in-progress tasks. Planner should be aware of all of them."""
    data = _load()
    return [t for t in data.get("active", []) if t.get("status") == "in_progress"]


def get_task_by_id(task_id: str) -> dict | None:
    """Find a task by ID across active list."""
    data = _load()
    for task in data.get("active", []):
        if task["id"] == task_id:
            return task
    return None


def add_step_result(task_id: str, step_description: str, result: str, status: str = "done"):
    """Append a completed step to the task's step log."""
    with _task_lock:
        data = _load()
        for task in data["active"]:
            if task["id"] == task_id:
                task["steps"].append({
                    "step":   step_description,
                    "result": (result or "")[:_RESULT_TRIM],
                    "status": status,
                    "at":     _now(),
                })
                task["last_updated"] = _now()
                _save(data)
                return


def complete_task(task_id: str, summary: str = ""):
    """Mark a task as complete and archive it."""
    with _task_lock:
        data = _load()
        for i, task in enumerate(data["active"]):
            if task["id"] == task_id:
                task["status"]       = "completed"
                task["completed_at"] = _now()
                task["summary"]      = summary
                data["completed"].append(task)
                data["active"].pop(i)
                _save(data)
                print(f"[TaskManager] Completed task {task_id}")
                return


def abandon_task(task_id: str, reason: str = ""):
    """Mark a task as abandoned and archive it."""
    with _task_lock:
        data = _load()
        for i, task in enumerate(data["active"]):
            if task["id"] == task_id:
                task["status"]        = "abandoned"
                task["abandoned_at"]  = _now()
                task["abandon_reason"] = reason
                data["completed"].append(task)
                data["active"].pop(i)
                _save(data)
                print(f"[TaskManager] Abandoned task {task_id}: {reason}")
                return


def abandon_all_active(reason: str = "user requested abort"):
    """Abandon every in-progress task. Called by !abort command."""
    with _task_lock:
        data = _load()
        now = _now()
        still_active = []
        for task in data["active"]:
            if task.get("status") == "in_progress":
                task["status"] = "abandoned"
                task["abandoned_at"] = now
                task["abandon_reason"] = reason
                data["completed"].append(task)
            else:
                still_active.append(task)
        data["active"] = still_active
        _save(data)
        print(f"[TaskManager] All tasks abandoned: {reason}")


def get_task_context(task: dict) -> str:
    """
    Format a task's current state as a compact string for the planner.
    Credentials are included so the agent can type passwords etc. without asking again.
    """
    if not task:
        return ""

    steps_lines = []
    for i, s in enumerate(task.get("steps", []), 1):
        result_preview = s.get("result", "")[:100].replace("\n", " ")
        steps_lines.append(f"  {i}. [{s['status']}] {s['step']}: {result_preview}")

    steps_text = "\n".join(steps_lines) if steps_lines else "  (none yet)"

    creds = task.get("credentials", {})
    creds_text = ""
    if creds:
        creds_text = f"\nCredentials: {json.dumps(creds)}"

    return (
        f"Task [{task['id']}]: {task['title']}\n"
        f"Category: {task.get('category', 'task_request')}\n"
        f"Goal: {task['description']}"
        f"{creds_text}\n"
        f"Plan: {json.dumps(task.get('plan', []))}\n"
        f"Steps done:\n{steps_text}\n"
        f"Last updated: {task.get('last_updated', '?')}"
    )


def get_all_tasks_context(tasks: list) -> str:
    """Format ALL active tasks for the planner prompt."""
    if not tasks:
        return ""
    blocks = [get_task_context(t) for t in tasks]
    return "\n\n".join(blocks)
