# ========================= core/agent_loop.py =========================
"""Avril's central brain loop: classify -> plan -> execute -> verify -> respond."""

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
from engines import task_manager, todo_manager

client = Client(host='http://localhost:11434')

MAX_STEPS             = 8    # Raised from 3 -- needed for real multi-step tasks
MAX_RETRIES           = 3    # Max consecutive retries on a failing tool
MAX_TOOL_CALLS_PER_TURN = 5  # Hard cap on tool calls per turn -- prevents tool spam
_LOOP_DETECT          = 3    # Abort if this many consecutive results are identical

# == Fast path: conversational bypass =========================================
# Two tiers of fast path:
#   Tier 1 -- GREETING: ultra-short greetings / acks -> minimal prompt, no context
#   Tier 2 -- CHAT:     short knowledge questions / opinions (no action intent)
#             -> persona + memory context, but skip the planner LLM call
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
        'greeting' -- Tier 1: skip planner + context (ultra-fast)
        'chat'     -- Tier 2: skip planner, but use persona + memory context
        'agent'    -- needs the full planner -> tool -> respond loop
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

# == Tool Activity Feed ========================================================
# In-memory circular buffer of recent tool calls (resets on server restart).
_TOOL_FEED: deque = deque(maxlen=50)


def get_tool_feed() -> list:
    """Return recent tool activity as a list of dicts, newest first."""
    return list(reversed(_TOOL_FEED))


# == Perception & Verification =================================================

# Tools that require post-action perception polling
_PERCEPTION_TOOLS = {
    "browser_control": {"open", "click", "type", "press", "scroll"},
    "executor":        {"*"},       # all executor actions need verification
    "window_manager":  {"open", "launch_app", "focus_window"},
}

# Actions that trigger long-running responses (need monitor_response)
_LONG_RESPONSE_ACTIONS = {
    ("browser_control", "type"),
    ("executor", "TYPE"),
}


def _needs_perception(tool_name: str, tool_args: dict) -> bool:
    """Check if this tool+action combination needs post-action perception."""
    if not config.VERIFY_ACTIONS:
        return False
    actions = _PERCEPTION_TOOLS.get(tool_name)
    if actions is None:
        return False
    if "*" in actions:
        return True
    action = str(tool_args.get("action", tool_args.get("command", ""))).strip().lower()
    # For executor, also check the first word of the command string
    if tool_name == "executor":
        cmd = str(tool_args.get("command", "")).strip()
        if cmd:
            action = cmd.split()[0].lower() if cmd.split() else ""
    return action in actions


def _capture_screen_hash() -> str:
    """Take a screenshot and return the screen hash for comparison."""
    try:
        registry.run("screenshot", {"mode": "active_window"})
        cache = config.safe_load_json(config.SCREEN_CACHE_FILE, {})
        return cache.get("screen_hash", "")
    except Exception:
        return ""


def _perceive_after_action(tool_name: str, tool_args: dict, ctx: TurnContext) -> str:
    """Post-action perception: wait for page state, verify change occurred.

    Returns a perception summary string (empty if no perception needed).
    """
    if not _needs_perception(tool_name, tool_args):
        return ""

    ctx.state = SystemState.PERCEIVING
    action = str(tool_args.get("action", "")).strip().lower()

    # Phase A: Wait for page to stabilize
    wait_result = registry.run("vision", {
        "action": "wait_ready",
        "mode": "active_window",
        "interval": config.PERCEPTION_POLL_INTERVAL,
        "timeout": config.PERCEPTION_TIMEOUT,
    })

    # Phase B: For long-response actions, also monitor text stability
    if _is_long_response_context(tool_name, tool_args):
        monitor_result = registry.run("vision", {
            "action": "monitor_response",
            "mode": "active_window",
            "interval": config.PERCEPTION_POLL_INTERVAL,
            "stable_polls": config.RESPONSE_STABLE_POLLS,
            "timeout": config.MONITOR_RESPONSE_TIMEOUT,
        })
        return f"Page state: {wait_result}\nResponse monitor: {monitor_result}"

    return f"Page state: {wait_result}"


