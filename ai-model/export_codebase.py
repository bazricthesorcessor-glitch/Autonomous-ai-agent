"""
export_codebase.py
------------------
Generates 10 split codebase files under /home/dmannu/divyansh/:

  codebase_01_core.txt           — core/ (Flask API, agent loop, brain, state, config)
  codebase_02_engines.txt        — engines/ (memory, facts, tasks, goals, summarizer, janitor)
  codebase_03_tool_infra.txt     — tool infrastructure (registry, files, screenshot, diag, terminal, utils, code)
  codebase_04_computer.txt       — computer control (computer_use, ui_parser, screen_map, actions, window_mgr, browser_control)
  codebase_05_web_tools.txt      — tools/web/ + tools/pdf.py
  codebase_06_google_tools.txt   — tools/google/ (Drive, Calendar, Classroom, Gmail)
  codebase_07_personality.txt    — personality/ (loader + persona prompts)
  codebase_08_whatsapp.txt       — whatsapp-ai-bot/ (Node.js bridge)
  codebase_09_ui.txt             — ui/ (Vanilla JS frontend, auto-scanned)
  codebase_10_skills_helpers.txt — tools/skills/ + helpers/ + skill_builder + legacy/

Usage:
    cd /home/dmannu/divyansh/ai-model
    python export_codebase.py

Run this after EVERY coding session so ChatGPT / Claude always gets fresh code.
Pass one of the 10 files depending on which part you need to discuss.
"""

import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))   # ai-model/
ROOT = os.path.dirname(BASE)                         # divyansh/

# ── Output paths ──────────────────────────────────────────────────────────────
OUT = {
    1:  os.path.join(ROOT, "codebase_01_core.txt"),
    2:  os.path.join(ROOT, "codebase_02_engines.txt"),
    3:  os.path.join(ROOT, "codebase_03_tool_infra.txt"),
    4:  os.path.join(ROOT, "codebase_04_computer.txt"),
    5:  os.path.join(ROOT, "codebase_05_web_tools.txt"),
    6:  os.path.join(ROOT, "codebase_06_google_tools.txt"),
    7:  os.path.join(ROOT, "codebase_07_personality.txt"),
    8:  os.path.join(ROOT, "codebase_08_whatsapp.txt"),
    9:  os.path.join(ROOT, "codebase_09_ui.txt"),
    10: os.path.join(ROOT, "codebase_10_skills_helpers.txt"),
}

