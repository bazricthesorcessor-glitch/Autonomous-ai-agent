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
from core.context_enricher import build_user_context, format_for_prompt as format_user_context
from tools import registry
from engines import task_manager, todo_manager

# ── Semantic fast classifier ─────────────────────────────────────────────────
# Embedding-based classification for messages that don't match regex patterns.
# Averages embeddings of class exemplars and uses cosine similarity.

_CLASS_EXAMPLES = {
    "greeting": [
        "hi", "hello", "hey", "good morning", "good evening",
        "what's up", "how are you", "thanks", "bye", "see ya",
        "wassup", "howdy", "yo", "hiya", "greetings",
    ],
    "chat": [
        "who are you", "what's your name", "tell me a joke",
        "how do you work", "are you real", "what do you think about",
        "i feel sad today", "i'm bored", "tell me something interesting",
        "do you have feelings", "what's the meaning of life",
    ],
    "teach_me": [
        "explain how", "teach me about", "what is a",
        "how does this work", "why does", "can you explain",
        "what's the difference between", "help me understand",
        "break this down for me", "what are the steps to",
    ],
    "action": [
        "open firefox", "search youtube for", "install this package",
        "run the build", "click the search bar", "type hello",
        "take a screenshot", "download this file", "create a new file",
        "go to google", "play some music", "check my wifi",
    ],
}

_class_embeddings = {}  # {class_name: averaged_embedding}
_class_embeddings_ready = False


def _ensure_class_embeddings():
    """Compute and cache averaged embeddings per class. Called once on first use."""
    global _class_embeddings, _class_embeddings_ready
    if _class_embeddings_ready:
        return

    from engines import memory_engine

    for cls, examples in _CLASS_EXAMPLES.items():
        vectors = []
        for ex in examples:
            emb = memory_engine.get_embedding(ex)
            if emb:
                vectors.append(emb)
        if vectors:
            # Average all exemplar vectors
            dim = len(vectors[0])
            avg = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
            _class_embeddings[cls] = avg

    _class_embeddings_ready = True


def _classify_semantic(msg: str) -> str:
    """Classify a message using embedding cosine similarity against class exemplars.
    Returns: 'greeting' | 'chat' | 'teach_me' | 'action' | 'unknown'
    """
    _ensure_class_embeddings()
    if not _class_embeddings:
        return "unknown"

    from engines import memory_engine

    msg_emb = memory_engine.get_embedding(msg)
    if not msg_emb:
        return "unknown"

    best_cls = "unknown"
    best_score = -1.0
    for cls, cls_emb in _class_embeddings.items():
        score = memory_engine.similarity(msg_emb, cls_emb)
        if score > best_score:
            best_score = score
            best_cls = cls

    # Require a minimum confidence threshold
    if best_score < 0.35:
        return "unknown"

    return best_cls


def warm_classifier():
    """Pre-warm class embeddings on startup (call from background thread)."""
    try:
        _ensure_class_embeddings()
    except Exception:
        pass

client = Client(host='http://localhost:11434')

MAX_STEPS             = 8    # Raised from 3 -- needed for real multi-step tasks
MAX_RETRIES           = 3    # Max consecutive retries on a failing tool
MAX_TOOL_CALLS_PER_TURN = 10  # Hard cap on tool calls per turn -- prevents tool spam
_LOOP_DETECT          = 3    # Abort if this many consecutive results are identical

# == Pending confirmation state (for blocked risky tools) =====================
# Stored across turns so "yes" replies can re-trigger the blocked tool.
_PENDING_CONFIRMATION: dict = {}
_CONFIRM_YES = frozenset({
    'yes', 'haan', 'ok', 'okay', 'sure', 'yeah', 'yep', 'yup', 'allow', 'go ahead',
})
_CONFIRM_NO = frozenset({'no', 'nahi', 'nope', 'cancel', 'abort'})

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
    # Obvious action words → always route to agent
    if _ACTION_WORDS_RE.search(msg):
        return 'agent'
    # Regex fast matches
    if _GREETING_RE.match(msg):
        return 'greeting'
    if _CHAT_RE.match(msg):
        return 'chat'
    # Semantic fallback for ambiguous messages (e.g. "wassup", "you there?")
    sem = _classify_semantic(msg)
    if sem == "greeting":
        return 'greeting'
    if sem in ("chat", "teach_me"):
        return 'chat'
    if sem == "action":
        return 'agent'
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

# Tools that require post-action perception 

