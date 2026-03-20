"""
export_codebase.py
------------------
Generates a single comprehensive codebase file:

  /home/dmannu/divyansh/codebase_full.txt

Contains all 10 sections with clear delimiters inside one file:
  Section 1:  Core (Flask API, agent loop, brain, state, config)
  Section 2:  Engines (memory, facts, tasks, goals, summarizer, janitor)
  Section 3:  Tool Infrastructure (registry, files, screenshot, diag, terminal, utils, code)
  Section 4:  Computer Control (computer_use, ui_parser, screen_map, actions, window_mgr, browser_control)
  Section 5:  Web Tools (tools/web/ + pdf)
  Section 6:  Google Tools (tools/google/)
  Section 7:  Personality (loader + persona prompts)
  Section 8:  WhatsApp Bridge (server.js, setup UI)
  Section 9:  Frontend UI (auto-scanned)
  Section 10: Skills + Helpers + Legacy

Usage:
    cd /home/dmannu/divyansh/ai-model
    python export_codebase.py
"""

import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))   # ai-model/
ROOT = os.path.dirname(BASE)                         # divyansh/

OUT_FULL = os.path.join(ROOT, "codebase_full.txt")

# ── Architecture header ──────────────────────────────────────────────────────
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
      +-- core/context_enricher.py  (live UserContext: exam proximity, strictness, schedule)
      +-- core/voice.py             (edge-tts TTS + mood-based prosody: normal/sad/crying/firm)
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
      +-- tools/system_state.py     (live snapshot: MPRIS + hyprctl + pactl — injected every turn)
      +-- tools/actions.py          (ydotool mouse/keyboard — individual low-level moves)
      +-- tools/computer_use.py     (scan_screen, click_map, smart_click, type_into, open_url)
      +-- tools/ui_parser.py        (YOLO UI detection + targeted OCR — replaces OCR-only)
      +-- tools/screen_map.py       (structured element map: OCR fallback pipeline)
      +-- tools/vision.py           (3-layer perception: DOM → AT-SPI → Qwen2-VL grid overlay)
      +-- tools/executor.py         (atomic GUI actions: CLICK/TYPE/SCROLL/PRESS/MOVE + volume/notify)
      +-- tools/browser_control.py  (Playwright DOM-based web automation — Layer 1)
      +-- tools/ui_positions.json   (pre-saved pixel positions per site/app)
      +-- tools/window_manager.py   (hyprctl window/app control)
      +-- tools/terminal_safe.py    (allowlisted safe shell execution)
      +-- tools/todos.py            (agent tool — create/update/list/clear todos)
      +-- tools/utilities.py        (flip_coin, roll_dice, time_now, convert_units, etc.)
      +-- tools/skill_builder.py    (AI skill creation — approval gate + regex+AST safety scanner + versioned .bak backups)
      +-- tools/remember.py         (zero-hallucination memory: reminders/shopping/errands)
      +-- tools/daily_log.py        (structured homework + checkin tracker per day)
      +-- tools/cloud_ai.py         (ask Claude/ChatGPT/Gemini via browser — no API key needed)
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

  API:  /chat  /health  /tasks  /status  /logs  /persona  /screen  /voice
        /autonomous  /todos  /todos/<id>  /todos/clear-done  /tool-feed
        /debug-screen  /ui-parse  /skills  /skills/<n>/approve|reject
  UI:   http://localhost:8000/app  (new full control panel)
        http://localhost:8000/ui   (legacy inline text console)