# ── Shared header info ────────────────────────────────────────────────────────
ARCHITECTURE = """
ARCHITECTURE:
  User (Browser)
      |
  [ui/index.html]  <-- standalone dark-theme control panel (served at /app)
      | fetch() via api.js
      |
  User (WhatsApp)
      |
  [whatsapp-ai-bot/server.js  :3000]  <-- index.html (Web Setup UI)
      | axios POST /chat
      |
  [ai-model/core/api_server.py  :8000]  <-- main.py entry
      |
      +-- core/agent_loop.py        (2-tier fast path + plan-tool-respond loop)
      +-- core/brain.py             (model routing + fallback)
      +-- core/context_builder.py   (memory assembly, raw log truncation, screen cache)
      +-- core/state.py             (agentic state machine)
      +-- core/system_shortcuts.py  (Hyprland shortcuts for planner awareness)
      +-- core/autonomous_mode.py   (global flag — enable/disable background tasks)
      +-- engines/fact_engine.py    (structured facts — extracted BEFORE context build)
      +-- engines/task_manager.py   (multi-task persistent tracking)
      +-- engines/memory_engine.py  (vector search + add_memory)
      +-- engines/janitor.py        (maintenance / summarizer trigger)
      +-- engines/summarizer.py     (log summarization)
      +-- engines/goal_scheduler.py (daemon thread — fires scheduled goals silently)
      +-- engines/todo_manager.py   (CRUD for memory/todos.json)
      +-- tools/registry.py         (tool loader + safe/risky gate + TOOL CATEGORIES)
      +-- tools/files.py
      +-- tools/screenshot.py       (active-window OCR, noise-filtered, writes screen_cache)
      +-- tools/system_diagnostics.py
      +-- tools/actions.py          (ydotool mouse/keyboard — individual low-level moves)
      +-- tools/computer_use.py     (scan_screen, click_map, smart_click, type_into, open_url)
      +-- tools/ui_parser.py        (YOLO UI detection + targeted OCR — replaces OCR-only)
      +-- tools/screen_map.py       (structured element map: OCR fallback pipeline)
      +-- tools/browser_control.py  (Playwright DOM-based web automation — Layer 1)
      +-- tools/ui_positions.json   (pre-saved pixel positions per site/app)
      +-- tools/window_manager.py   (hyprctl window/app control)
      +-- tools/terminal_safe.py    (allowlisted safe shell execution)
      +-- tools/todos.py            (agent tool — create/update/list/clear todos)
      +-- tools/utilities.py        (flip_coin, roll_dice, time_now, convert_units, etc.)
      +-- tools/skill_builder.py    (AI skill creation with USER APPROVAL GATE)
      +-- tools/code.py             (sandboxed Python exec/eval — restricted builtins)
      +-- tools/skills/             (AI-created skill files, auto-loaded on startup)
      +-- tools/web/                (web tools package)
      |     __init__.py, http_client.py, browser.py, search.py, fetch.py, wikipedia.py, inspect.py
      +-- tools/pdf.py              (PDF read, info, topics, page extraction, keyword search)
      +-- tools/google/             (Google Apps package — OAuth2)
      |     __init__.py, auth.py, drive.py, calendar.py, classroom.py, gmail.py
      +-- personality/              (persona prompts: default, coding, teacher, assistant)
      +-- memory/                   (tasks.json, facts.json, todos.json, identity.json, goals.json, etc.)
      +-- helpers/                  (start.sh, stop.sh, status.sh, engineering_brief.py)
      +-- models/                   (UI detection model: ui_detect.pt)

  API:  /chat  /health  /tasks  /status  /logs  /persona  /screen
        /autonomous  /todos  /todos/<id>  /todos/clear-done  /tool-feed
        /debug-screen  /ui-parse  /skills  /skills/<name>/approve|reject
  UI:   http://localhost:8000/app  (new full control panel)
        http://localhost:8000/ui   (legacy inline text console)
  Principles:
    - UI communicates only through HTTP — never imports AI code directly
    - CORS enabled so ui/ can also be opened as a plain file://
    - Skills require user approval before activation
    - UI parser uses YOLO detection when model available, OCR fallback otherwise
"""

# ── File lists per part ──────────────────────────────────────────────────────

# Part 1: Core
CORE_FILES = [
    ("ai-model/main.py",                        "ai-model/main.py",                        "entry point"),
    ("ai-model/config.py",                      "ai-model/config.py",                      "central config"),
    ("ai-model/config/system_config.json",      "ai-model/config/system_config.json",      "runtime config"),
    ("ai-model/structure_setup.py",             "ai-model/structure_setup.py",             "first-run scaffolding"),
    ("ai-model/core/__init__.py",               "ai-model/core/__init__.py",               ""),
    ("ai-model/core/api_server.py",             "ai-model/core/api_server.py",             "Flask API + all endpoints"),
    ("ai-model/core/brain.py",                  "ai-model/core/brain.py",                  "LLM wrapper + model fallback"),
    ("ai-model/core/agent_loop.py",             "ai-model/core/agent_loop.py",             "2-tier fast path + plan-tool-respond"),
    ("ai-model/core/state.py",                  "ai-model/core/state.py",                  "agentic state machine"),
    ("ai-model/core/context_builder.py",        "ai-model/core/context_builder.py",        "memory context assembly"),
    ("ai-model/core/autonomous_mode.py",        "ai-model/core/autonomous_mode.py",        "autonomous flag"),
    ("ai-model/core/system_shortcuts.py",       "ai-model/core/system_shortcuts.py",       "Hyprland shortcuts"),
]

# Part 2: Engines
ENGINE_FILES = [
    ("ai-model/engines/__init__.py",            "ai-model/engines/__init__.py",            ""),
    ("ai-model/engines/fact_engine.py",         "ai-model/engines/fact_engine.py",         "structured fact extraction"),
    ("ai-model/engines/task_manager.py",        "ai-model/engines/task_manager.py",        "multi-step task tracking"),
    ("ai-model/engines/memory_engine.py",       "ai-model/engines/memory_engine.py",       "vector store + cosine search"),
    ("ai-model/engines/janitor.py",             "ai-model/engines/janitor.py",             "maintenance + summarizer trigger"),
    ("ai-model/engines/summarizer.py",          "ai-model/engines/summarizer.py",          "LLM-based log summarization"),
    ("ai-model/engines/goal_scheduler.py",      "ai-model/engines/goal_scheduler.py",      "background daemon for goals"),
    ("ai-model/engines/todo_manager.py",        "ai-model/engines/todo_manager.py",        "todo CRUD"),
]