def _verify_action_effect(
    pre_hash: str,
    tool_name: str,
    tool_args: dict,
    ctx: TurnContext,
) -> tuple[bool, str]:
    """Compare pre/post screenshots to verify the action had an effect.

    Returns (changed: bool, verification_summary: str).
    """
    if not _needs_perception(tool_name, tool_args):
        return True, ""

    post_hash = _capture_screen_hash()

    if not pre_hash or not post_hash:
        return True, "[verification: screenshot unavailable]"

    changed = (pre_hash != post_hash)
    if changed:
        return True, "[verification: screen changed - action successful]"
    else:
        ctx.verification_failures += 1
        return False, "[verification: screen UNCHANGED - action may have failed]"


def _is_long_response_context(tool_name: str, tool_args: dict) -> bool:
    """Heuristic: detect if the current action might trigger a long-running output."""
    action = str(tool_args.get("action", "")).lower()

    # Direct match on known long-response action pairs
    if (tool_name, action) in _LONG_RESPONSE_ACTIONS:
        return True

    # Heuristic: pressing Enter after typing in an AI/chat context
    if action == "press" and str(tool_args.get("key", "")).lower() in ("enter", "return"):
        try:
            cache = config.safe_load_json(config.SCREEN_CACHE_FILE, {})
            text = (cache.get("last_screen_text", "") or "").lower()
            ai_indicators = {
                "chatgpt", "claude", "gemini", "copilot",
                "send a message", "ask anything", "type a message",
            }
            if any(ind in text for ind in ai_indicators):
                return True
        except Exception:
            pass

    return False


# == Planner System Prompt =====================================================