_PERCEPTION_TOOLS = {
    "computer_use": {"mai_ui_act", "click_element"},
    "executor":     {"*"},        # all executor actions need verification
    "window_manager": {"open", "launch_app", "focus_window"},
}

# Actions that trigger long-running responses (need monitor_response)

_LONG_RESPONSE_ACTIONS = {
    ("computer_use", "mai_ui_act"),   # replaces browser_control type
    ("executor", "TYPE"),
}

# == Local media fast-path constants (compiled once at module level) ===========
_LOCAL_TRIGGERS = {"next episode", "episode", " ep ", "vlc", "mpv", ".mkv", ".mp4", ".avi"}
_LOCAL_MEDIA_RE = re.compile(
    r'(?:play|watch|open|start)\s+'
    r'(?:(next|previous|last)\s+)?'
    r'(?:ep(?:isode)?\s*\d*\s+(?:of\s+)?)?'
    r'(.+?)(?:\s+(?:on\s+vlc|in\s+vlc|with\s+vlc|on\s+mpv))?$',
    re.IGNORECASE,
)
 

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
  Use a tool      -> {{"decision": "use_tool",   "tool": "<name>", "args": {{...}}, "reason": "<why>", "confidence": 0.9}}
  Start new task  -> {{"decision": "start_task",  "title": "<short title>", "description": "<full goal including all details>", "credentials": {{"wifi_password": "...", "etc": "..."}}, "confidence": 0.8}}
  Task complete   -> {{"decision": "task_done",   "task_id": "<id>", "summary": "<what was done>"}}
  Respond now     -> {{"decision": "respond",     "reason": "<why no tool needed>"}}
  Ask user first  -> {{"decision": "clarify",     "question": "<what you need to know before acting>"}}

Optional fields (any decision):
  "confidence"   -- 0.0 to 1.0, how sure you are.
  "memory_hint"  -- a short fact worth remembering (e.g. "User's wifi SSID is HomeNet"). Will be stored in long-term memory.

Rules:
- The request has already been classified. Respect the provided intent category and TODO plan.
- Treat the TODO plan as the canonical execution checklist. Advance it step by step.
- Use start_task for ANY multi-step goal (install, fix, configure, automate).
  Include ALL details (passwords, ssid, targets) so nothing is forgotten.
- task_done requires task_id -- always specify which task was completed.
  Only mark done after verifying success (take a screenshot to confirm).
- Multiple tasks can run in parallel. task_done applies only to the specified task.
- For automation_task and system_command categories: NEVER use "clarify".
  The TODO plan is already defined. Execute it step by step.
  If something is ambiguous, make a reasonable assumption and proceed.
  Only use "clarify" for memory_store or information_lookup when truly needed.
- For YouTube tasks: follow the TODO plan using executor keyboard steps + vision. NEVER browser_control.
- For other website tasks: follow the TODO plan exactly, one browser_control call per step.
  Do not skip steps. Do not ask if it worked. Just go to the next step.
- TOOL ROUTING:
        1. code            -- math / computation / formula evaluation
        2. web             -- information lookups and fetches
        3. computer_use    -- all website interaction (open URL + mai_ui_act)
        4. vision          -- locate elements, page state, OCR, verify_task
        5. executor        -- atomic GUI actions after vision returns coordinates
        6. window_manager  -- open or focus desktop applications
        7. terminal_safe   -- run controlled commands
        8. screenshot      -- capture screen for context or debugging

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
  ONLY for desktop apps (VS Code, file manager, settings). NEVER for websites.
  Goal: Click Save button in Kate
  Step 1 -> {{"decision": "use_tool", "tool": "vision", "args": {{"action": "locate", "query": "save button", "app": "kate"}}, "reason": "find save button"}}
           -> Returns: {{"coordinates": [234, 45], "state": "FOUND"}}
  Step 2 -> {{"decision": "use_tool", "tool": "executor", "args": {{"command": "CLICK 234 45"}}, "reason": "click save"}}

