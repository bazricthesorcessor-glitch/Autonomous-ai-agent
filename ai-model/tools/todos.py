# tools/todos.py
"""
Todos tool — lets Avril create and manage a visible todo list.

The planner can call this tool to create, update, list, or clear todos.
When todos are created, the response includes a special __TODOS__ marker
that the UI renders as an interactive card in the chat.

Actions:
  create  — {"action": "create", "items": ["step 1", "step 2", ...]}
  update  — {"action": "update", "id": "<id>", "status": "done|in_progress|pending"}
  list    — {"action": "list"}
  clear   — {"action": "clear"}
"""

import json
from engines import todo_manager

# Status display helpers
_STATUS_ICON = {
    "done":        "☑",
    "in_progress": "▷",
    "pending":     "☐",
}


def run_tool(args: dict) -> str:
    action = args.get("action", "").strip().lower()

    # ── CREATE ──────────────────────────────────────────────────────────────
    if action == "create":
        raw_items = args.get("items", [])
        if not raw_items or not isinstance(raw_items, list):
            return "[Todos] Provide 'items' as a non-empty list of strings."

        new_items = todo_manager.create_items(raw_items)
        if not new_items:
            return "[Todos] No valid items created."

        # JSON block for UI card rendering — must come BEFORE any human text
        card_json = json.dumps(new_items, ensure_ascii=False)
        lines = [
            f"  {_STATUS_ICON[t['status']]} {t['content']}"
            for t in new_items
        ]
        return (
            f"__TODOS__\n{card_json}\n__TODOS__\n"
            f"Created {len(new_items)} todo item(s):\n" + "\n".join(lines)
        )

    # ── UPDATE ──────────────────────────────────────────────────────────────
    if action == "update":
        todo_id = args.get("id", "").strip()
        status  = args.get("status", "done").strip()
        if not todo_id:
            return "[Todos] Provide 'id' of the item to update."
        ok = todo_manager.update_status(todo_id, status)
        if ok:
            return f"[Todos] Item {todo_id} marked as '{status}'."
        return f"[Todos] Item '{todo_id}' not found or invalid status '{status}'."

    # ── LIST ────────────────────────────────────────────────────────────────
    if action == "list":
        todos = todo_manager.get_all()
        if not todos:
            return "[Todos] No todos yet."
        lines = [
            f"  [{t['id']}] {_STATUS_ICON.get(t.get('status','pending'), '☐')} {t['content']}"
            for t in todos
        ]
        return f"Current todos ({len(todos)}):\n" + "\n".join(lines)

    # ── CLEAR ────────────────────────────────────────────────────────────────
    if action == "clear":
        target = args.get("target", "all").strip().lower()
        if target == "done":
            removed = todo_manager.clear_done()
            return f"[Todos] Removed {removed} completed item(s)."
        todo_manager.clear_all()
        return "[Todos] Todo list cleared."

    return (
        "[Todos] Unknown action. Use: create | update | list | clear\n"
        "Example: {\"action\": \"create\", \"items\": [\"Step 1\", \"Step 2\"]}"
    )