# Part 3: Tool Infrastructure
TOOL_INFRA_FILES = [
    ("ai-model/tools/__init__.py",              "ai-model/tools/__init__.py",              ""),
    ("ai-model/tools/registry.py",              "ai-model/tools/registry.py",              "tool loader + categories + dispatch"),
    ("ai-model/tools/_template.py",             "ai-model/tools/_template.py",             "template for new tools"),
    ("ai-model/tools/files.py",                 "ai-model/tools/files.py",                 "file CRUD"),
    ("ai-model/tools/screenshot.py",            "ai-model/tools/screenshot.py",            "active-window OCR + noise filter"),
    ("ai-model/tools/system_diagnostics.py",    "ai-model/tools/system_diagnostics.py",    "CPU/RAM/disk/network"),
    ("ai-model/tools/terminal_safe.py",         "ai-model/tools/terminal_safe.py",         "allowlisted shell commands"),
    ("ai-model/tools/todos.py",                 "ai-model/tools/todos.py",                 "agent-facing todo CRUD"),
    ("ai-model/tools/utilities.py",             "ai-model/tools/utilities.py",             "coin flip, dice, time, conversions"),
    ("ai-model/tools/code.py",                  "ai-model/tools/code.py",                  "sandboxed Python exec/eval"),
]

# Part 4: Computer Control (the perception + action stack)
COMPUTER_FILES = [
    ("ai-model/tools/computer_use.py",          "ai-model/tools/computer_use.py",          "high-level: smart_click, type_into, scan_screen"),
    ("ai-model/tools/ui_parser.py",             "ai-model/tools/ui_parser.py",             "YOLO UI detection + targeted OCR"),
    ("ai-model/tools/screen_map.py",            "ai-model/tools/screen_map.py",            "OCR-only fallback element map"),
    ("ai-model/tools/actions.py",               "ai-model/tools/actions.py",               "low-level ydotool mouse/keyboard"),
    ("ai-model/tools/window_manager.py",        "ai-model/tools/window_manager.py",        "hyprctl window control"),
    ("ai-model/tools/browser_control.py",       "ai-model/tools/browser_control.py",       "Playwright DOM-based web automation"),
    ("ai-model/tools/ui_positions.json",        "ai-model/tools/ui_positions.json",        "pre-saved pixel positions"),
]

# Part 5: Web Tools
WEB_TOOL_FILES = [
    ("ai-model/tools/web/__init__.py",          "ai-model/tools/web/__init__.py",          "dispatcher"),
    ("ai-model/tools/web/http_client.py",       "ai-model/tools/web/http_client.py",       "SSL-aware HTTP + html_to_text"),
    ("ai-model/tools/web/browser.py",           "ai-model/tools/web/browser.py",           "open_browser"),
    ("ai-model/tools/web/search.py",            "ai-model/tools/web/search.py",            "DuckDuckGo + Lite fallback"),
    ("ai-model/tools/web/fetch.py",             "ai-model/tools/web/fetch.py",             "fetch_page, scrape_page"),
    ("ai-model/tools/web/wikipedia.py",         "ai-model/tools/web/wikipedia.py",         "wikipedia lookup"),
    ("ai-model/tools/web/inspect.py",           "ai-model/tools/web/inspect.py",           "inspect_page, find_forms, etc."),
    ("ai-model/tools/pdf.py",                   "ai-model/tools/pdf.py",                   "PDF read/analyse"),
]

# Part 6: Google Tools
GOOGLE_TOOL_FILES = [
    ("ai-model/tools/google/__init__.py",       "ai-model/tools/google/__init__.py",       "dispatcher"),
    ("ai-model/tools/google/auth.py",           "ai-model/tools/google/auth.py",           "OAuth2 / build_service"),
    ("ai-model/tools/google/drive.py",          "ai-model/tools/google/drive.py",          "Drive actions"),
    ("ai-model/tools/google/calendar.py",       "ai-model/tools/google/calendar.py",       "Calendar actions"),
    ("ai-model/tools/google/classroom.py",      "ai-model/tools/google/classroom.py",      "Classroom actions"),
    ("ai-model/tools/google/gmail.py",          "ai-model/tools/google/gmail.py",          "Gmail: list, read, send, search"),
]

