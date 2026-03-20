# ========================= tools/remember.py =========================
"""
Remember tool — Avril's explicit zero-hallucination memory store.
Divyansh tells Avril to remember something → stored verbatim → read back verbatim.

Sections in memory/remember.json:
  reminders     — birthdays, anniversaries, one-time datetime reminders
  shopping_lists — grocery / stationery / dairy / other (persistent, accumulates)
  errands        — time-triggered tasks ("remind me at 5 to go to market")

Actions:
  add           — add a reminder (type: birthday|anniversary|reminder|free_reminder)
  add_item      — add item to a shopping list
  add_errand    — "remind me at 5 to go to market", optionally attach lists
  list          — show all upcoming reminders + shopping lists + errands
  list_shopping — show shopping lists only (grouped by category)
  mark_done     — mark a reminder/errand done by id
  mark_item_done — mark a shopping item done
  delete        — delete a reminder/errand by id
  check         — (called by scheduler) return anything due right now
  clear_done    — remove all done items (called by janitor at night)
"""

import json, os, uuid
from datetime import datetime, date
import config

REMEMBER_PATH = os.path.join(config.MEMORY_DIR, "remember.json")

_EMPTY = {
    "reminders": [],
    "shopping_lists": {
        "grocery": [],
        "stationery": [],
        "dairy": [],
        "other": [],
    },
    "errands": [],
}


def _load() -> dict:
    if not os.path.exists(REMEMBER_PATH):
        return {k: (v.copy() if isinstance(v, dict) else list(v))
                for k, v in _EMPTY.items()}
    try:
        with open(REMEMBER_PATH) as f:
            data = json.load(f)
        # Ensure all sections exist
        data.setdefault("reminders", [])
        data.setdefault("shopping_lists", {
            "grocery": [], "stationery": [], "dairy": [], "other": []
        })
        data.setdefault("errands", [])
        return data
    except Exception:
        return {k: (v.copy() if isinstance(v, dict) else list(v))
                for k, v in _EMPTY.items()}


def _save(data: dict):
    os.makedirs(os.path.dirname(REMEMBER_PATH), exist_ok=True)
    tmp = REMEMBER_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, REMEMBER_PATH)
    except Exception as e:
        print(f"[Remember] Save failed: {e}")