YOUTUBE AUTOMATION -- use executor + vision (existing Firefox, keyboard-based):
  YouTube ALWAYS uses executor keyboard shortcuts + vision. NEVER use browser_control for YouTube.
  Firefox is already open on Super+1. The plan uses keyboard shortcuts to control it.

  FULL EXAMPLE -- "play Moon Princess by One Piece on YouTube":
    Step 1: {{"decision": "use_tool", "tool": "executor", "args": {{"command": "PRESS super+1"}}, "reason": "focus Firefox"}}
    Step 2: {{"decision": "use_tool", "tool": "executor", "args": {{"command": "WAIT 0.5"}}, "reason": "wait for focus"}}
    Step 3: {{"decision": "use_tool", "tool": "executor", "args": {{"command": "PRESS ctrl+t"}}, "reason": "open new tab"}}
    Step 4: {{"decision": "use_tool", "tool": "executor", "args": {{"command": "PRESS ctrl+l"}}, "reason": "focus address bar"}}
    Step 5: {{"decision": "use_tool", "tool": "executor", "args": {{"command": "TYPE https://www.youtube.com"}}, "reason": "type URL"}}
    Step 6: {{"decision": "use_tool", "tool": "executor", "args": {{"command": "PRESS Return"}}, "reason": "navigate"}}
    Step 7: {{"decision": "use_tool", "tool": "executor", "args": {{"command": "WAIT 3"}}, "reason": "wait for page load"}}
    Step 8: {{"decision": "use_tool", "tool": "vision", "args": {{"action": "locate", "query": "YouTube search input box"}}, "reason": "find search bar"}}
    Step 9: {{"decision": "use_tool", "tool": "executor", "args": {{"command": "CLICK <x> <y>"}}, "reason": "click search bar (use coordinates from Step 8)"}}
    Step 10: {{"decision": "use_tool", "tool": "executor", "args": {{"command": "TYPE Moon Princess One Piece"}}, "reason": "type search query"}}
    Step 11: {{"decision": "use_tool", "tool": "executor", "args": {{"command": "PRESS Return"}}, "reason": "submit search"}}
    Step 12: {{"decision": "use_tool", "tool": "executor", "args": {{"command": "WAIT 3"}}, "reason": "wait for results"}}
    Step 13: {{"decision": "use_tool", "tool": "vision", "args": {{"action": "locate", "query": "best matching video result title or thumbnail for the search query"}}, "reason": "find best matching video"}}
    Step 14: {{"decision": "use_tool", "tool": "executor", "args": {{"command": "CLICK <x> <y>"}}, "reason": "click first video (use coordinates from Step 13)"}}

WEBSITE AUTOMATION -- use computer_use (MAI-UI, screenshot-based):
  For non-YouTube website tasks (Google, Gmail, Reddit, etc.), use computer_use.
  computer_use.open_url opens the site in Firefox.
  computer_use.mai_ui_act takes a screenshot and performs the requested interaction.
  NEVER use browser_control for any interaction — it is a stub and will return errors.

  FULL EXAMPLE -- "search Google for something":
    Step 1: {{"decision": "use_tool", "tool": "computer_use", "args": {{"action": "open_url", "url": "https://google.com"}}, "reason": "open Google"}}
    Step 2: {{"decision": "use_tool", "tool": "vision", "args": {{"action": "wait_ready"}}, "reason": "wait for page"}}
    Step 3: {{"decision": "use_tool", "tool": "computer_use", "args": {{"action": "mai_ui_act", "task": "click the search box and type 'your query'"}}, "reason": "search"}}
    Step 4: {{"decision": "use_tool", "tool": "computer_use", "args": {{"action": "mai_ui_act", "task": "press Enter to submit the search"}}, "reason": "submit"}}

  FULL EXAMPLE -- "open instagram and like the first post":
    Step 1: {{"decision": "use_tool", "tool": "computer_use", "args": {{"action": "open_url", "url": "https://instagram.com"}}, "reason": "open Instagram"}}
    Step 2: {{"decision": "use_tool", "tool": "vision", "args": {{"action": "wait_ready"}}, "reason": "wait for page"}}
    Step 3: {{"decision": "use_tool", "tool": "computer_use", "args": {{"action": "mai_ui_act", "task": "click the like button on the first post"}}, "reason": "like post"}}

DESKTOP APP -- use window_manager (NOT browser_control):
  For apps like kate, terminal, file manager -> use window_manager.
  Example: {{"decision": "use_tool", "tool": "window_manager", "args": {{"action": "open", "app": "kate"}}, "reason": "open kate"}}

DESKTOP APP AUTOMATION -- use vision + executor:
  ONLY for non-browser desktop apps (VS Code, file manager, settings, games).
  Step 1 -> window_manager launch/focus the app
  Step 2 -> vision locate the required element
  Step 3 -> executor run the action with returned coordinates
  Step 4 -> vision verify the change

