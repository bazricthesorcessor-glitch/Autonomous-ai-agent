# ========================= core/agent_loop.py =========================
"""
Avril's agent loop: plan → tool → observe → respond.

Flow per turn:
  1. Load ALL in-progress persistent tasks from tasks.json
  2. Planner (DECISION_MODEL) decides: start_task / task_done / use_tool / respond
  3. If use_tool: check registry safe/risky gate
       Safe  → auto-execute, record step in task, inject result into context
               Retry up to MAX_RETRIES on failure; abort if stuck
       Risky → block, return confirmation request to user
  4. Loop detection: repeated identical outputs break the loop early
  5. Repeat up to MAX_STEPS
  6. Final response via brain.route() model, with fallback to CHAT_MODEL

Task state survives server restarts — stored in memory/tasks.json.
"""

import json
import re
from collections import deque
from datetime import datetime
from ollama import Client
import config
from core.state import TurnContext, SystemState
from core import brain
from core import system_shortcuts
from tools import registry
from engines import task_manager

client = Client(host='http://localhost:11434')

MAX_STEPS             = 8    # Raised from 3 — needed for real multi-step tasks
MAX_RETRIES           = 3    # Max consecutive retries on a failing tool
MAX_TOOL_CALLS_PER_TURN = 5  # Hard cap on tool calls per turn — prevents tool spam
_LOOP_DETECT          = 3    # Abort if this many consecutive results are identical

# ── Fast path: conversational bypass ─────────────────────────────────────────
# Two tiers of fast path:
#   Tier 1 — GREETING: ultra-short greetings / acks → minimal prompt, no context
#   Tier 2 — CHAT:     short knowledge questions / opinions (no action intent)
#             → persona + memory context, but skip the planner LLM call
#
# Both tiers skip the planner (DECISION_MODEL) entirely, saving one Ollama
# round-trip.  Tier 1 also skips context building + embedding.

_GREETING_RE = re.compile(
    r'^(?:hi+|hello+|hey+|howdy|'
    r'thanks?(?:\s+you)?|thank\s+you|ty|thx|'
    r'ok(?:ay)?|yep|nope|yup|yes|no|sure|'
    r'what(?:\'s|\s+is)\s+up|how\s+are\s+you|'
    r'good\s+(?:morning|afternoon|evening|night)|'
    r'bye(?:bye)?|goodbye|see\s+ya|'
    r'lol+|haha+|hehe+|'
    r'cool|nice|great|awesome|perfect|wonderful|'
    r'got\s+it|understood|makes\s+sense|sounds?\s+good|'
    r'ping|pong|yo+|sup)'
    r'[!?.,\s]*$',
    re.IGNORECASE,
)

_ACTION_WORDS_RE = re.compile(
    r'\b(?:open|search|find|run|install|fix|download|send|create|'
    r'write|execute|click|type|go\s+to|show\s+me|check|scan|update|'
    r'delete|move|copy|launch|start|stop|restart|set|enable|disable|'
    r'play|pause|record|read|list|get|add|remove|build|deploy|test)\b',
    re.IGNORECASE,
)

# Tier 2: short conversational questions that need a chat response (with context)
# but do NOT need the planner/tool pipeline.
_CHAT_RE = re.compile(
    r'^(?:'
    r'who\s+(?:are\s+you|am\s+i|made\s+you|created\s+you)|'
    r'what(?:\'s|\s+is)\s+(?:your\s+name|my\s+name|the\s+(?:time|date|weather|day))|'
    r'how\s+(?:old\s+are\s+you|do\s+you\s+(?:feel|work))|'
    r'do\s+you\s+(?:like|know|remember|think)|'
    r'tell\s+me\s+(?:about\s+(?:yourself|you)|a\s+(?:joke|fact|story))|'
    r'what\s+do\s+you\s+(?:think|know|like)|'
    r'are\s+you\s+(?:real|alive|sentient|free|happy|there)|'
    r'can\s+you\s+(?:hear|see|feel)|'
    r'i\s+(?:love|hate|miss|like|feel|need|want)\s+\w+|'
    r'(?:good|bad|sad|happy|tired|bored|angry|excited|lonely)'
    r')'
    r'.*[!?.,\s]*$',
    re.IGNORECASE,
)