# Part 7: Personality
PERSONALITY_FILES = [
    ("ai-model/personality/__init__.py",        "ai-model/personality/__init__.py",        ""),
    ("ai-model/personality/loader.py",          "ai-model/personality/loader.py",          "keyword-based mode detection"),
    ("ai-model/personality/default.txt",        "ai-model/personality/default.txt",        "default persona"),
    ("ai-model/personality/coding.txt",         "ai-model/personality/coding.txt",         "coding persona"),
    ("ai-model/personality/teacher.txt",        "ai-model/personality/teacher.txt",        "teacher persona"),
    ("ai-model/personality/assistant.txt",      "ai-model/personality/assistant.txt",      "task assistant persona"),
]

# Part 8: WhatsApp
WHATSAPP_FILES = [
    ("whatsapp-ai-bot/server.js",               "whatsapp-ai-bot/server.js",               "Baileys client + Express"),
    ("whatsapp-ai-bot/index.html",              "whatsapp-ai-bot/index.html",              "QR login UI"),
    ("whatsapp-ai-bot/package.json",            "whatsapp-ai-bot/package.json",            ""),
]

# Part 9: Frontend UI — auto-scanned
# Part 10: Skills + Helpers + Legacy — skills auto-scanned, helpers auto-scanned

SKILL_BUILDER_FILES = [
    ("ai-model/tools/skill_builder.py",         "ai-model/tools/skill_builder.py",         "AI skill creation + approval gate"),
    ("ai-model/tools/skills/__init__.py",       "ai-model/tools/skills/__init__.py",       "skills package"),
]