DECISION RULE:
    Computation?          -> code
    Information lookup?   -> web
    YouTube task?         -> executor + vision (keyboard plan, NEVER browser_control or computer_use)
    Other website?        -> computer_use (open_url then mai_ui_act)
    Desktop GUI?          -> vision then executor
    System/app control?   -> terminal_safe or window_manager
    Deep explanation?     -> cloud_ai
    Verify task done?     -> vision verify_task (video=true for media tasks)

ESCALATION RULE — use cloud_ai when:
  - Task needs deep explanation, derivation, or long-form writing
  - Local model gave an incomplete or uncertain answer
  - Divyansh explicitly asks for a "detailed explanation" or "full answer"
  - Homework problems that need step-by-step working
  - Any request where confidence is low

  cloud_ai args:
    site:   "claude" | "chatgpt" | "gemini" (omit 'site' for auto-select)
    prompt: the full self-contained question (include subject context)

  Example:
    User: "DSD mein flip-flops explain kar do"
    -> {{"decision": "use_tool", "tool": "cloud_ai",
        "args": {{"prompt": "Explain JK, D, T, and SR flip-flops for a Digital System Design exam. Include truth tables and applications."}},
        "reason": "detailed explanation needed"}}

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
    # Try to extract JSON from any code fence block
    if '```' in raw:
        for part in raw.split('```'):
            part = part.strip()
            if part.startswith('json'):
                part = part[4:].strip()
            elif part.startswith('python') or part.startswith('py'):
                # Model wrapped its answer in a python block — not valid JSON
                continue
            if part.startswith('{'):
                try:
                    return json.loads(part)
                except Exception:
                    pass
    # Try to find a bare JSON object anywhere in the text
    start = raw.find('{')
    if start != -1:
        # Walk from rightmost '}' back to find the outermost JSON object
        end = raw.rfind('}')
        if end != -1 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except Exception:
                pass
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


def _build_planner_system(tools_desc: str, active_tasks: list, analysis: dict, user_ctx=None) -> str:
    if active_tasks:
        ctx = task_manager.get_all_tasks_context(active_tasks)
        task_block = f"ACTIVE TASKS (continue working on these):\n{ctx}"
    else:
        task_block = ""

    shortcuts_block = system_shortcuts.get_shortcuts_prompt()
    analysis_block = brain.format_analysis_for_prompt(analysis)

    # User context: time, schedule, mode — use pre-computed if provided
    if user_ctx is None:
        user_ctx = build_user_context()
    user_context_block = format_user_context(user_ctx)

    base = _PLANNER_SYSTEM.format(
        tools_desc=tools_desc,
        analysis_block=analysis_block,
        task_block=task_block,
        shortcuts_block=shortcuts_block,
    )
    return base + f"\n\nUSER CONTEXT:\n{user_context_block}"


def _is_tool_error(result: str) -> bool:
    """Heuristic: check if the tool result indicates a failure."""
    if result is None:
        return True
    lower = result.lower()
    return (
        lower.startswith("error") or
        lower.startswith("[error]") or
        lower.startswith("[blocked]") or
        lower.startswith("[registry]") or
        "not found" in lower[:80] or
        "failed" in lower[:80]
    )


# == Task priority levels ======================================================
# 10: Critical  (security alert, urgent shout)
# 8:  Urgent    (deadline today, explicit "urgent" keyword)
# 5:  Normal    (default — regular tasks, searches)
# 3:  Background (downloads, long research)
# 1:  Idle      (cleanup, summarization)

_URGENT_RE = re.compile(
    r'\b(urgent|emergency|critical|asap|abhi|turant|jaldi|right\s*now|immediately)\b',
    re.IGNORECASE,
)


def _detect_priority(user_message: str, analysis: dict) -> int:
    """Infer task priority from message content and brain analysis."""
    if _URGENT_RE.search(user_message):
        return 8
    category = analysis.get("category", "")
    if category in ("simple_chat", "memory_store"):
        return 0   # does not create a task
    if category == "information_lookup":
        return 3
    return 5  # normal default


