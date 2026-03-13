# ========================= tools/skill_builder.py =========================
"""
Skill builder — lets the AI create, inspect, delete, and reload custom skill tools.

Skills are regular Python modules stored in tools/skills/.
Each must expose a run_tool(args: dict) -> str function.

APPROVAL GATE: when the AI creates a skill, it is saved as PENDING.
The user must explicitly approve the skill before it is hot-registered
and callable by the agent.  This prevents runaway self-modification.

Actions:
  propose — AI writes skill code; saved as pending, NOT yet active
  list    — list all skills (active + pending)
  inspect — print a skill's full source code
  delete  — delete a skill file and unregister it
  reload  — (re-)load all approved skill files from disk
  approve — user approves a pending skill → activates it
  reject  — user rejects a pending skill → deletes the file
"""

import os
import re
import sys
import json
import importlib.util
from datetime import datetime

SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'skills')
_PENDING_META = os.path.join(SKILLS_DIR, '_pending.json')

# Patterns that must NEVER appear in AI-generated skill code
_DANGEROUS_PATTERNS = re.compile(
    r'subprocess|os\.system|os\.popen|os\.exec|os\.remove|os\.unlink|shutil\.rmtree'
    r'|__import__|eval\s*\(|exec\s*\(|open\s*\(.*/etc/'
    r'|socket\.socket|http\.server|smtplib'
    r'|ctypes|cffi|importlib\.import_module',
    re.IGNORECASE,
)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ensure_dir():
    os.makedirs(SKILLS_DIR, exist_ok=True)
    init = os.path.join(SKILLS_DIR, '__init__.py')
    if not os.path.exists(init):
        with open(init, 'w', encoding='utf-8') as f:
            f.write('# AI-generated skills package\n')


def _skill_path(name: str) -> str:
    return os.path.join(SKILLS_DIR, f"{name}.py")