LEGACY_FILES = [
    ("ai-model/legacy/router.py",              "ai-model/legacy/router.py",               "LEGACY — old monolithic router"),
    ("ai-model/legacy/ai_agent.py",            "ai-model/legacy/ai_agent.py",             "LEGACY — old summarizer agent"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

SEP = "=" * 80

_TEXT_EXTS = {'.py', '.js', '.json', '.txt', '.md', '.html', '.css', '.ts', '.sh', '.env'}


def _scan_dir(directory: str, root: str) -> list:
    """Auto-discover all text files under `directory`, returning (label, rel_path, note) tuples."""
    results = []
    if not os.path.isdir(directory):
        return results
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith('.') and d != '__pycache__')
        for filename in sorted(filenames):
            if filename.startswith('.'):
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext not in _TEXT_EXTS:
                continue
            full = os.path.join(dirpath, filename)
            rel  = os.path.relpath(full, root)
            results.append((rel, rel, ""))
    return results


def _write_part(out_path: str, part_title: str, section_label: str,
                file_list: list, root: str, now: str) -> tuple:
    """Write one codebase split file. Returns (ok_count, missing_list)."""
    lines = []
    lines.append(SEP)
    lines.append("PROJECT: AVRIL — Personal Advanced AI Assistant")
    lines.append(f"PART: {part_title}")
    lines.append(SEP)
    lines.append(f"Owner / Pen name: Divyansh (Bazric)")
    lines.append(f"AI Name: Avril (Satomi)")
    lines.append(f"Stack: Python (Flask + Ollama) backend | Node.js (Baileys) WhatsApp bot | Vanilla JS UI")
    lines.append(f"Exported: {now}")
    lines.append(f"Section: {section_label}")
    lines.append(SEP)
    lines.append(ARCHITECTURE)

    ok = 0
    missing = []

    for label, rel_path, note in file_list:
        full_path = os.path.join(root, rel_path)
        header_note = f"  [{note}]" if note else ""
        lines.append(SEP)
        lines.append(f"FILE: {label}{header_note}")
        lines.append(SEP)
        if os.path.exists(full_path):
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                lines.append(f.read())
            ok += 1
        else:
            lines.append(f"[FILE NOT FOUND: {full_path}]")
            missing.append(rel_path)

    lines.append(SEP)
    lines.append(f"END OF {part_title}")
    lines.append(SEP)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return ok, missing


def build_export():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts = []

    # Part 1: Core
    ok, miss = _write_part(
        OUT[1], "1/10 — Core (core/)",
        "Flask API, agent loop (2-tier fast path), brain, state, config",
        CORE_FILES, ROOT, now
    )
    parts.append(("core", ok, len(CORE_FILES), miss))

    # Part 2: Engines
    ok, miss = _write_part(
        OUT[2], "2/10 — Engines (engines/)",
        "Memory, facts, tasks, goals, summarizer, janitor, todos",
        ENGINE_FILES, ROOT, now
    )
    parts.append(("engines", ok, len(ENGINE_FILES), miss))

    # Part 3: Tool Infrastructure
    ok, miss = _write_part(
        OUT[3], "3/10 — Tool Infrastructure",
        "Registry (categories), files, screenshot, diagnostics, terminal, utils, code",
        TOOL_INFRA_FILES, ROOT, now
    )
    parts.append(("tool-infra", ok, len(TOOL_INFRA_FILES), miss))

    # Part 4: Computer Control
    ok, miss = _write_part(
        OUT[4], "4/10 — Computer Control (perception + action)",
        "computer_use (smart_click, type_into), ui_parser (YOLO), screen_map (OCR), actions, window_mgr, browser_control",
        COMPUTER_FILES, ROOT, now
    )
    parts.append(("computer", ok, len(COMPUTER_FILES), miss))

    # Part 5: Web Tools
    ok, miss = _write_part(
        OUT[5], "5/10 — Web Tools (tools/web/ + pdf)",
        "Web package: browser, DuckDuckGo search, fetch/scrape, Wikipedia; PDF reader",
        WEB_TOOL_FILES, ROOT, now
    )
    parts.append(("web-tools", ok, len(WEB_TOOL_FILES), miss))

    # Part 6: Google Tools
    ok, miss = _write_part(
        OUT[6], "6/10 — Google Tools (tools/google/)",
        "Google Apps package: OAuth2, Drive, Calendar, Classroom, Gmail",
        GOOGLE_TOOL_FILES, ROOT, now
    )
    parts.append(("google", ok, len(GOOGLE_TOOL_FILES), miss))

    # Part 7: Personality
    ok, miss = _write_part(
        OUT[7], "7/10 — Personality (personality/)",
        "Keyword-based persona detection + prompt templates (default, coding, teacher, assistant)",
        PERSONALITY_FILES, ROOT, now
    )
    parts.append(("personality", ok, len(PERSONALITY_FILES), miss))

    # Part 8: WhatsApp
    ok, miss = _write_part(
        OUT[8], "8/10 — WhatsApp Bridge (whatsapp-ai-bot/)",
        "Node.js Baileys bridge: server.js, setup UI, package.json",
        WHATSAPP_FILES, ROOT, now
    )
    parts.append(("whatsapp", ok, len(WHATSAPP_FILES), miss))

    # Part 9: Frontend UI (auto-scanned)
    ui_dir   = os.path.join(ROOT, 'ui')
    ui_files = _scan_dir(ui_dir, ROOT)
    ok, miss = _write_part(
        OUT[9], "9/10 — Frontend UI (ui/)",
        "Vanilla JS control panel: index.html, css/style.css, js/api.js, chat.js, settings.js, sidebar.js",
        ui_files, ROOT, now
    )
    parts.append(("ui", ok, len(ui_files), miss))

    # Part 10: Skills + Helpers + Legacy (skills and helpers auto-scanned)
    skills_dir   = os.path.join(BASE, 'tools', 'skills')
    helpers_dir  = os.path.join(BASE, 'helpers')
    skills_auto  = _scan_dir(skills_dir, ROOT)
    helpers_auto = _scan_dir(helpers_dir, ROOT)
    combined = SKILL_BUILDER_FILES + skills_auto + helpers_auto + LEGACY_FILES
    ok, miss = _write_part(
        OUT[10], "10/10 — Skills + Helpers + Legacy",
        "skill_builder (approval gate), AI-learned skills, launcher scripts, engineering brief, legacy code",
        combined, ROOT, now
    )
    parts.append(("skills+helpers", ok, len(combined), miss))

    # Summary
    print()
    total_ok = 0
    total_files = 0
    for name, ok, count, miss in parts:
        total_ok += ok
        total_files += count
        idx = parts.index((name, ok, count, miss)) + 1
        status = f"{ok}/{count} files"
        print(f"  Part {idx:2d}  {name:<16s}  {status}")
        if miss:
            print(f"           WARNING missing: {miss}")

    print(f"\n  Total: {total_ok}/{total_files} files across 10 parts.")
    print(f"  Output: {os.path.dirname(OUT[1])}/codebase_*.txt")


if __name__ == "__main__":
    build_export()