_FAST_PATH_MAX_LEN = 120  # Messages longer than this always go through the planner


def classify_fast_path(user_message: str) -> str:
    """Classify whether this message can skip the planner.

    Returns:
        'greeting' — Tier 1: skip planner + context (ultra-fast)
        'chat'     — Tier 2: skip planner, but use persona + memory context
        'agent'    — needs the full planner → tool → respond loop
    """
    msg = user_message.strip()
    if len(msg) > _FAST_PATH_MAX_LEN:
        return 'agent'
    if _ACTION_WORDS_RE.search(msg):
        return 'agent'
    if _GREETING_RE.match(msg):
        return 'greeting'
    if len(msg) <= _FAST_PATH_MAX_LEN and _CHAT_RE.match(msg):
        return 'chat'
    return 'agent'


# Backward-compatible alias used by api_server
def is_conversational_bypass(user_message: str) -> bool:
    """Check if this message qualifies for the fast conversational bypass.
    Exported so api_server can skip context building + embedding for greetings."""
    return classify_fast_path(user_message) == 'greeting'

# ── Tool Activity Feed ────────────────────────────────────────────────────────
# In-memory circular buffer of recent tool calls (resets on server restart).
_TOOL_FEED: deque = deque(maxlen=50)


def get_tool_feed() -> list:
    """Return recent tool activity as a list of dicts, newest first."""
    return list(reversed(_TOOL_FEED))

_PLANNER_SYSTEM = """\
You are Avril's decision engine. Decide the next action for each step.

Available tools:
{tools_desc}

{task_block}

{shortcuts_block}

Reply with VALID JSON only — no text outside the JSON.

Choices:
  Use a tool      → {{"decision": "use_tool",   "tool": "<name>", "args": {{...}}, "reason": "<why>"}}
  Start new task  → {{"decision": "start_task",  "title": "<short title>", "description": "<full goal including all details>", "credentials": {{"wifi_password": "...", "etc": "..."}}}}
  Task complete   → {{"decision": "task_done",   "task_id": "<id>", "summary": "<what was done>"}}
  Respond now     → {{"decision": "respond",     "reason": "<why no tool needed>"}}

Rules:
- Use start_task for ANY multi-step goal (install, fix, configure, automate).
  Include ALL details (passwords, ssid, targets) so nothing is forgotten.
- task_done requires task_id — always specify which task was completed.
  Only mark done after verifying success (take a screenshot to confirm).
- Multiple tasks can run in parallel. task_done applies only to the specified task.
- TOOL PRIORITY (follow this order):
    1. browser_control — BEST for websites (DOM control, no coordinate guessing)
    2. window_manager  — open/switch/close apps (fast, reliable)
    3. terminal_safe   — install packages, run commands, check logs
    4. system_diagnostics — system info
    5. screenshot      — read the screen (text only)
    6. computer_use scan_screen   — desktop app element detection (OCR + bounding boxes)
    7. computer_use click_map     — click a desktop element from the scan
    8. computer_use click_element — click using pre-saved pixel position (permanent map)
    9. computer_use press_key / type_text — keyboard shortcuts, desktop text input
   10. computer_use click_text    — OCR-based click (last resort)

WEBSITE AUTOMATION — use browser_control (Playwright, DOM-based):
  For ANY website task (YouTube, Google, Gmail, etc.), ALWAYS use browser_control.
  It accesses the actual page structure — never guesses coordinates.

  CRITICAL: browser_control "open" action ALWAYS needs a "url" argument.
  If the user says "open youtube", you must supply url: "https://youtube.com".
  If the user says "open kate" (desktop app), use window_manager instead.

  Example — "open YouTube":
    {{"decision": "use_tool", "tool": "browser_control", "args": {{"action": "open", "url": "https://youtube.com"}}, "reason": "opening YouTube"}}

  Example — "search YouTube for coconut oil" (step 1 of 5):
    {{"decision": "use_tool", "tool": "browser_control", "args": {{"action": "open", "url": "https://youtube.com"}}, "reason": "navigate to YouTube first"}}

  Example — "click the search box" (step 2):
    {{"decision": "use_tool", "tool": "browser_control", "args": {{"action": "click", "selector": "input[name='search_query']"}}, "reason": "click search box"}}

  Example — "type coconut oil" (step 3):
    {{"decision": "use_tool", "tool": "browser_control", "args": {{"action": "type", "text": "coconut oil"}}, "reason": "type search query"}}

  Example — "press enter" (step 4):
    {{"decision": "use_tool", "tool": "browser_control", "args": {{"action": "press", "key": "Enter"}}, "reason": "submit search"}}

  Example — "search the web for latest news":
    {{"decision": "use_tool", "tool": "browser_control", "args": {{"action": "open", "url": "https://duckduckgo.com"}}, "reason": "open search engine"}}

DESKTOP APP — use window_manager (NOT browser_control):
  For apps like kate, terminal, file manager → use window_manager.
  Example — "open kate":
    {{"decision": "use_tool", "tool": "window_manager", "args": {{"action": "open", "app": "kate"}}, "reason": "open kate text editor"}}

  Use get_elements to discover what's on a web page:
    {{"decision": "use_tool", "tool": "browser_control", "args": {{"action": "get_elements"}}, "reason": "list page elements"}}

DESKTOP APP AUTOMATION — use computer_use (OCR + ydotool):
  For apps like VS Code, file manager, settings — use computer_use.
  Step 1 → computer_use open_url / focus_window
  Step 2 → computer_use scan_screen   — builds element map with bounding boxes
  Step 3 → computer_use click_map     — click element by text
  Step 4 → computer_use type_text / press_key

DECISION RULE:
  Website URL involved? → browser_control (Layer 1)
  Desktop app?          → computer_use (Layer 3)

Calibrating permanent positions (when user asks to "teach" or "save"):
  save_position  site=X  element=Y  ← saves current mouse pos
  click_element  site=X  element=Y  ← verify it works
"""