"""

# ── Sections: (title, description, file_list) ─────────────────────────────────

SECTIONS = [
    (
        "1/10 — Core",
        "Flask API, agent loop (2-tier fast path), brain, state, config",
        [
            ("ai-model/main.py",                   "entry point"),
            ("ai-model/config.py",                  "central config"),
            ("ai-model/config/system_config.json",  "runtime config"),
            ("ai-model/structure_setup.py",         "first-run scaffolding"),
            ("ai-model/core/__init__.py",           ""),
            ("ai-model/core/api_server.py",         "Flask API + all endpoints"),
            ("ai-model/core/brain.py",              "LLM wrapper + model fallback"),
            ("ai-model/core/agent_loop.py",         "2-tier fast path + plan-tool-respond"),
            ("ai-model/core/state.py",              "agentic state machine"),
            ("ai-model/core/context_builder.py",    "memory context assembly"),
            ("ai-model/core/context_enricher.py",   "live UserContext: exam/schedule/enrichment"),
            ("ai-model/core/voice.py",              "TTS: edge-tts + mood prosody"),
            ("ai-model/core/autonomous_mode.py",    "autonomous flag"),
            ("ai-model/core/system_shortcuts.py",   "Hyprland shortcuts"),
        ],
    ),
    (
        "2/10 — Engines",
        "Memory, facts, tasks, goals, summarizer, janitor, todos",
        [
            ("ai-model/engines/__init__.py",        ""),
            ("ai-model/engines/fact_engine.py",     "structured fact extraction"),
            ("ai-model/engines/task_manager.py",    "multi-step task tracking"),
            ("ai-model/engines/memory_engine.py",   "vector store + cosine search"),
            ("ai-model/engines/janitor.py",         "maintenance + summarizer trigger"),
            ("ai-model/engines/summarizer.py",      "LLM-based log summarization"),
            ("ai-model/engines/goal_scheduler.py",  "background daemon for goals"),
            ("ai-model/engines/todo_manager.py",    "todo CRUD"),
        ],
    ),
    (
        "3/10 — Tool Infrastructure",
        "Registry (categories), files, screenshot, diagnostics, system_state, terminal, utils, code",
        [
            ("ai-model/tools/__init__.py",          ""),
            ("ai-model/tools/registry.py",          "tool loader + categories + dispatch"),
            ("ai-model/tools/_template.py",         "template for new tools"),
            ("ai-model/tools/files.py",             "file CRUD"),
            ("ai-model/tools/screenshot.py",        "active-window OCR + noise filter"),
            ("ai-model/tools/system_diagnostics.py","CPU/RAM/disk/network"),
            ("ai-model/tools/system_state.py",      "live MPRIS+hyprctl+pactl snapshot — injected every turn"),
            ("ai-model/tools/terminal_safe.py",     "allowlisted shell commands"),
            ("ai-model/tools/todos.py",             "agent-facing todo CRUD"),
            ("ai-model/tools/utilities.py",         "coin flip, dice, time, conversions"),
            ("ai-model/tools/code.py",              "sandboxed Python exec/eval"),
            ("ai-model/tools/remember.py",          "zero-hallucination reminders/shopping/errands"),
            ("ai-model/tools/daily_log.py",          "structured homework and checkin tracker"),
            ("ai-model/tools/cloud_ai.py",           "ask Claude/ChatGPT/Gemini via browser — no API key"),
        ],
    ),
    (
        "4/10 — Computer Control",
        "vision (3-layer: DOM→AT-SPI→Qwen2-VL), executor (ydotool), computer_use, ui_parser, screen_map, actions, window_mgr, browser_control",
        [
            ("ai-model/tools/vision.py",            "3-layer perception: DOM → AT-SPI → Qwen2-VL grid"),
            ("ai-model/tools/executor.py",          "atomic GUI actions: CLICK/TYPE/SCROLL/PRESS/MOVE + volume/notify"),
            ("ai-model/tools/computer_use.py",      "high-level: smart_click, type_into, scan_screen"),
            ("ai-model/tools/ui_parser.py",         "YOLO UI detection + targeted OCR"),
            ("ai-model/tools/screen_map.py",        "OCR-only fallback element map"),
            ("ai-model/tools/actions.py",           "low-level ydotool mouse/keyboard"),
            ("ai-model/tools/window_manager.py",    "hyprctl window control"),
            ("ai-model/tools/browser_control.py",   "Playwright DOM-based web automation"),
            ("ai-model/tools/ui_positions.json",    "pre-saved pixel positions"),
        ],
    ),
    (
        "5/10 — Web Tools",
        "Web package: browser, DuckDuckGo search (+ browser_control fallback), deep_research pipeline, fetch/scrape (+ JS-shell detection), Wikipedia; PDF reader",
        [
            ("ai-model/tools/web/__init__.py",      "dispatcher"),
            ("ai-model/tools/web/http_client.py",   "SSL-aware HTTP + html_to_text"),
            ("ai-model/tools/web/browser.py",       "open_browser"),
            ("ai-model/tools/web/search.py",        "DuckDuckGo + Lite + browser_control fallback"),
            ("ai-model/tools/web/fetch.py",         "fetch_page, scrape_page + JS-shell detection"),
            ("ai-model/tools/web/wikipedia.py",     "wikipedia lookup"),
            ("ai-model/tools/web/inspect.py",       "inspect_page, find_forms, etc."),
            ("ai-model/tools/web/research.py",      "deep_research multi-source pipeline"),
            ("ai-model/tools/pdf.py",               "PDF read/analyse"),
        ],
    ),
    (
        "6/10 — Google Tools",
        "Google Apps package: OAuth2, Drive, Calendar, Classroom, Gmail",
        [
            ("ai-model/tools/google/__init__.py",   "dispatcher"),
            ("ai-model/tools/google/auth.py",       "OAuth2 / build_service"),
            ("ai-model/tools/google/drive.py",      "Drive actions"),
            ("ai-model/tools/google/calendar.py",   "Calendar actions"),
            ("ai-model/tools/google/classroom.py",  "Classroom actions"),
            ("ai-model/tools/google/gmail.py",      "Gmail: list, read, send, search"),
        ],
    ),
    (
        "7/10 — Personality",
        "Keyword-based persona detection + prompt templates",
        [
            ("ai-model/personality/__init__.py",    ""),
            ("ai-model/personality/loader.py",      "keyword-based mode detection"),
            ("ai-model/personality/default.txt",    "default persona"),
            ("ai-model/personality/coding.txt",     "coding persona"),
            ("ai-model/personality/teacher.txt",    "teacher persona"),
            ("ai-model/personality/assistant.txt",  "task assistant persona"),
        ],
    ),
    (
        "8/10 — WhatsApp Bridge",
        "Node.js Baileys bridge: server.js, setup UI, package.json",
        [
            ("whatsapp-ai-bot/server.js",           "Baileys client + Express"),
            ("whatsapp-ai-bot/index.html",          "QR login UI"),
            ("whatsapp-ai-bot/package.json",        ""),
        ],
    ),
    (
        "9/10 — Frontend UI",
        "Vanilla JS control panel (auto-scanned from ui/)",
        "_SCAN:ui",  # special marker: auto-scan this directory
    ),
    (
        "10/10 — Skills + Helpers + Memory Configs + Legacy",
        "skill_builder (approval gate + regex+AST scanner + versioned backups), AI-learned skills, launcher scripts, memory configs, legacy code",
        [
            ("ai-model/tools/skill_builder.py",          "AI skill creation — approval gate, dual-phase safety scanner, .bak versioning"),
            ("ai-model/tools/skills/__init__.py",         "skills package"),
            "_SCAN:ai-model/tools/skills",
            "_SCAN:ai-model/helpers",
            ("ai-model/memory/schedule.json",             "college schedule + exams + strictness ramp"),
            ("ai-model/memory/goals.json",                "core goals + scheduled goals"),
            ("ai-model/memory/behavioral_patterns.json",  "observed behavioral patterns"),
            ("ai-model/memory/prep_status.json",          "per-subject exam prep completion"),
            ("ai-model/memory/remember.json",             "reminders / shopping lists / errands"),
            ("ai-model/memory/daily_log.json",             "daily homework + checkin log"),
            ("ai-model/memory/long_term_memory.json",     "long-term milestones"),
            ("ai-model/legacy/router.py",                 "LEGACY — old monolithic router"),
            ("ai-model/legacy/ai_agent.py",               "LEGACY — old summarizer agent"),
        ],
    ),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

SEP = "=" * 80
THIN = "-" * 80

_TEXT_EXTS = {'.py', '.js', '.json', '.txt', '.md', '.html', '.css', '.ts', '.sh', '.env'}


def _scan_dir(directory: str, root: str) -> list:
    """Auto-discover text files under directory. Returns (rel_path, note) tuples."""
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
            results.append((rel, ""))
    return results


def _resolve_file_list(file_list, root: str) -> list:
    """Resolve a section's file_list, expanding _SCAN: markers."""
    if isinstance(file_list, str) and file_list.startswith("_SCAN:"):
        scan_rel = file_list[len("_SCAN:"):]
        return _scan_dir(os.path.join(root, scan_rel), root)

    resolved = []
    for item in file_list:
        if isinstance(item, str) and item.startswith("_SCAN:"):
            scan_rel = item[len("_SCAN:"):]
            resolved.extend(_scan_dir(os.path.join(root, scan_rel), root))
        else:
            resolved.append(item)
    return resolved