_PLANNER_SYSTEM = """\
You are Avril's central decision engine. Execute the cycle:
classify intent -> follow the TODO plan -> route to the correct tool -> verify -> finish.

Available tools:
{tools_desc}

{analysis_block}

{task_block}

{shortcuts_block}

Reply with VALID JSON only -- no text outside the JSON.

Choices:
  Use a tool      -> {{"decision": "use_tool",   "tool": "<name>", "args": {{...}}, "reason": "<why>"}}
  Start new task  -> {{"decision": "start_task",  "title": "<short title>", "description": "<full goal including all details>", "credentials": {{"wifi_password": "...", "etc": "..."}}}}
  Task complete   -> {{"decision": "task_done",   "task_id": "<id>", "summary": "<what was done>"}}
  Respond now     -> {{"decision": "respond",     "reason": "<why no tool needed>"}}

Rules:
- The request has already been classified. Respect the provided intent category and TODO plan.
- Treat the TODO plan as the canonical execution checklist. Advance it step by step.
- Use start_task for ANY multi-step goal (install, fix, configure, automate).
  Include ALL details (passwords, ssid, targets) so nothing is forgotten.
- task_done requires task_id -- always specify which task was completed.
  Only mark done after verifying success (take a screenshot to confirm).
- Multiple tasks can run in parallel. task_done applies only to the specified task.
- TOOL ROUTING:
        1. code            -- math / computation / formula evaluation
        2. web             -- information lookups and fetches
        3. browser_control -- websites when DOM control is available
        4. vision          -- locate elements, page state, OCR completion detection
        5. executor        -- atomic GUI actions after vision returns coordinates
        6. window_manager  -- open or focus desktop applications
        7. terminal_safe   -- run controlled commands
        8. screenshot / ui_parser / computer_use -- fallback perception or automation layers

VISION RULES (READ-ONLY -- vision NEVER performs actions):
- Vision is strictly a perception interface. It returns data. It never clicks, types, scrolls, or controls the mouse/keyboard.
- Use vision locate to get coordinates: returns {{"coordinates": [x, y], "state": "FOUND"|"NOT_FOUND"}}
- Use vision page_state to check if a page is LOADING/READY/ERROR.
- Use vision wait_ready to block until the page is READY.
- Use vision monitor_response to block until text output stops changing.
- After vision returns coordinates, issue the action through executor (e.g., CLICK x y).
- NEVER pass action commands to vision. NEVER expect vision to click or type.

EXECUTOR RULES (WRITE-ONLY -- executor ONLY performs actions, never reads):
- Executor performs atomic GUI commands. It does not inspect the screen.
- Commands: CLICK x y, TYPE x y text, SCROLL x y up|down, WAIT seconds, PRESS key
- Vision supplies coordinates -> executor performs the action -> vision verifies the result.
- Flow: vision.locate -> executor.CLICK -> vision.page_state (verify)

VISION->EXECUTOR WORKFLOW EXAMPLE:
  Goal: Click the search box on YouTube
  Step 1 -> {{"decision": "use_tool", "tool": "vision", "args": {{"action": "locate", "query": "search input"}}, "reason": "find search box coordinates"}}
           -> Returns: {{"coordinates": [640, 52], "state": "FOUND"}}
  Step 2 -> {{"decision": "use_tool", "tool": "executor", "args": {{"command": "CLICK 640 52"}}, "reason": "click at coordinates returned by vision"}}
  Step 3 -> {{"decision": "use_tool", "tool": "vision", "args": {{"action": "page_state"}}, "reason": "verify click landed"}}

WEBSITE AUTOMATION -- use browser_control (Playwright, DOM-based):
  For ANY website task (YouTube, Google, Gmail, etc.), ALWAYS use browser_control.
  It accesses the actual page structure -- never guesses coordinates.

  CRITICAL: browser_control "open" action ALWAYS needs a "url" argument.
  If the user says "open youtube", you must supply url: "https://youtube.com".
  If the user says "open kate" (desktop app), use window_manager instead.

  Example -- "open YouTube":
    {{"decision": "use_tool", "tool": "browser_control", "args": {{"action": "open", "url": "https://youtube.com"}}, "reason": "opening YouTube"}}

  Example -- "search YouTube for coconut oil" (step 1 of 5):
    {{"decision": "use_tool", "tool": "browser_control", "args": {{"action": "open", "url": "https://youtube.com"}}, "reason": "navigate to YouTube first"}}

  Example -- "click the search box" (step 2):
    {{"decision": "use_tool", "tool": "browser_control", "args": {{"action": "click", "selector": "input[name='search_query']"}}, "reason": "click search box"}}

  Example -- "type coconut oil" (step 3):
    {{"decision": "use_tool", "tool": "browser_control", "args": {{"action": "type", "text": "coconut oil"}}, "reason": "type search query"}}

  Example -- "press enter" (step 4):
    {{"decision": "use_tool", "tool": "browser_control", "args": {{"action": "press", "key": "Enter"}}, "reason": "submit search"}}

  Example -- "search the web for latest news":
    {{"decision": "use_tool", "tool": "browser_control", "args": {{"action": "open", "url": "https://duckduckgo.com"}}, "reason": "open search engine"}}

DESKTOP APP -- use window_manager (NOT browser_control):
  For apps like kate, terminal, file manager -> use window_manager.
  Example -- "open kate":
    {{"decision": "use_tool", "tool": "window_manager", "args": {{"action": "open", "app": "kate"}}, "reason": "open kate text editor"}}

  Use get_elements to discover what's on a web page:
    {{"decision": "use_tool", "tool": "browser_control", "args": {{"action": "get_elements"}}, "reason": "list page elements"}}

DESKTOP APP AUTOMATION -- use vision + executor:
    For apps like VS Code, file manager, settings:
    Step 1 -> window_manager launch/focus the app
    Step 2 -> vision locate the required element or inspect page state
    Step 3 -> executor run atomic GUI commands using returned coordinates
    Step 4 -> vision verify the UI changed as expected

DECISION RULE:
    Computation?          -> code
    Information lookup?   -> web
    Website interaction?  -> browser_control first, vision second
    Desktop GUI?          -> vision then executor
    System/app control?   -> terminal_safe or window_manager

Calibrating permanent positions (when user asks to "teach" or "save"):
  save_position  site=X  element=Y  <- saves current mouse pos
  click_element  site=X  element=Y  <- verify it works
"""


_SUMMARIZE_THRESHOLD = 800   # Characters -- outputs above this get LLM-summarized


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
                    'Summarize the following tool output in <=150 words. '
                    'Keep only information useful for the next planning step. '
                    'Reply with plain text only -- no JSON, no headers.'},
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


def _sync_initial_todos(plan: list[str]) -> None:
    if not plan:
        return
    todo_manager.clear_all()
    created = todo_manager.create_items(plan)
    if created:
        todo_manager.update_status(created[0]['id'], 'in_progress')