def run_tool(args: dict = None) -> str:
    if args is None:
        args = {}
    action = args.get("action", "list")

    # ── ADD REMINDER ──────────────────────────────────────────────────────────
    if action == "add":
        data = _load()
        r = {
            "id":                 "rem_" + uuid.uuid4().hex[:6],
            "type":               args.get("type", "free_reminder"),
            "title":              args.get("title", ""),
            "person":             args.get("person", ""),
            "date":               args.get("date", ""),
            "datetime":           args.get("datetime", ""),
            "recurs":             args.get("recurs", "never"),
            "remind_days_before": args.get("remind_days_before", [1]),
            "message":            args.get("message", ""),
            "created_at":         date.today().isoformat(),
            "done":               False,
        }
        data["reminders"].append(r)
        _save(data)
        label = r.get("title") or r.get("person") or r.get("type")
        when  = r.get("datetime") or r.get("date") or "recurring"
        return f"Yaad rakhungi — {label} ({when}). [{r['id']}]"

    # ── ADD SHOPPING ITEM ─────────────────────────────────────────────────────
    if action == "add_item":
        cat  = args.get("category", "grocery").lower()
        item = args.get("item", "").strip()
        qty  = args.get("qty", None)
        if not item:
            return "Kya add karna hai? 'item' field chahiye."
        data = _load()
        if cat not in data["shopping_lists"]:
            data["shopping_lists"][cat] = []
        data["shopping_lists"][cat].append({
            "item":  item,
            "qty":   qty,
            "added": date.today().isoformat(),
            "done":  False,
        })
        _save(data)
        qty_str = f" ({qty})" if qty else ""
        return f"List mein daal diya — {item}{qty_str} [{cat}]."

    # ── ADD ERRAND ────────────────────────────────────────────────────────────
    if action == "add_errand":
        data = _load()
        e = {
            "id":           "erd_" + uuid.uuid4().hex[:6],
            "task":         args.get("task", ""),
            "remind_at":    args.get("remind_at", ""),
            "remind_date":  args.get("remind_date", date.today().isoformat()),
            "recurs":       args.get("recurs", "never"),
            "attach_lists": args.get("attach_lists", []),
            "done":         False,
            "created_at":   datetime.now().isoformat(),
        }
        data["errands"].append(e)
        _save(data)
        when = f"{e['remind_at']} baje" if e["remind_at"] else "jab time aaye"
        return f"Theek hai, {when} yaad dilaungi — {e['task']}. [{e['id']}]"

    # ── LIST ──────────────────────────────────────────────────────────────────
    if action == "list":
        data  = _load()
        lines = []

        reminders = [r for r in data.get("reminders", []) if not r.get("done")]
        if reminders:
            lines.append("Reminders:")
            for r in reminders:
                when  = r.get("datetime") or r.get("date") or "yearly"
                label = r.get("title") or r.get("person") or r.get("type")
                lines.append(f"  [{r['id']}] {label} — {when}")

        shopping = data.get("shopping_lists", {})
        for cat, items in shopping.items():
            pending = [i for i in items if not i.get("done")]
            if pending:
                lines.append(f"\n{cat.capitalize()} list:")
                for i in pending:
                    qty = f" ({i['qty']})" if i.get("qty") else ""
                    lines.append(f"  - {i['item']}{qty}")

        errands = [e for e in data.get("errands", []) if not e.get("done")]
        if errands:
            lines.append("\nErrands:")
            for e in errands:
                when = f"{e['remind_at']} baje" if e.get("remind_at") else "pending"
                lines.append(f"  [{e['id']}] {e['task']} — {when}")

        return "\n".join(lines) if lines else "Koi reminder, list ya errand nahi hai abhi."

    # ── LIST SHOPPING ONLY ────────────────────────────────────────────────────
    if action == "list_shopping":
        data  = _load()
        lines = []
        for cat, items in data.get("shopping_lists", {}).items():
            pending = [i for i in items if not i.get("done")]
            if pending:
                lines.append(f"{cat.capitalize()}:")
                for i in pending:
                    qty = f" ({i['qty']})" if i.get("qty") else ""
                    lines.append(f"  - {i['item']}{qty}")
        return "\n".join(lines) if lines else "Shopping list khali hai."

    # ── MARK DONE ─────────────────────────────────────────────────────────────
    if action == "mark_done":
        rid  = args.get("id", "")
        data = _load()
        for r in data.get("reminders", []) + data.get("errands", []):
            if r.get("id") == rid:
                r["done"] = True
                _save(data)
                return f"[{rid}] done mark kar diya."
        return f"ID {rid} nahi mila."

    # ── MARK ITEM DONE ────────────────────────────────────────────────────────
    if action == "mark_item_done":
        cat  = args.get("category", "grocery").lower()
        item = args.get("item", "").strip().lower()
        data = _load()
        for i in data.get("shopping_lists", {}).get(cat, []):
            if i["item"].lower() == item:
                i["done"] = True
                _save(data)
                return f"{item} ({cat}) done mark kar diya."
        return f"{item} nahi mila {cat} list mein."

    # ── DELETE ────────────────────────────────────────────────────────────────
    if action == "delete":
        rid  = args.get("id", "")
        data = _load()
        before = len(data["reminders"]) + len(data["errands"])
        data["reminders"] = [r for r in data["reminders"] if r.get("id") != rid]
        data["errands"]   = [e for e in data["errands"]   if e.get("id") != rid]
        after = len(data["reminders"]) + len(data["errands"])
        if before != after:
            _save(data)
            return f"[{rid}] delete kar diya."
        return f"ID {rid} nahi mila."

    # ── CHECK (called by scheduler every tick) ────────────────────────────────
    if action == "check":
        data      = _load()
        today     = date.today()
        today_str = today.isoformat()
        now       = datetime.now()
        messages  = []

        # One-time reminders due today
        for r in data.get("reminders", []):
            if r.get("done"):
                continue
            if r.get("datetime"):
                try:
                    dt = datetime.fromisoformat(r["datetime"])
                    if dt.date() == today and abs((now - dt).total_seconds()) <= 120:
                        messages.append(r.get("message") or f"Reminder: {r.get('title', '')}")
                except Exception:
                    pass
            elif r.get("recurs") == "yearly" and r.get("date"):
                try:
                    md = r["date"][5:]
                    ed = date.fromisoformat(f"{today.year}-{md}")
                    days_away = (ed - today).days
                    if days_away in r.get("remind_days_before", [1, 0]):
                        person = r.get("person") or r.get("title", "")
                        msg    = r.get("message", "")
                        if not msg:
                            word = "aaj" if days_away == 0 else f"{days_away} din mein"
                            msg  = f"Yaad hai? {person} ka {word} birthday/anniversary hai!"
                        messages.append(msg)
                except Exception:
                    pass

        # Errands due right now (±2 min window)
        for e in data.get("errands", []):
            if e.get("done") or e.get("remind_date") != today_str:
                continue
            if not e.get("remind_at"):
                continue
            try:
                h, m = map(int, e["remind_at"].split(":"))
                scheduled = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if abs((now - scheduled).total_seconds()) <= 120:
                    msg = f"Tune bola tha — {e['task']}!"
                    # Attach shopping lists
                    for cat in e.get("attach_lists", []):
                        items = [
                            i for i in data["shopping_lists"].get(cat, [])
                            if not i.get("done")
                        ]
                        if items:
                            names = ", ".join(
                                i["item"] + (f" ({i['qty']})" if i.get("qty") else "")
                                for i in items
                            )
                            msg += f"\n  {cat.capitalize()}: {names}"
                    messages.append(msg)
            except Exception:
                pass

        return "\n\n".join(messages) if messages else ""

    # ── CLEAR DONE (called by janitor nightly) ────────────────────────────────
    if action == "clear_done":
        data     = _load()
        before_r = len(data["reminders"])
        before_e = len(data["errands"])

        data["errands"] = [e for e in data["errands"] if not e.get("done")]
        data["reminders"] = [
            r for r in data["reminders"]
            if not r.get("done") or r.get("recurs") == "yearly"
        ]
        # Reset done flag on recurring reminders so they fire again next year
        for r in data["reminders"]:
            if r.get("recurs") == "yearly":
                r["done"] = False

        for cat in data["shopping_lists"].values():
            cat[:] = [i for i in cat if not i.get("done")]

        _save(data)
        removed = (before_r - len(data["reminders"])) + (before_e - len(data["errands"]))
        return f"[Remember] {removed} done item(s) cleaned up."

    return (
        f"Unknown action '{action}'. Available: "
        "add, add_item, add_errand, list, list_shopping, "
        "mark_done, mark_item_done, delete, check, clear_done"
    )