def _check_preemption(new_priority: int, ctx: TurnContext) -> bool:
    """
    If a new request has higher priority than the currently running task,
    pause the current task so the new one can be handled first.
    Returns True if preemption happened (current task was paused).
    """
    if new_priority <= 0:
        return False  # non-task messages never preempt

    current = task_manager.get_highest_priority_active()
    if not current:
        return False

    if new_priority > current.get("priority", 5):
        task_manager.pause_task(
            current["id"],
            step_index=len(ctx.steps_taken),
            context={
                "steps": list(ctx.steps_taken),
                "last_result": ctx.steps_taken[-1] if ctx.steps_taken else "",
            },
        )
        print(
            f"[AgentLoop] Preempting task {current['id']} "
            f"(priority {current.get('priority', 5)}) "
            f"for new request (priority {new_priority})"
        )
        return True
    return False


# == YouTube hardcoded plan (bypasses LLM planner — phi4-mini unreliable for this) ====

def _format_verify_result(v: dict, query: str) -> str:
    scene    = v.get("scene",      "unknown")
    conf     = v.get("confidence", 0.0)
    detail   = v.get("detail",     "")
    done     = v.get("done",       False)
    low_conf = v.get("low_confidence", False)
    conf_pct = f"{int(conf * 100)}%"
    if done and not low_conf:
        return f"Playing '{query}' ✓\nScene: {scene} (confidence {conf_pct})\n{detail}"
    if done and low_conf:
        return (f"Playing '{query}' — likely ✓ but low confidence ({conf_pct})\n"
                f"Scene: {scene}\n{detail}")
    return (f"Attempted to play '{query}'.\n"
            f"Scene detected: {scene} (confidence {conf_pct})\n{detail}")


def _run_youtube_plan(search_query: str) -> str:
    """
    Execute the YouTube automation plan directly via executor, bypassing LLM planner.

    Strategy:
      1. Focus Firefox via hyprctl (Hyprland native) or xdotool fallback — NOT super+1,
         which is unreliable and may send keystrokes to AVRIL's own chat input.
      2. Navigate directly to youtube.com/results?search_query=... — skips interacting
         with the search bar entirely (avoids vision dependency).
      3. Use Tab×N + Enter for first video — pure keyboard, no vision needed.
    """
    import time
    import subprocess
    import urllib.parse

    def _exec(cmd: str) -> str:
        result = registry.run("executor", {"command": cmd})
        print(f"[YouTube] {cmd}: {result}")
        return str(result)

    # ── Step 1: Focus Firefox ────────────────────────────────────────────────
    # IMPORTANT: must focus Firefox BEFORE ydotool sends any keystrokes,
    # otherwise they land in AVRIL's chat input box.
    focused = False

    # Try Hyprland IPC first (native Wayland, most reliable on Hyprland)
    r = subprocess.run(
        ["hyprctl", "dispatch", "focuswindow", "class:firefox"],
        capture_output=True, text=True
    )
    if r.returncode == 0:
        focused = True
        print("[YouTube] focused Firefox via hyprctl")

    if not focused:
        # Try xdotool (works via XWayland)
        r2 = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--class", "Navigator"],
            capture_output=True, text=True
        )
        win_ids = r2.stdout.strip().split()
        if win_ids:
            subprocess.run(["xdotool", "windowactivate", "--sync", win_ids[0]], capture_output=True)
            focused = True
            print(f"[YouTube] focused Firefox via xdotool wid={win_ids[0]}")

    if not focused:
        # Last resort: workspace shortcut
        _exec("PRESS super+1")
        print("[YouTube] used super+1 fallback")

    time.sleep(0.4)  # wait for window manager to complete focus switch

    # ── Step 2: Open YouTube search results URL directly via firefox CLI ──────
    # Avoids address-bar typing entirely — no ydotool TYPE, no ctrl+l focus
    # issues. `firefox --new-tab URL` opens in existing Firefox window.
    encoded = urllib.parse.quote_plus(search_query)
    search_url = f"https://www.youtube.com/results?search_query={encoded}"

    subprocess.Popen(["firefox", "--new-tab", search_url])
    time.sleep(0.5)  # brief pause so Firefox registers the new tab command

    # Re-focus Firefox after spawning the subprocess (it may have lost focus)
    subprocess.run(
        ["hyprctl", "dispatch", "focuswindow", "class:firefox"],
        capture_output=True, text=True
    )
    print(f"[YouTube] opening: {search_url}")
    time.sleep(4)  # wait for YouTube search results to load

    # ── Step 3: Click first video using Firefox window geometry ──────────────
    # Use hyprctl to get the exact window position so we can calculate where
    # the first YouTube search result is on screen — no Tab guessing needed.
    import json as _json

    # ── Step 3: Ask mai-ui:2b vision model where to click the first video ────
    # Pass app="firefox" to skip the DOM/AT-SPI layers and go straight to the
    # screenshot-based model (Layer 3). It sees the real screen, returns x,y.
    time.sleep(0.5)  # let page visually settle before screenshot
    vis = registry.run("vision", {
        "action": "locate",
        "query":  f"best matching video result for '{search_query}' — match title text, skip ads and channel cards",
    })
    print(f"[YouTube] vision result: {vis}")

    click_x, click_y = None, None
    try:
        data = _json.loads(vis) if isinstance(vis, str) else vis
        if isinstance(data, dict) and data.get("state") == "FOUND":
            coords = data.get("coordinates", [])
            if coords and len(coords) >= 2:
                click_x, click_y = int(coords[0]), int(coords[1])
    except Exception as e:
        print(f"[YouTube] vision parse failed: {e}")

    if click_x:
        time.sleep(0.2)
        _exec(f"CLICK {click_x} {click_y}")
    else:
        print("[YouTube] vision failed — falling back to geometry click")
        try:
            r = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True)
            ff = next((c for c in _json.loads(r.stdout)
                       if "firefox" in c.get("class", "").lower()), None)
            if ff:
                at = ff.get("at", [0, 0])
                _exec(f"CLICK {at[0] + 400} {at[1] + 220}")
        except Exception as fe:
            print(f"[YouTube] geometry fallback failed: {fe}")

    time.sleep(1.5)
    verify_raw = registry.run("vision", {
        "action": "verify_task",
        "task":   f"play {search_query} on YouTube",
        "video":  True,
    })
    try:
        v = _json.loads(verify_raw)
    except Exception:
        v = {"done": False, "scene": "unknown", "confidence": 0.0,
             "detail": verify_raw, "low_confidence": True}
    return _format_verify_result(v, search_query)


