# engines/todo_manager.py
"""
Manages Avril's todo list stored in memory/todos.json.

Todos are session-persistent (survive restarts) but are meant for
the current context — not long-term memory.

Schema per item:
  id         — short 8-char hex uuid
  content    — the task description
  status     — 'pending' | 'in_progress' | 'done'
  created_at — ISO timestamp
  updated_at — ISO timestamp (set on status change)
"""

import json
import os
import uuid
import tempfile
import threading
from datetime import datetime
import config

# ── File path ─────────────────────────────────────────────────────────────────
TODOS_FILE = config.TODOS_FILE
_todo_lock = threading.Lock()


# ── Private helpers ───────────────────────────────────────────────────────────

def _load() -> list:
    data = config.safe_load_json(TODOS_FILE, [])
    return data if isinstance(data, list) else []


def _save(todos: list) -> None:
    dir_name = os.path.dirname(TODOS_FILE) or '.'
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(todos, f, indent=2, ensure_ascii=False)
        os.replace(tmp, TODOS_FILE)
    except Exception:
        os.unlink(tmp)
        raise


# ── Public API ────────────────────────────────────────────────────────────────

def get_all() -> list:
    """Return all todos (all statuses)."""
    return _load()


def get_active() -> list:
    """Return only pending and in-progress todos."""
    return [t for t in _load() if t.get("status") != "done"]


def create_items(items: list) -> list:
    """
    Create new todo items from a list of strings.
    Returns the newly created items with their assigned ids.
    """
    todos = _load()
    new_items = []
    now = datetime.now().isoformat()
    for content in items:
        content = str(content).strip()
        if not content:
            continue
        item = {
            "id":         uuid.uuid4().hex[:8],
            "content":    content,
            "status":     "pending",
            "created_at": now,
        }
        todos.append(item)
        new_items.append(item)
    _save(todos)
    return new_items


def update_status(todo_id: str, status: str) -> bool:
    """
    Update the status of a single todo item.
    status must be: 'pending' | 'in_progress' | 'done'
    Returns True on success, False if id not found.
    """
    valid = {"pending", "in_progress", "done"}
    if status not in valid:
        return False
    todos = _load()
    for item in todos:
        if item.get("id") == todo_id:
            item["status"]     = status
            item["updated_at"] = datetime.now().isoformat()
            _save(todos)
            return True
    return False


def clear_done() -> int:
    """Remove completed todos. Returns the count removed."""
    todos   = _load()
    active  = [t for t in todos if t.get("status") != "done"]
    removed = len(todos) - len(active)
    _save(active)
    return removed


def clear_all() -> None:
    """Delete every todo."""
    _save([])