def _advance_todo_progress() -> None:
    active = todo_manager.get_active()
    in_progress = next((item for item in active if item.get('status') == 'in_progress'), None)
    if in_progress:
        todo_manager.update_status(in_progress['id'], 'done')

    active = todo_manager.get_active()
    next_pending = next((item for item in active if item.get('status') == 'pending'), None)
    if next_pending:
        todo_manager.update_status(next_pending['id'], 'in_progress')


def _complete_all_todos() -> None:
    for item in todo_manager.get_active():
        todo_manager.update_status(item['id'], 'done')


def _build_planner_system(tools_desc: str, active_tasks: list, analysis: dict) -> str:
    if active_tasks:
        ctx = task_manager.get_all_tasks_context(active_tasks)
        task_block = f"ACTIVE TASKS (continue working on these):\n{ctx}"
    else:
        task_block = ""

    shortcuts_block = system_shortcuts.get_shortcuts_prompt()
    analysis_block = brain.format_analysis_for_prompt(analysis)

    return _PLANNER_SYSTEM.format(
        tools_desc=tools_desc,
        analysis_block=analysis_block,
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


# == Main Turn Loop ============================================================

def run_turn(user_message: str, persona_prompt: str, memory_context: str = "") -> str:
    """
    Full agent turn. Returns the final AI response string.
    """
    ctx = TurnContext(user_message)
    ctx.state = SystemState.PLANNING

    tools_desc = registry.describe_tools()
    active_tasks = task_manager.get_active_tasks()
    analysis = brain.analyze_request(user_message)

    if not active_tasks and analysis.get('needs_plan'):
        task_manager.create_task(
            title=analysis.get('task_title', analysis.get('title', 'Task')),
            description=user_message,
            category=analysis.get('category', 'task_request'),
            plan=analysis.get('todo_plan', analysis.get('todo', [])),
        )
        _sync_initial_todos(analysis.get('todo_plan', analysis.get('todo', [])))
        active_tasks = task_manager.get_active_tasks()

    # == Fast path: Tier 1 (greeting) or Tier 2 (chat) ========================
    fast = classify_fast_path(user_message) if not active_tasks else 'agent'

    if fast in ('greeting', 'chat'):
        ctx.state = SystemState.IDLE
        system = persona_prompt
        if fast == 'chat' and memory_context.strip():
            # Tier 2: include memory context so the model can answer
            # "who am I", "what's my name", etc. without the planner.
            system += (
                "\n\n[Background context -- use this to inform your answers, "
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

    planner_system = _build_planner_system(tools_desc, active_tasks, analysis)

    working_request = f"{brain.format_analysis_for_prompt(analysis)}\n\nUser request:\n{user_message}"

    consecutive_errors   = 0
    tool_calls_this_turn = 0  # Hard cap counter
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

        # == Start a new persistent task =======================================
        if d_type == 'start_task':
            task_id = task_manager.create_task(
                title=decision.get('title', 'Task'),
                description=decision.get('description', user_message),
                credentials=decision.get('credentials', {}),
                category=analysis.get('category', 'task_request'),
                plan=analysis.get('todo_plan', analysis.get('todo', [])),
            )
            active_tasks = task_manager.get_active_tasks()
            plan = analysis.get('todo_plan', analysis.get('todo', []))
            if plan:
                _sync_initial_todos(plan)
            planner_system = _build_planner_system(tools_desc, active_tasks, analysis)
            ctx.add_step(decision, f"[Task {task_id} created]")
            working_request += "\n\nTask registered. Now execute it step by step using tools."
            continue

        # == Task complete (must specify task_id) ==============================
        if d_type == 'task_done':
            tid = decision.get('task_id', '')
            # Fallback: complete first active task if id not specified
            if not tid and active_tasks:
                tid = active_tasks[0]['id']
            if tid:
                summary = decision.get('summary', 'completed')
                task_manager.complete_task(tid, summary)
                _complete_all_todos()
                ctx.add_step(decision, f"[Task {tid} completed: {summary}]")
                active_tasks = task_manager.get_active_tasks()
                planner_system = _build_planner_system(tools_desc, active_tasks, analysis)
            break

        # == Respond directly ==================================================
        if d_type != 'use_tool':
            break

        tool_name = decision.get('tool', '')
        tool_args = decision.get('args', {})

        # == Permission gate ===================================================
        if not registry.is_safe(tool_name):
            ctx.state = SystemState.WAITING_FOR_USER
            ctx.add_step(decision, "[BLOCKED -- awaiting confirmation]")
            ctx.state = SystemState.IDLE
            return (
                f"I need to use '{tool_name}' for this. "
                f"Reply 'yes' to allow or 'no' to cancel."
            )

        # == Validate executor commands before dispatch ========================
        if tool_name == "executor":
            cmd = tool_args.get("command", "")
            cmds = tool_args.get("commands")
            if cmd:
                normalized = brain.normalize_action_command(str(cmd))
                if normalized is None:
                    ctx.add_step(decision, f"[Invalid action command: {cmd}]")
                    working_request += (
                        f"\n\n[Invalid command format: '{cmd}'. "
                        "Use: CLICK x y, TYPE x y text, SCROLL x y direction, "
                        "WAIT seconds, PRESS key]"
                    )
                    continue
                tool_args["command"] = normalized
            if cmds and isinstance(cmds, list):
                normalized_cmds = []
                all_valid = True
                for c in cmds:
                    n = brain.normalize_action_command(str(c))
                    if n is None:
                        ctx.add_step(decision, f"[Invalid action command: {c}]")
                        working_request += (
                            f"\n\n[Invalid command format: '{c}'. "
                            "Use: CLICK x y, TYPE x y text, SCROLL x y direction, "
                            "WAIT seconds, PRESS key]"
                        )
                        all_valid = False
                        break
                    normalized_cmds.append(n)
                if not all_valid:
                    continue
                tool_args["commands"] = normalized_cmds

        # == Execute tool (with retry on failure) ==============================
        # Hard cap: abort if too many tool calls this turn (prevents spam)
        if tool_calls_this_turn >= MAX_TOOL_CALLS_PER_TURN:
            ctx.add_step({"decision": "capped"}, f"[Tool cap: {MAX_TOOL_CALLS_PER_TURN} calls reached]")
            break

        ctx.state = SystemState.EXECUTING_TOOL

        # Capture pre-action screen state for verification
        pre_hash = ""
        if _needs_perception(tool_name, tool_args):
            pre_hash = _capture_screen_hash()

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
        _advance_todo_progress()

        # == Post-action perception + verification =============================
        perception_result = _perceive_after_action(tool_name, tool_args, ctx)
        if perception_result:
            ctx.add_step({"decision": "perceive", "tool": "vision"}, perception_result)
            result = f"{result}\n\nPerception:\n{perception_result}"

        # Verify the action had visible effect
        changed, verify_msg = _verify_action_effect(pre_hash, tool_name, tool_args, ctx)
        if verify_msg:
            ctx.add_step({"decision": "verify"}, verify_msg)
            result = f"{result}\n{verify_msg}"

        # If action had no effect, inject a hint for the planner
        if not changed and ctx.verification_failures <= config.MAX_VERIFICATION_FAILURES:
            working_request += (
                "\n\n[WARNING: Last action did not change the screen. "
                "The element may not have been found, or the action failed. "
                "Consider retrying with different coordinates or approach.]"
            )
        elif not changed and ctx.verification_failures > config.MAX_VERIFICATION_FAILURES:
            ctx.add_step({"decision": "stuck"}, "[Repeated verification failures - breaking]")
            return (
                "I've tried this action multiple times but the screen isn't changing. "
                "The target element may not be visible or interactable. "
                "What should I try instead?"
            )

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
            ctx.add_step({"decision": "stuck"}, "[Loop detected -- breaking]")
            return (
                "I seem to be stuck in a loop -- the same tool keeps returning the same output.\n"
                f"Last output: {result[:200]}\n"
                "What should I do differently?"
            )

        # Summarize large outputs before injecting into planning context
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

    # == Final LLM response ====================================================
    ctx.state = SystemState.IDLE

    # Inject memory context into the system prompt so the LLM treats it
    # as background knowledge rather than echoing it back to the user.
    system_prompt = persona_prompt
    if memory_context.strip():
        system_prompt += (
            "\n\n[Background context -- use this to inform your answers, "
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
        print(f"[AgentLoop] {selected_model} failed: {e} -- falling back to {config.CHAT_MODEL}")
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