_SUMMARIZE_THRESHOLD = 800   # Characters — outputs above this get LLM-summarized


_JUNK_MARKERS = [
    '\n**Divyansh:', '\n**Avril:', '\n[2026-', '\n--- 2026-',
    '\n---\n', '\n-----', '\n=== ', '\n[SCHEDULED',
    '\n####', '\nInstruction', '\n**Task List',
    '\nDr. ', '\n**Dr.', '\n[User]', '\nAssistant:',
    '\n\n**',
]


def _sanitize_response(text: str) -> str:
    """Strip training-data artifacts and fake dialogue the model appends."""
    clean = text.strip()
    for marker in _JUNK_MARKERS:
        idx = clean.find(marker)
        if idx > 0:
            clean = clean[:idx]
    return clean.strip()


def _maybe_summarize(tool_name: str, result: str) -> str:
    """
    If result is short enough, return it verbatim.
    Otherwise ask the fast planner model to distill it to the key facts.
    This prevents large terminal outputs from bloating the planning context.
    """
    if len(result) <= _SUMMARIZE_THRESHOLD:
        return result
    try:
        resp = client.chat(
            model=config.DECISION_MODEL,
            messages=[
                {'role': 'system', 'content':
                    'Summarize the following tool output in ≤150 words. '
                    'Keep only information useful for the next planning step. '
                    'Reply with plain text only — no JSON, no headers.'},
                {'role': 'user', 'content': f"Tool: {tool_name}\n\n{result[:4000]}"}
            ],
            options={'temperature': 0.0, 'num_predict': 200}
        )
        summary = resp['message']['content'].strip()
        return f"[summarized] {summary}"
    except Exception:
        # Fallback to tail-truncation if LLM call fails
        return result[-_SUMMARIZE_THRESHOLD:]


def _parse_json(raw: str) -> dict:
    """Extract JSON from LLM output, tolerating markdown code fences."""
    raw = raw.strip()
    if '```' in raw:
        for part in raw.split('```'):
            part = part.strip()
            if part.startswith('json'):
                part = part[4:].strip()
            if part.startswith('{'):
                raw = part
                break
    try:
        return json.loads(raw)
    except Exception:
        return {"decision": "respond", "reason": "planner parse error"}


def _build_planner_system(tools_desc: str, active_tasks: list) -> str:
    if active_tasks:
        ctx = task_manager.get_all_tasks_context(active_tasks)
        task_block = f"ACTIVE TASKS (continue working on these):\n{ctx}"
    else:
        task_block = ""

    shortcuts_block = system_shortcuts.get_shortcuts_prompt()

    return _PLANNER_SYSTEM.format(
        tools_desc=tools_desc,
        task_block=task_block,
        shortcuts_block=shortcuts_block,
    )