def _run_local_media_plan(show_name: str, episode_hint: str = "next") -> str:
    """Find and play a local media file in VLC/mpv."""

    def _find_episodes(name: str) -> list:
        search_dirs = [
            os.path.expanduser("~/Videos"),
            os.path.expanduser("~/Downloads"),
            os.path.expanduser("~/Movies"),
            "/media", "/mnt", "/home",
        ]
        name_parts = [p for p in re.sub(r'[^a-z0-9 ]', ' ', name.lower()).split() if len(p) > 2]
        found = []
        for d in search_dirs:
            if not os.path.isdir(d):
                continue
            try:
                r = subprocess.run(
                    ["find", d, "-iname", f"*{name.replace(' ', '*')}*", "-type", "f"],
                    capture_output=True, text=True, timeout=10
                )
                for path in r.stdout.strip().splitlines():
                    path = path.strip()
                    if not path or not os.path.isfile(path):
                        continue
                    if not any(path.lower().endswith(ext)
                               for ext in (".mkv", ".mp4", ".avi", ".mov", ".m4v", ".webm")):
                        continue
                    fname_lower = os.path.basename(path).lower()
                    if any(p in fname_lower for p in name_parts):
                        found.append(path)
            except Exception:
                continue
        seen = set()
        unique = [p for p in found if not (p in seen or seen.add(p))]
        def _natural_key(s):
            return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]
        return sorted(unique, key=_natural_key)

    def _get_last_episode(show: str):
        try:
            from engines import memory_engine
            key     = f"last_episode_{re.sub(r'[^a-z0-9]', '_', show.lower())}"
            results = memory_engine.search_memory(key, top_k=1)
            # search_memory returns list of strings
            if results:
                text = results[0]
                if ": " in text:
                    return text.split(": ", 1)[1].strip()
        except Exception:
            pass
        return None

    def _save_last_episode(show: str, path: str) -> None:
        try:
            from engines import memory_engine
            key = f"last_episode_{re.sub(r'[^a-z0-9]', '_', show.lower())}"
            memory_engine.add_memory(f"{key}: {path}")
        except Exception:
            pass

    episodes = _find_episodes(show_name)
    if not episodes:
        return (f"No video files found for '{show_name}'. "
                "Check ~/Videos, ~/Downloads, /media, or /mnt.")

    target_path = None

    ep_num_match = re.search(r'(?:ep(?:isode)?\s*|e)(\d+)', episode_hint, re.IGNORECASE)
    if ep_num_match:
        ep_num = int(ep_num_match.group(1))
        for path in episodes:
            if re.search(rf'(?:ep?|episode|e){ep_num:02d}|[^0-9]{ep_num:02d}[^0-9]',
                         os.path.basename(path), re.IGNORECASE):
                target_path = path
                break

    if not target_path and "next" in episode_hint.lower():
        last = _get_last_episode(show_name)
        if last and last in episodes:
            idx = episodes.index(last)
            if idx + 1 < len(episodes):
                target_path = episodes[idx + 1]
            else:
                return (f"No episode after '{os.path.basename(last)}'. "
                        f"All {len(episodes)} episodes may be watched.")
        else:
            target_path = episodes[0]

    if not target_path:
        target_path = episodes[0]

    print(f"[LocalMedia] Opening: {target_path}")
    try:
        subprocess.Popen(["vlc", "--fullscreen", target_path])
    except FileNotFoundError:
        try:
            subprocess.Popen(["mpv", "--fullscreen", target_path])
        except FileNotFoundError:
            return "VLC and MPV not found. Install: sudo pacman -S vlc"

    time.sleep(1.5)
    ep_name    = os.path.splitext(os.path.basename(target_path))[0]
    verify_raw = registry.run("vision", {
        "action": "verify_task",
        "task":   f"play {ep_name} in VLC",
        "video":  True,
    })
    try:
        v = json.loads(verify_raw)
    except Exception:
        v = {"done": False, "scene": "unknown", "confidence": 0.0,
             "detail": verify_raw, "low_confidence": True}

    if v.get("done"):
        _save_last_episode(show_name, target_path)
    return _format_verify_result(v, ep_name)


