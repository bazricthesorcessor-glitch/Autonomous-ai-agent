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

import ast
import hashlib
import os
import re
import shutil
import sys
import json
import importlib.util
from datetime import datetime

SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'skills')
_PENDING_META = os.path.join(SKILLS_DIR, '_pending.json')

# Patterns that must NEVER appear in AI-generated skill code
_DANGEROUS_PATTERNS = re.compile(
    # Process / shell execution
    r'subprocess|os\.system|os\.popen|os\.exec|os\.spawn'
    # Code injection
    r'|__import__|eval\s*\(|exec\s*\(|compile\s*\('
    # All file I/O — skills must use registry tools (file_search etc.) not raw open()
    r'|open\s*\('
    # File operations
    r'|os\.remove|os\.unlink|os\.rename|os\.replace'
    r'|os\.makedirs|os\.mkdir|os\.rmdir'
    # Dangerous modules (full module block)
    r'|shutil\b|pathlib\b|tempfile\b'
    # Network / exfiltration
    r'|requests\b|urllib\b|httpx\b|aiohttp\b'
    r'|socket\.socket|http\.server|smtplib'
    # Low-level / FFI
    r'|ctypes\b|cffi\b|importlib\.import_module'
    # Encoding tricks to bypass detection
    r'|base64\.b64decode|codecs\.decode',
    re.IGNORECASE,
)

# Modules that skills are never allowed to import (checked at AST level)
_BLOCKED_IMPORTS = frozenset({
    'subprocess', 'socket', 'requests', 'urllib', 'httpx', 'aiohttp',
    'ctypes', 'cffi', 'shutil', 'tempfile', 'pathlib',
    'ftplib', 'telnetlib', 'smtplib', 'poplib', 'imaplib',
    'multiprocessing', 'threading', 'concurrent',
})

# Function/method names that skills are never allowed to call (checked at AST level)
_BLOCKED_CALLS = frozenset({
    'eval', 'exec', 'compile', '__import__',
    'system', 'popen', 'spawn', 'execv', 'execve',   # os.*
    'remove', 'unlink', 'rmdir', 'makedirs', 'mkdir', # os.*
    'rename', 'replace',                               # os.*
    'open',                                            # builtin
})


def _ast_scan(code: str) -> str | None:
    """
    AST-level scan for dangerous patterns that bypass regex (indirect calls,
    attribute access, dynamic imports).

    Returns a description of the violation, or None if the code is clean.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"Syntax error: {e}"

    for node in ast.walk(tree):
        # Direct name calls: eval(), exec(), open(), __import__()
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in _BLOCKED_CALLS:
                    return f"Forbidden call: {node.func.id}()"
            # Attribute calls: os.system(), os.open(), etc.
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in _BLOCKED_CALLS:
                    return f"Forbidden attribute call: .{node.func.attr}()"
            # getattr(os, "system") pattern — catches dynamic attribute access
            if isinstance(node.func, ast.Name) and node.func.id == 'getattr':
                if node.args and isinstance(node.args[-1], ast.Constant):
                    if node.args[-1].value in _BLOCKED_CALLS:
                        return f"Forbidden getattr() call to: .{node.args[-1].value}"

        # Import statements: import subprocess, from socket import ...
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = (alias.name or '').split('.')[0]
                if root in _BLOCKED_IMPORTS:
                    return f"Forbidden import: {alias.name}"
        if isinstance(node, ast.ImportFrom):
            root = (node.module or '').split('.')[0]
            if root in _BLOCKED_IMPORTS:
                return f"Forbidden import from: {node.module}"

    return None

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

    # Safety scan — Phase 1: regex (fast, catches literal patterns)
    match = _DANGEROUS_PATTERNS.search(code)
    if match:
        return (
            f"[skill_builder] BLOCKED: code contains forbidden pattern '{match.group()}'. "
            "Skills cannot use subprocess, eval, exec, os.system, sockets, file I/O, etc."
        )

    # Safety scan — Phase 2: AST (catches indirect calls, dynamic imports)
    ast_violation = _ast_scan(code)
    if ast_violation:
        return (
            f"[skill_builder] BLOCKED (AST): {ast_violation}. "
            "Skills must not use forbidden functions even via getattr or dynamic access."
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
    prev_version = pending.get(name, {}).get('version', 0)
    pending[name] = {
        'purpose':     purpose,
        'proposed_at': datetime.now().isoformat(),
        'file':        path,
        'version':     prev_version + 1,
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

    # Save a versioned backup of the approved code (.bak) so broken re-proposals
    # can be rolled back by copying the most recent .bak back to {name}.py.
    try:
        with open(path, encoding='utf-8') as _f:
            _code_bytes = _f.read().encode()
        _hash = hashlib.md5(_code_bytes).hexdigest()[:8]
        _version = pending.get(name, {}).get('version', 1)
        _bak_path = os.path.join(SKILLS_DIR, f"{name}.v{_version}_{_hash}.bak")
        shutil.copy2(path, _bak_path)
        # Keep only the 3 most recent backups for this skill
        _all_baks = sorted(
            f for f in os.listdir(SKILLS_DIR)
            if f.startswith(f"{name}.v") and f.endswith('.bak')
        )
        for _old in _all_baks[:-3]:
            try:
                os.remove(os.path.join(SKILLS_DIR, _old))
            except OSError:
                pass
    except Exception:
        pass  # backup failure is non-fatal — skill is still activated

    # Remove from pending
    _version = pending.pop(name, {}).get('version', 1)
    _save_pending(pending)

    return (
        f"Skill '{name}' APPROVED and activated. You can now use tool='{name}'.\n"
        f"Backup saved as v{_version}. To roll back: copy the .bak file back to {name}.py and reload."
    )


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
