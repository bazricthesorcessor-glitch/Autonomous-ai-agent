# ========================= tools/registry.py =========================
"""
Central tool dispatcher.
Maps tool name strings to run_tool() functions.
Handles safe/risky permission checks via system_config.json.

Tools are organized into CATEGORIES for better planner reasoning:
the planner sees grouped tools instead of a flat list, so it can
first pick a category then pick the right tool inside it.
"""
import os
import sys
import json
import importlib.util

# Load safe_tools list from system_config.json
_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config', 'system_config.json')
try:
    with open(_config_path, 'r') as _f:
        _sys_config = json.load(_f)
    SAFE_TOOLS = set(_sys_config.get('permissions', {}).get('safe_tools', []))
except Exception:
    SAFE_TOOLS = {'system_diagnostics', 'file_search', 'screenshot'}

# Lazy-loaded registry: {tool_name: module}
_REGISTRY = {}

# Path to AI-learned skill files
_SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'skills')

# ── Tool categories ──────────────────────────────────────────────────────────
TOOL_CATEGORIES = {
    "web_tools": {
        "label": "Web & Browser",
        "desc":  "Search the web, fetch pages, browse websites",
        "tools": ["web", "browser_control"],
    },
    "perception_tools": {
        "label": "Perception & Vision",
        "desc":  "Read screen, locate UI elements, monitor output via MAI-UI",
        "tools": ["vision", "screenshot"],
    },
    "computer_tools": {
        "label": "Desktop & Computer Control",
        "desc":  "Screen automation, mouse/keyboard, window management, screenshots",
        "tools": ["computer_use", "executor", "actions", "window_manager"],
    },
    "filesystem_tools": {
        "label": "Files & Code",
        "desc":  "Read/write files, run safe commands, execute Python, PDF reading",
        "tools": ["file_search", "terminal_safe", "code", "pdf"],
    },
    "google_tools": {
        "label": "Google Apps",
        "desc":  "Drive, Calendar, Classroom, Gmail via OAuth",
        "tools": ["google"],
    },
    "info_tools": {
        "label": "Information & Utilities",
        "desc":  "System diagnostics, todos, utilities, coin flip, time, remember, daily log",
        "tools": ["system_diagnostics", "todos", "utilities", "remember", "daily_log", "cloud_ai", "system_state"],
    },
    "skill_tools": {
        "label": "Skills & Learning",
        "desc":  "Create, manage, and use learned AI skills",
        "tools": ["skill_builder"],
    },
}


def _load():
    global _REGISTRY
    if _REGISTRY:
        return

    from tools import system_diagnostics, files, screenshot, window_manager, terminal_safe, todos, utilities, pdf
    from tools import code           # sandboxed Python code execution
    from tools import web            # tools/web/ package (browser, search, fetch, wikipedia)
    from tools import google         # tools/google/ package (drive, calendar, classroom)
    from tools import computer_use   # MAI-UI screen interaction
    from tools import browser_control  # lightweight browser stub
    from tools import vision         # MAI-UI structured perception
    from tools import executor       # atomic GUI action executor
    _REGISTRY = {
        'system_diagnostics': system_diagnostics,
        'file_search':        files,
        'screenshot':         screenshot,
        'window_manager':     window_manager,
        'terminal_safe':      terminal_safe,
        'todos':              todos,
        'utilities':          utilities,
        'web':                web,
        'pdf':                pdf,
        'google':             google,
        'computer_use':       computer_use,
        'browser_control':    browser_control,
        'code':               code,
        'vision':             vision,
        'executor':           executor,
    }

    # Optional: load actions tool if ydotool is available
    try:
        from tools import actions
        _REGISTRY['actions'] = actions
    except ImportError:
        pass

    # Skill builder — lets the AI create/manage learned skills
    from tools import skill_builder
    _REGISTRY['skill_builder'] = skill_builder

    # Remember tool — explicit zero-hallucination memory store
    from tools import remember
    _REGISTRY['remember'] = remember

    # Daily log — structured homework/checkin tracker for each day
    from tools import daily_log
    _REGISTRY['daily_log'] = daily_log

    # Cloud AI — asks Claude.ai / ChatGPT / Gemini via browser automation
    from tools import cloud_ai
    _REGISTRY['cloud_ai'] = cloud_ai

    # System state — live window/media/audio snapshot via MPRIS + hyprctl + pactl
    from tools import system_state
    _REGISTRY['system_state'] = system_state

    # Auto-load any skills the AI has already created
    _load_skills()


def _load_skills():
    """Auto-import every .py file in tools/skills/ into the registry."""
    if not os.path.isdir(_SKILLS_DIR):
        return
    for fname in sorted(os.listdir(_SKILLS_DIR)):
        if not fname.endswith('.py') or fname == '__init__.py':
            continue
        name = fname[:-3]
        path = os.path.join(_SKILLS_DIR, fname)
        try:
            spec = importlib.util.spec_from_file_location(f"tools.skills.{name}", path)
            mod  = importlib.util.module_from_spec(spec)
            sys.modules[f"tools.skills.{name}"] = mod
            spec.loader.exec_module(mod)
            _REGISTRY[name] = mod
        except Exception:
            pass  # bad skill file — skip silently, don't crash the registry


def register(name: str, module) -> None:
    """Hot-register a module under the given tool name (used by skill_builder)."""
    _REGISTRY[name] = module


def unregister(name: str) -> None:
    """Remove a tool from the live registry (used by skill_builder on delete)."""
    _REGISTRY.pop(name, None)


def is_safe(tool_name: str) -> bool:
    """Returns True if the tool is in the safe_tools whitelist."""
    return tool_name in SAFE_TOOLS


def run(tool_name: str, args: dict = None) -> str:
    """Dispatch a tool call by name. Returns result string."""
    _load()
    if args is None:
        args = {}

    if tool_name not in _REGISTRY:
        return f"[Registry] Unknown tool: '{tool_name}'. Available: {list_tools()}"

    try:
        return _REGISTRY[tool_name].run_tool(args)
    except Exception as e:
        return f"[Registry] Error running '{tool_name}': {str(e)}"


def list_tools() -> list:
    """Returns list of registered tool names."""
    _load()
    return list(_REGISTRY.keys())


def _tool_desc(name: str, mod) -> str:
    """Build a single-line description for one tool."""
    tag = "safe" if is_safe(name) else "risky"
    desc = ""
    if mod.__doc__:
        for line in mod.__doc__.strip().splitlines():
            line = line.strip()
            if line:
                desc = f" — {line}"
                break
    return f"    {name} [{tag}]{desc}"


def describe_tools() -> str:
    """Returns a categorized listing of tools for the planner prompt."""
    _load()

    categorized = set()
    for cat_info in TOOL_CATEGORIES.values():
        categorized.update(cat_info["tools"])

    lines = []
    for cat_key, cat_info in TOOL_CATEGORIES.items():
        cat_tools = [n for n in cat_info["tools"] if n in _REGISTRY]
        if not cat_tools:
            continue
        lines.append(f"  [{cat_info['label']}] {cat_info['desc']}")
        for name in cat_tools:
            lines.append(_tool_desc(name, _REGISTRY[name]))

    other = [n for n in _REGISTRY if n not in categorized]
    if other:
        lines.append("  [Other / Learned Skills]")
        for name in other:
            lines.append(_tool_desc(name, _REGISTRY[name]))

    return "\n".join(lines)