def build_export():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []

    # Master header
    lines.append(SEP)
    lines.append("PROJECT: AVRIL — Personal Advanced AI Assistant")
    lines.append("FULL CODEBASE EXPORT")
    lines.append(SEP)
    lines.append(f"Owner / Pen name: Divyansh (Bazric)")
    lines.append(f"AI Name: Avril (Satomi)")
    lines.append(f"Stack: Python (Flask + Ollama) backend | Node.js (Baileys) WhatsApp bot | Vanilla JS UI")
    lines.append(f"Exported: {now}")
    lines.append(SEP)
    lines.append(ARCHITECTURE)
    lines.append("")

    # Table of contents
    lines.append(THIN)
    lines.append("TABLE OF CONTENTS")
    lines.append(THIN)
    for title, desc, _ in SECTIONS:
        lines.append(f"  {title}: {desc}")
    lines.append(THIN)
    lines.append("")

    total_ok = 0
    total_files = 0

    for title, desc, raw_files in SECTIONS:
        file_list = _resolve_file_list(raw_files, ROOT)
        section_ok = 0
        section_miss = []

        # Section header
        lines.append("")
        lines.append(SEP)
        lines.append(f"SECTION: {title}")
        lines.append(f"  {desc}")
        lines.append(SEP)
        lines.append("")

        for item in file_list:
            rel_path, note = item[0], item[1] if len(item) > 1 else ""
            full_path = os.path.join(ROOT, rel_path)
            header_note = f"  [{note}]" if note else ""

            lines.append(THIN)
            lines.append(f"FILE: {rel_path}{header_note}")
            lines.append(THIN)

            if os.path.exists(full_path):
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    lines.append(f.read())
                section_ok += 1
            else:
                lines.append(f"[FILE NOT FOUND: {full_path}]")
                section_miss.append(rel_path)

        total_ok += section_ok
        total_files += len(file_list)

        status = f"{section_ok}/{len(file_list)} files"
        print(f"  {title:<36s}  {status}")
        if section_miss:
            print(f"    WARNING missing: {section_miss}")

    # Footer
    lines.append("")
    lines.append(SEP)
    lines.append("END OF FULL CODEBASE EXPORT")
    lines.append(f"Total: {total_ok}/{total_files} files across {len(SECTIONS)} sections")
    lines.append(SEP)

    with open(OUT_FULL, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n  Total: {total_ok}/{total_files} files → {OUT_FULL}")


if __name__ == "__main__":
    build_export()