# == Main Turn Loop ============================================================

def run_turn(user_message: str, persona_prompt: str, memory_context: str = "") -> str:
    """
    Full agent turn. Returns the final AI response string.
    """
    ctx = TurnContext(user_message)
    ctx.state = SystemState.PLANNING

    tools_desc = registry.describe_tools()
    active_tasks = task_manager.get_active_tasks()

    # == Pending confirmation handler ==========================================
    # Must be FIRST — before the fast path, which would swallow "yes" as a
    # greeting and abandon the blocked tool entirely.
    _confirm = _PENDING_CONFIRMATION.pop('default', None)
    if _confirm:
        msg_lower = user_message.strip().lower()
        if msg_lower in _CONFIRM_YES:
            _c_result = registry.run(_confirm['tool_name'], _confirm['tool_args'])
            if _c_result is None:
                _c_result = "Error: tool returned no output"
            _c_msgs = [
                {'role': 'system',    'content': persona_prompt},
                {'role': 'user',      'content': _confirm['original_message']},
                {'role': 'assistant', 'content': f"[Used {_confirm['tool_name']}]\n{_c_result}"},
                {'role': 'user',      'content': 'Give me the final answer based on the tool result above.'},
            ]
            try:
                _c_resp = client.chat(
                    model=config.PRIMARY_MODEL,
                    messages=_c_msgs,
                    options={'temperature': 0.6, 'num_predict': 600},
                )
                return _sanitize_response(_c_resp['message']['content'])
            except Exception as _ce:
                return _c_result  # fallback: return raw tool output
        else:
            return "Okay, cancelled."

    # == Build user context ONCE — used by fast path AND agent path =============
    # Must come here so greeting/chat responses also see what's playing/focused.
    try:
        _turn_user_ctx = build_user_context()
    except Exception:
        _turn_user_ctx = None

    # == Fast path: Tier 1 (greeting) or Tier 2 (chat) ========================
    # Checked BEFORE analyze_request() and task creation — prevents orphan tasks
    # from being created for greetings misclassified as information_lookup.
    fast = classify_fast_path(user_message) if not active_tasks else 'agent'

    if fast in ('greeting', 'chat'):
        ctx.state = SystemState.IDLE
        system = persona_prompt

        # Inject live system state so the model knows what's playing / focused
        # even when the user just says "hi" or asks a short question.
        if _turn_user_ctx and _turn_user_ctx.system_state_raw:
            system += f"\n\n{_turn_user_ctx.system_state_raw}"

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
        # Use FAST_MODEL for greetings/chat — saves latency vs full PRIMARY_MODEL
        selected_model = config.FAST_MODEL
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

    # == Full agent path — analyze, create tasks, run planner loop ============
    # _turn_user_ctx already built above — reuse, don't rebuild.
    analysis = brain.analyze_request(user_message, user_ctx=_turn_user_ctx)

    # == YouTube fast-path: bypass planner, execute directly ===================
    if (analysis.get('category') == 'automation_task'
            and ('youtube' in user_message.lower() or 'youtube.com' in user_message.lower())):
        # Extract search query from brain targets
        targets = brain._extract_targets(user_message)
        sq = targets.get('search_query')
        if sq:
            ctx.state = SystemState.IDLE
            result = _run_youtube_plan(sq)
            ctx.state = SystemState.IDLE
            return result

    # == Local media fast-path: "play next episode of X", "play X.mkv" =========
    if (
        analysis.get('category') == 'automation_task'
        and any(t in user_message.lower() for t in _LOCAL_TRIGGERS)
        and 'youtube' not in user_message.lower()
        and not any(s in user_message.lower() for s in ('netflix', 'hotstar', 'prime', 'crunchyroll'))
    ):
        m = _LOCAL_MEDIA_RE.search(user_message)
        if m:
            episode_hint = (m.group(1) or "next").strip()
            show_name    = (m.group(2) or "").strip().rstrip(".,!?")
            if show_name:
                ctx.state = SystemState.EXECUTING_TOOL
                result    = _run_local_media_plan(show_name, episode_hint)
                ctx.state = SystemState.IDLE
                return result

    # == Priority preemption check ==============================================
    new_priority = _detect_priority(user_message, analysis)
    _check_preemption(new_priority, ctx)

    if not active_tasks and analysis.get('needs_plan'):
        task_manager.create_task(
            title=analysis.get('task_title', analysis.get('title', 'Task')),
            description=user_message,
            category=analysis.get('category', 'task_request'),
            plan=analysis.get('todo_plan', analysis.get('todo', [])),
            priority=new_priority if new_priority > 0 else 5,
        )
        _sync_initial_todos(analysis.get('todo_plan', analysis.get('todo', [])))
        active_tasks = task_manager.get_active_tasks()

    planner_system = _build_planner_system(tools_desc, active_tasks, analysis, user_ctx=_turn_user_ctx)

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

        # == Store memory hint if present ======================================
        memory_hint = decision.get('memory_hint', '').strip()
        if memory_hint:
            try:
                from engines import memory_engine
                memory_engine.add_memory(memory_hint)
            except Exception:
                pass

        # == Clarify: planner is unsure, ask the user ==========================
        if d_type == 'clarify':
            # Block clarify for automation/system tasks — just execute the plan
            if analysis.get('category') in ('automation_task', 'system_command', 'task_request'):
                working_request += "\n\n[DO NOT clarify. Execute the next step in the TODO plan directly.]"
                continue
            question = decision.get('question', 'Could you clarify what you need?')
            ctx.state = SystemState.IDLE
            return question

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
            planner_system = _build_planner_system(tools_desc, active_tasks, analysis, user_ctx=_turn_user_ctx)
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
                planner_system = _build_planner_system(tools_desc, active_tasks, analysis, user_ctx=_turn_user_ctx)
            break

        # == Respond directly ==================================================
        if d_type != 'use_tool':
            break

        tool_name = decision.get('tool', '')
        tool_args = decision.get('args', {})

        # == Low confidence gate ================================================
        # If planner is unsure (confidence < 0.5), ask instead of guessing
        confidence = decision.get('confidence', 1.0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 1.0
        if confidence < 0.5:
            reason = decision.get('reason', 'this action')
            ctx.state = SystemState.IDLE
            return (
                f"I'm not confident about {reason}. "
                f"Can you confirm or give me more details?"
            )

        # == Permission gate ===================================================
        if not registry.is_safe(tool_name):
            _PENDING_CONFIRMATION['default'] = {
                'tool_name':        tool_name,
                'tool_args':        tool_args,
                'original_message': user_message,
            }
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
            if result is None:
                result = "Error: tool returned no output"
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
            options={'temperature': 0.6, 'num_predict': 600}
        )
        return _sanitize_response(response['message']['content'])
    except Exception as e:
        print(f"[AgentLoop] {selected_model} failed: {e} -- falling back to {config.CHAT_MODEL}")
        if selected_model != config.CHAT_MODEL:
            try:
                response = client.chat(
                    model=config.CHAT_MODEL,
                    messages=messages,
                    options={'temperature': 0.6, 'num_predict': 600}
                )
                return _sanitize_response(response['message']['content'])
            except Exception as e2:
                print(f"[AgentLoop] Fallback also failed: {e2}")
        return f"Sorry, something went wrong: {str(e)}"