def _import_module(name: str, path: str):
    """Dynamically import a skill file and return the module object."""
    spec = importlib.util.spec_from_file_location(f"tools.skills.{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"tools.skills.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


def _doc_summary(path: str) -> str:
    """Return the first meaningful line of the module docstring."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        for q in ('"""', "'''"):
            if q in content:
                start = content.index(q) + 3
                rest  = content[start:]
                if q in rest:
                    end = rest.index(q)
                    doc = rest[:end].strip()
                    return doc.split('\n')[0][:90]
    except Exception:
        pass
    return ''


# ── Pending skills metadata ──────────────────────────────────────────────────

def _load_pending() -> dict:
    """Load pending skills metadata: {name: {purpose, proposed_at}}."""
    try:
        with open(_PENDING_META, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_pending(data: dict):
    _ensure_dir()
    with open(_PENDING_META, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def _is_pending(name: str) -> bool:
    return name in _load_pending()


# ── Action functions ──────────────────────────────────────────────────────────

def _propose(args: dict) -> str:
    """AI proposes a new skill. Saved to disk but NOT activated until user approves."""
    name = str(args.get('name', '')).strip().replace(' ', '_').lower()
    if not name:
        return "[skill_builder] 'name' is required."
    if not name.isidentifier():
        return f"[skill_builder] Invalid name '{name}' — must be a valid Python identifier."

    code = str(args.get('code', '')).strip()
    if not code:
        return "[skill_builder] 'code' is required."
    if 'def run_tool' not in code:
        return "[skill_builder] Skill code must contain a 'def run_tool(args)' function."

    # Safety scan: block dangerous patterns
    match = _DANGEROUS_PATTERNS.search(code)
    if match:
        return (
            f"[skill_builder] BLOCKED: code contains forbidden pattern '{match.group()}'. "
            "Skills cannot use subprocess, eval, exec, os.system, sockets, etc."
        )

    _ensure_dir()
    path = _skill_path(name)

    # Prepend a docstring header if code doesn't already have one
    purpose = str(args.get('purpose', 'Custom skill')).strip()
    if not (code.startswith('"""') or code.startswith("'''")):
        header = (
            f'"""\n'
            f'Skill: {name}\n'
            f'Purpose: {purpose}\n'
            f'Created: {datetime.now().strftime("%Y-%m-%d")}\n'
            f'Status: PENDING — awaiting user approval\n'
            f'"""\n\n'
        )
        code = header + code

    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(code)
    except Exception as e:
        return f"[skill_builder] Failed to write skill file: {e}"

    # Mark as pending (NOT registered in the tool registry)
    pending = _load_pending()
    pending[name] = {
        'purpose': purpose,
        'proposed_at': datetime.now().isoformat(),
        'file': path,
    }
    _save_pending(pending)

    return (
        f"Skill '{name}' proposed and saved to disk.\n"
        f"Purpose: {purpose}\n"
        f"File: {path}\n"
        f"STATUS: PENDING — waiting for user approval.\n"
        f"The user must run: !skill approve {name}  (or use the API)"
    )


def _approve(args: dict) -> str:
    """User approves a pending skill → load and register it."""
    name = str(args.get('name', '')).strip().lower()
    if not name:
        return "[skill_builder] 'name' is required."

    pending = _load_pending()
    if name not in pending:
        return f"[skill_builder] '{name}' is not in the pending queue."

    path = _skill_path(name)
    if not os.path.exists(path):
        pending.pop(name, None)
        _save_pending(pending)
        return f"[skill_builder] Skill file for '{name}' not found — removed from pending."

    try:
        mod = _import_module(name, path)
        from tools import registry
        registry.register(name, mod)
    except Exception as e:
        return f"[skill_builder] Skill '{name}' failed to load: {e}"

    # Remove from pending
    pending.pop(name, None)
    _save_pending(pending)

    return f"Skill '{name}' APPROVED and activated. You can now use tool='{name}'."


def _reject(args: dict) -> str:
    """User rejects a pending skill → delete the file."""
    name = str(args.get('name', '')).strip().lower()
    if not name:
        return "[skill_builder] 'name' is required."

    pending = _load_pending()
    if name not in pending:
        return f"[skill_builder] '{name}' is not in the pending queue."

    path = _skill_path(name)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

    pending.pop(name, None)
    _save_pending(pending)
    return f"Skill '{name}' REJECTED and deleted."


def _create(args: dict) -> str:
    """Backward-compatible alias: 'create' now routes through the approval gate."""
    return _propose(args)


def _list(args: dict) -> str:
    _ensure_dir()
    files = sorted(
        f for f in os.listdir(SKILLS_DIR)
        if f.endswith('.py') and f != '__init__.py'
    )
    if not files:
        return "No skills yet. Use action='propose' to teach a new one."

    pending = _load_pending()
    lines = [f"Skills ({len(files)}):", '─' * 50]
    for fname in files:
        name = fname[:-3]
        desc = _doc_summary(_skill_path(name))
        status = "PENDING" if name in pending else "ACTIVE"
        lines.append(f"  [{status:7s}] {name:<20}  {desc}")

    if pending:
        lines.append(f"\nPending skills need approval: !skill approve <name>")

    return '\n'.join(lines)


def _inspect(args: dict) -> str:
    name = str(args.get('name', '')).strip()
    if not name:
        return "[skill_builder] 'name' is required."
    path = _skill_path(name)
    if not os.path.exists(path):
        return f"[skill_builder] Skill '{name}' not found."
    pending = _load_pending()
    status = "PENDING" if name in pending else "ACTIVE"
    with open(path, 'r', encoding='utf-8') as f:
        return f"=== {name}.py [{status}] ===\n{f.read()}"


def _delete(args: dict) -> str:
    name = str(args.get('name', '')).strip()
    if not name:
        return "[skill_builder] 'name' is required."
    path = _skill_path(name)
    if not os.path.exists(path):
        return f"[skill_builder] Skill '{name}' not found."
    try:
        os.remove(path)
        from tools import registry
        registry.unregister(name)
        # Also clean from pending if present
        pending = _load_pending()
        if name in pending:
            pending.pop(name)
            _save_pending(pending)
        return f"Skill '{name}' deleted and unregistered."
    except Exception as e:
        return f"[skill_builder] Error: {e}"


def _reload(args: dict) -> str:
    """Reload all APPROVED skills from disk (skip pending ones)."""
    _ensure_dir()
    from tools import registry
    pending = _load_pending()
    files = sorted(
        f for f in os.listdir(SKILLS_DIR)
        if f.endswith('.py') and f != '__init__.py'
    )
    loaded, skipped, failed = [], [], []
    for fname in files:
        name = fname[:-3]
        if name in pending:
            skipped.append(name)
            continue
        path = _skill_path(name)
        try:
            mod = _import_module(name, path)
            registry.register(name, mod)
            loaded.append(name)
        except Exception as e:
            failed.append(f"{name}: {e}")

    result = f"Reloaded {len(loaded)} skill(s): {loaded or 'none'}"
    if skipped:
        result += f"\nSkipped (pending approval): {skipped}"
    if failed:
        result += f"\nFailed: {failed}"
    return result


# ── Dispatcher ────────────────────────────────────────────────────────────────

_ACTIONS = {
    'propose': _propose,
    'create':  _create,   # backward compat — now goes through approval gate
    'list':    _list,
    'inspect': _inspect,
    'delete':  _delete,
    'reload':  _reload,
    'approve': _approve,
    'reject':  _reject,
}


def run_tool(args: dict = None) -> str:
    if args is None:
        args = {}
    action = str(args.get('action', 'list')).lower()
    fn = _ACTIONS.get(action)
    if fn is None:
        return (
            f"[skill_builder] Unknown action '{action}'. "
            f"Available: {list(_ACTIONS.keys())}"
        )
    return fn(args)