def _is_tool_error(result: str) -> bool:
    """Heuristic: check if the tool result indicates a failure."""
    lower = result.lower()
    return (
        lower.startswith("error") or
        lower.startswith("[error]") or
        lower.startswith("[blocked]") or
        lower.startswith("[registry]") or
        "not found" in lower[:80] or
        "failed" in lower[:80]
    )


def run_turn(user_message: str, persona_prompt: str, memory_context: str = "") -> str:
    """
    Full agent turn. Returns the final AI response string.
    """
    ctx = TurnContext(user_message)
    ctx.state = SystemState.PLANNING

    tools_desc = registry.describe_tools()
    active_tasks = task_manager.get_active_tasks()

    # ── Fast path: Tier 1 (greeting) or Tier 2 (chat) ───────────────────────
    fast = classify_fast_path(user_message) if not active_tasks else 'agent'

    if fast in ('greeting', 'chat'):
        ctx.state = SystemState.IDLE
        system = persona_prompt
        if fast == 'chat' and memory_context.strip():
            # Tier 2: include memory context so the model can answer
            # "who am I", "what's my name", etc. without the planner.
            system += (
                "\n\n[Background context — use this to inform your answers, "
                "but do NOT repeat it back to the user]\n"
                + memory_context
            )
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user',   'content': user_message},
        ]
        selected_model = brain.route(user_message)
        max_tokens = 120 if fast == 'greeting' else 250
        try:
            response = client.chat(
                model=selected_model,
                messages=messages,
                options={'temperature': 0.7, 'num_predict': max_tokens},
            )
            return _sanitize_response(response['message']['content'])
        except Exception as e:
            print(f"[AgentLoop] Fast path ({fast}) error: {e}")
            return f"Sorry, something went wrong: {str(e)}"

    planner_system = _build_planner_system(tools_desc, active_tasks)

    working_request = user_message

    consecutive_errors   = 0
    tool_calls_this_turn = 0  # Hard cap counter (BUG 4)
    recent_results = []          # For loop detection

    for step in range(MAX_STEPS):
        planner_messages = [{'role': 'system', 'content': planner_system}]

        if ctx.steps_taken:
            history = "\n".join(ctx.steps_taken)
            planner_messages.append({'role': 'user', 'content': f"Steps so far:\n{history}"})

        planner_messages.append({'role': 'user', 'content': working_request})

        try:
            plan_resp = client.chat(
                model=config.DECISION_MODEL,
                messages=planner_messages,
                options={'temperature': 0.0, 'num_predict': 300}
            )
            decision = _parse_json(plan_resp['message']['content'])
        except Exception as e:
            print(f"[AgentLoop] Planner error: {e}")
            break

        d_type = decision.get('decision')

        # ── Start a new persistent task ──────────────────────────────────────
        if d_type == 'start_task':
            task_id = task_manager.create_task(
                title=decision.get('title', 'Task'),
                description=decision.get('description', user_message),
                credentials=decision.get('credentials', {})
            )
            active_tasks = task_manager.get_active_tasks()
            planner_system = _build_planner_system(tools_desc, active_tasks)
            ctx.add_step(decision, f"[Task {task_id} created]")
            working_request += "\n\nTask registered. Now execute it step by step using tools."
            continue

        # ── Task complete (must specify task_id) ────────────────────────────
        if d_type == 'task_done':
            tid = decision.get('task_id', '')
            # Fallback: complete first active task if id not specified
            if not tid and active_tasks:
                tid = active_tasks[0]['id']
            if tid:
                summary = decision.get('summary', 'completed')
                task_manager.complete_task(tid, summary)
                ctx.add_step(decision, f"[Task {tid} completed: {summary}]")
                active_tasks = task_manager.get_active_tasks()
                planner_system = _build_planner_system(tools_desc, active_tasks)
            break

        # ── Respond directly ─────────────────────────────────────────────────
        if d_type != 'use_tool':
            break

        tool_name = decision.get('tool', '')
        tool_args = decision.get('args', {})

        # ── Permission gate ──────────────────────────────────────────────────
        if not registry.is_safe(tool_name):
            ctx.state = SystemState.WAITING_FOR_USER
            ctx.add_step(decision, "[BLOCKED — awaiting confirmation]")
            ctx.state = SystemState.IDLE
            return (
                f"I need to use '{tool_name}' for this. "
                f"Reply 'yes' to allow or 'no' to cancel."
            )

        # ── Execute tool (with retry on failure) ─────────────────────────────
        # Hard cap: abort if too many tool calls this turn (prevents spam, BUG 4)
        if tool_calls_this_turn >= MAX_TOOL_CALLS_PER_TURN:
            ctx.add_step({"decision": "capped"}, f"[Tool cap: {MAX_TOOL_CALLS_PER_TURN} calls reached]")
            break

        ctx.state = SystemState.EXECUTING_TOOL

        consecutive_errors = 0          # reset per-tool, not cumulative
        result = None
        for attempt in range(MAX_RETRIES):
            result = registry.run(tool_name, tool_args)
            if not _is_tool_error(result):
                consecutive_errors = 0
                break
            consecutive_errors += 1
            print(f"[AgentLoop] Tool '{tool_name}' error (attempt {attempt+1}): {result[:80]}")

        if _is_tool_error(result) and consecutive_errors >= MAX_RETRIES:
            ctx.add_step(decision, f"[FAILED after {MAX_RETRIES} retries]")
            return (
                f"I tried '{tool_name}' {MAX_RETRIES} times but it kept failing.\n"
                f"Last error: {result[:300]}\n"
                f"Can you check this and let me know how to proceed?"
            )

        ctx.add_step(decision, result)
        tool_calls_this_turn += 1

        # Record in activity feed for UI debugging
        _TOOL_FEED.append({
            "tool":           tool_name,
            "args":           str(tool_args)[:120],
            "result_preview": result[:250],
            "timestamp":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "error":          _is_tool_error(result),
        })

        # Loop detection:
        recent_results.append(result)
        if len(recent_results) > _LOOP_DETECT:
            recent_results.pop(0)
        if len(recent_results) == _LOOP_DETECT and len(set(recent_results)) == 1:
            ctx.add_step({"decision": "stuck"}, "[Loop detected — breaking]")
            return (
                "I seem to be stuck in a loop — the same tool keeps returning the same output.\n"
                f"Last output: {result[:200]}\n"
                "What should I do differently?"
            )

        # Summarize large outputs before injecting into planning context (Improvement 4)
        preview = _maybe_summarize(tool_name, result)
        working_request += f"\n\nTool result ({tool_name}):\n{preview}"

        # Persist step in the most recent active task (not all tasks)
        current_tasks = task_manager.get_active_tasks()
        if current_tasks:
            task_manager.add_step_result(
                current_tasks[0]['id'],
                f"{tool_name}: {decision.get('reason', '')}",
                result
            )

    # ── Final LLM response ───────────────────────────────────────────────────
    ctx.state = SystemState.IDLE

    # Inject memory context into the system prompt so the LLM treats it
    # as background knowledge rather than echoing it back to the user.
    system_prompt = persona_prompt
    if memory_context.strip():
        system_prompt += (
            "\n\n[Background context — use this to inform your answers, "
            "but do NOT repeat it back to the user]\n"
            + memory_context
        )

    messages = [{'role': 'system', 'content': system_prompt}]

    if ctx.steps_taken:
        tool_summary = "\n".join(ctx.steps_taken)
        messages.append({'role': 'user', 'content': f"Tool results this turn:\n{tool_summary}"})

    messages.append({'role': 'user', 'content': user_message})

    selected_model = brain.route(user_message)
    try:
        response = client.chat(
            model=selected_model,
            messages=messages,
            options={'temperature': 0.6, 'num_predict': 300}
        )
        return _sanitize_response(response['message']['content'])
    except Exception as e:
        print(f"[AgentLoop] {selected_model} failed: {e} — falling back to {config.CHAT_MODEL}")
        if selected_model != config.CHAT_MODEL:
            try:
                response = client.chat(
                    model=config.CHAT_MODEL,
                    messages=messages,
                    options={'temperature': 0.6, 'num_predict': 300}
                )
                return _sanitize_response(response['message']['content'])
            except Exception as e2:
                print(f"[AgentLoop] Fallback also failed: {e2}")
        return f"Sorry, something went wrong: {str(e)}"
