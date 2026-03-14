# ========================= core/brain.py =========================
"""Central brain helpers for AVRIL.

The brain is responsible for:
  - classifying user intent
  - extracting actionable targets from input
  - generating context-aware structured task plans
  - recommending tool routing with sub-category awareness
  - normalizing action commands before execution
  - selecting the single primary reasoning model
"""

from __future__ import annotations

import re
import shlex

import config

# ── Intent categories ────────────────────────────────────────────────────────

INTENT_CATEGORIES = (
    "simple_chat",
    "homework_question",
    "task_request",
    "memory_store",
    "system_command",
    "information_lookup",
    "automation_task",
)

# ── Keyword hint sets ────────────────────────────────────────────────────────

_SYSTEM_COMMAND_HINTS = {
    "run", "execute", "terminal", "shell", "command", "install", "service",
    "systemctl", "journalctl", "nmcli", "git ", "python ", "pip ", "npm ",
    "launch", "start app", "restart", "stop",
    "close app", "kill process", "check network", "connect wifi", "disconnect",
    "close the current window", "close window",
}

_AUTOMATION_HINTS = {
    "open", "search", "click", "type", "press", "scroll", "navigate",
    "youtube", "browser", "website", "page", "tab", "gui",
    "screen", "ocr", "screenshot", "desktop",
    "play", "video", "watch", "stream", "download", "upload", "bookmark",
    "fill out", "fill in", "submit", "login", "log in", "sign in", "sign up",
    "next page", "previous page", "go back", "refresh", "reload",
    "close tab", "new tab", "switch tab", "what do you see",
}

_MEMORY_HINTS = {
    "remember", "don't forget", "do not forget", "save this", "store this",
    "my name is", "i like", "i prefer", "my favorite", "note that",
}

_LOOKUP_HINTS = {
    "look up", "lookup", "find information", "find out", "who is", "what is",
    "when did", "where is", "latest", "news", "search the web", "fetch",
    "wikipedia", "tell me about", "capital of",
}

_HOMEWORK_HINTS = {
    "derivative", "integral", "prove", "equation", "calculate", "solve",
    "homework", "assignment", "x^", "x\u00b2", "probability", "statistics",
    "physics", "chemistry", "math", "algebra", "geometry", "multiply",
}

_SIMPLE_CHAT_HINTS = {
    "hi", "hello", "hey", "thanks", "thank you", "how are you", "what's up",
    "who are you", "your name", "good morning", "good night",
    "tell me a joke", "joke",
}

_BROWSER_HINTS = {
    "http://", "https://", "www.", "youtube", "google", "gmail", "wikipedia",
    "duckduckgo", "web", "browser", "site", "page", "chatgpt", "chat.openai",
}

_APP_HINTS = {
    "terminal", "kate", "vscode", "settings", "file manager", "app",
    "application", "firefox", "chrome",
}

# Sub-routing hints for automation_task ────────────────────────────────────────

_VISION_ACTION_HINTS = {
    "click the", "click on the", "tap the", "press the button",
    "select the", "choose the", "pick the",
    "first", "second", "third", "fourth", "fifth",
    "1st", "2nd", "3rd", "4th", "5th",
    "that button", "that link", "that video", "that image",
    "what do you see", "what's on the screen", "what is on screen",
    "type hello", "type in the",
}

_DOM_ACTION_HINTS = {
    "search youtube", "search google", "search for",
    "open youtube", "open google", "open gmail", "open chatgpt",
    "open wikipedia", "open duckduckgo",
    "type in the search", "fill in", "enter text",
    "submit the form", "log in to", "sign in to",
    "download this", "download the",
}

# ── Regex patterns ───────────────────────────────────────────────────────────

_MATH_EXPR_RE = re.compile(r"(?<!\w)(?:\d+(?:\.\d+)?|[()+\-*/%]|\*\*)+(?!\w)")

_URL_RE = re.compile(r'https?://\S+')

_SEARCH_QUERY_RE = re.compile(
    r'search\s+(?:on\s+)?(?:youtube|google|the\s+web|duckduckgo|wikipedia)?\s*'
    r'(?:for\s+)?(.+)',
    re.IGNORECASE,
)

_CLICK_RE = re.compile(
    r'click\s+(?:on\s+)?(?:the\s+)?(.+)',
    re.IGNORECASE,
)

_OPEN_SITE_RE = re.compile(
    r'open\s+(?:up\s+)?(\S+)',
    re.IGNORECASE,
)

_ORDINAL_RE = re.compile(
    r'(first|second|third|fourth|fifth|\d+(?:st|nd|rd|th))\s+(.+)',
    re.IGNORECASE,
)

# ── Site-to-URL mapping ─────────────────────────────────────────────────────

_SITE_URLS = {
    "youtube": "https://youtube.com",
    "google": "https://google.com",
    "gmail": "https://mail.google.com",
    "wikipedia": "https://en.wikipedia.org",
    "duckduckgo": "https://duckduckgo.com",
    "github": "https://github.com",
    "chatgpt": "https://chat.openai.com",
    "reddit": "https://reddit.com",
    "twitter": "https://twitter.com",
    "x": "https://x.com",
}

# ── Action command normalization ─────────────────────────────────────────────

_ACTION_CMD_RE = re.compile(
    r'^(CLICK|TYPE|SCROLL|WAIT|PRESS|MOVE)\s+(.+)$',
    re.IGNORECASE,
)


def normalize_action_command(raw_command: str) -> str | None:
    """Validate and normalize an action command string.

    Returns the normalized command string, or None if invalid.

    Valid formats:
        CLICK x y
        TYPE x y text
        SCROLL x y up|down [amount]
        WAIT seconds
        PRESS key
        MOVE x y
    """
    raw = raw_command.strip()
    match = _ACTION_CMD_RE.match(raw)
    if not match:
        return None

    op = match.group(1).upper()
    rest = match.group(2).strip()

    try:
        parts = shlex.split(rest)
    except ValueError:
        parts = rest.split()

    if not parts:
        return None

    if op in ("CLICK", "MOVE") and len(parts) >= 2:
        try:
            x, y = int(parts[0]), int(parts[1])
            return f"{op} {x} {y}"
        except ValueError:
            return None

    if op == "TYPE" and len(parts) >= 3:
        try:
            x, y = int(parts[0]), int(parts[1])
            # Everything after x y is the text
            text = rest.split(None, 2)[2] if len(rest.split(None, 2)) > 2 else ""
            if not text:
                return None
            return f"TYPE {x} {y} {text}"
        except (ValueError, IndexError):
            return None

    if op == "SCROLL" and len(parts) >= 3:
        try:
            x, y = int(parts[0]), int(parts[1])
            direction = parts[2].lower()
            if direction not in ("up", "down"):
                return None
            amount = int(parts[3]) if len(parts) > 3 else 3
            return f"SCROLL {x} {y} {direction} {amount}"
        except ValueError:
            return None

    if op == "WAIT" and len(parts) >= 1:
        try:
            seconds = float(parts[0])
            return f"WAIT {seconds}"
        except ValueError:
            return None

    if op == "PRESS" and len(parts) >= 1:
        return f"PRESS {parts[0]}"

    return None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _contains_any(message: str, words: set[str]) -> bool:
    return any(token in message for token in words)


def _contains_any_word(message: str, words: set[str]) -> bool:
    """Match whole phrases/words — avoids substring false positives like 'hi' in 'third'."""
    for token in words:
        # Multi-word phrases: direct substring match is fine (specific enough)
        if " " in token:
            if token in message:
                return True
        else:
            # Single-word tokens: require word boundary
            if re.search(r'(?:^|\s)' + re.escape(token) + r'(?:\s|$|[!?.,])', message):
                return True
    return False


# ── Intent classification ────────────────────────────────────────────────────

def classify_intent(user_input: str) -> str:
    """Classify a user message into one of the supported brain categories."""
    msg = user_input.strip().lower()
    if not msg:
        return "simple_chat"

    # Simple chat FIRST — catches greetings, "how are you", "tell me a joke"
    # Uses word-boundary matching to avoid false positives (e.g., "hi" in "third")
    # BUT: skip if the message contains action verbs (e.g., "type hello" is automation)
    _ACTION_VERBS = {
        "click", "type", "press", "scroll", "open", "search", "download",
        "navigate", "close", "launch", "run", "install", "execute", "submit",
    }
    has_action_verb = _contains_any_word(msg, _ACTION_VERBS)
    if not has_action_verb and _contains_any_word(msg, _SIMPLE_CHAT_HINTS):
        return "simple_chat"
    if _contains_any(msg, _MEMORY_HINTS):
        return "memory_store"

    # Desktop app launch/close → system_command (before automation catches "open")
    if _contains_any(msg, _APP_HINTS):
        return "system_command"
    if _contains_any(msg, _SYSTEM_COMMAND_HINTS):
        return "system_command"

    if _contains_any(msg, _AUTOMATION_HINTS):
        return "automation_task"
    if _contains_any(msg, _HOMEWORK_HINTS) or _MATH_EXPR_RE.search(msg):
        return "homework_question"
    if _contains_any(msg, _LOOKUP_HINTS) or msg.startswith(("who ", "what ", "when ", "where ", "why ", "how ")):
        return "information_lookup"
    return "task_request"


# ── Target extraction ────────────────────────────────────────────────────────

def _extract_targets(user_input: str) -> dict:
    """Extract actionable targets from user input using regex patterns.

    Returns:
        {
            "url": str | None,
            "app": str | None,
            "search_query": str | None,
            "click_target": str | None,
            "site": str | None,
        }
    """
    msg = user_input.strip()
    msg_lower = msg.lower()

    targets = {
        "url": None,
        "app": None,
        "search_query": None,
        "click_target": None,
        "site": None,
    }

    # Extract explicit URL
    url_match = _URL_RE.search(msg)
    if url_match:
        targets["url"] = url_match.group(0)

    # Detect site name
    for site_name in _SITE_URLS:
        if site_name in msg_lower:
            targets["site"] = site_name
            if not targets["url"]:
                targets["url"] = _SITE_URLS[site_name]
            break

    # Extract search query
    search_match = _SEARCH_QUERY_RE.search(msg)
    if search_match:
        targets["search_query"] = search_match.group(1).strip().rstrip(".!?")

    # Extract click target
    click_match = _CLICK_RE.search(msg)
    if click_match:
        targets["click_target"] = click_match.group(1).strip().rstrip(".!?")

    # Extract app name (only if not a browser site)
    if not targets["site"] and not targets["url"]:
        open_match = _OPEN_SITE_RE.search(msg)
        if open_match:
            candidate = open_match.group(1).strip().lower()
            # Check if it's a known site
            if candidate in _SITE_URLS:
                targets["site"] = candidate
                targets["url"] = _SITE_URLS[candidate]
            elif _contains_any(candidate, _APP_HINTS) or candidate in {
                "firefox", "chrome", "kate", "dolphin", "konsole",
                "thunar", "nautilus", "gedit", "code", "vscode",
            }:
                targets["app"] = candidate

    return targets


# ── Task title ───────────────────────────────────────────────────────────────

def build_task_title(user_input: str, category: str | None = None) -> str:
    """Create a short task title from the request."""
    category = category or classify_intent(user_input)
    cleaned = re.sub(r"\s+", " ", user_input).strip(" .,!?")
    if not cleaned:
        return "Task"
    words = cleaned.split()
    title = " ".join(words[:6])
    if category == "automation_task":
        return f"Automate: {title}"
    if category == "system_command":
        return f"System: {title}"
    if category == "homework_question":
        return f"Solve: {title}"
    return title


# ── Context-aware plan generators ────────────────────────────────────────────

def _browser_plan_contextual(user_input: str, targets: dict) -> list[str]:
    """Generate a context-aware browser automation plan."""
    steps = []
    site = targets.get("site")
    url = targets.get("url") or _SITE_URLS.get(site or "", "")
    search_query = targets.get("search_query")
    click_target = targets.get("click_target")

    if url:
        steps.append(f"open {url} using browser_control")
        steps.append("wait for page to reach READY state")
    else:
        steps.append("open the target website using browser_control")
        steps.append("wait for page to reach READY state")

    if search_query:
        steps.append("locate the search input field")
        steps.append(f"type '{search_query}' into the search field")
        steps.append("press Enter to submit the search")
        steps.append("wait for results page to reach READY state")

    if click_target:
        steps.append(f"locate '{click_target}' on the page")
        steps.append("click the target element")

    steps.append("verify the visible result matches the request")
    return steps


def _system_plan_contextual(user_input: str, targets: dict) -> list[str]:
    """Generate a context-aware system command plan."""
    app = targets.get("app")
    msg_lower = user_input.strip().lower()

    if "screenshot" in msg_lower:
        return [
            "capture current screen using screenshot tool",
            "store screenshot result",
            "return the captured data",
        ]

    if "close" in msg_lower or "kill" in msg_lower:
        return [
            "identify the target window or process",
            "send close/kill command via window_manager",
            "verify the window/process is gone",
        ]

    if "stop" in msg_lower and ("everything" in msg_lower or "all" in msg_lower):
        return [
            "identify all running tasks",
            "cancel active tasks",
            "confirm shutdown",
        ]

    if app:
        return [
            f"check if {app} is already running",
            f"launch {app} using window_manager",
            f"verify {app} window opened",
        ]

    return [
        "inspect the target application or command context",
        "run the required safe command or launch action",
        "capture the system output or window state",
        "verify the requested change completed successfully",
    ]


def _gui_action_plan(user_input: str, targets: dict) -> list[str]:
    """Plan for non-browser GUI automation (vision + executor)."""
    click_target = targets.get("click_target")
    search_query = targets.get("search_query")
    msg_lower = user_input.strip().lower()

    steps = ["capture current screen state (screenshot + OCR)"]

    if click_target:
        # Check for ordinal reference
        ordinal_match = _ORDINAL_RE.search(click_target)
        if ordinal_match:
            ordinal, element = ordinal_match.group(1), ordinal_match.group(2)
            steps.append(f"scan screen for list of {element.strip()} elements")
            steps.append(f"identify the {ordinal} element position")
            steps.append("click the target element via executor")
        else:
            steps.append(f"locate '{click_target}' using vision.locate")
            steps.append("click at returned coordinates via executor")
    elif search_query or "type" in msg_lower:
        steps.append("locate the target input field using vision.locate")
        steps.append("click the input field via executor")
        text = search_query or "the requested text"
        steps.append(f"type '{text}' via executor")
    elif "scroll" in msg_lower:
        steps.append("identify the active window or scroll area")
        steps.append("execute scroll action via executor")
        steps.append("verify the screen content has shifted")
        return steps
    else:
        steps.append("analyze visible elements to identify the action target")
        steps.append("locate the required UI element using vision.locate")
        steps.append("execute the atomic GUI action via executor")

    steps.append("capture post-action screenshot and verify change")
    return steps


def _lookup_plan(user_input: str) -> list[str]:
    return [
        "search the relevant information source",
        "retrieve and extract the answer",
        "present a concise explanation",
    ]


def _homework_plan(user_input: str) -> list[str]:
    return [
        "interpret the mathematical expression or problem",
        "compute the result using the python execution tool",
        "present the answer with explanation",
    ]


def _memory_plan(user_input: str) -> list[str]:
    return [
        "extract the important fact from the message",
        "store the fact in memory",
        "confirm the stored data",
    ]


# ── Plan generation ──────────────────────────────────────────────────────────

def generate_todo_plan(user_input: str, category: str | None = None) -> list[str]:
    """Generate a structured step-by-step plan for actionable requests."""
    category = category or classify_intent(user_input)
    targets = _extract_targets(user_input)

    if category == "automation_task":
        msg_lower = user_input.strip().lower()
        # Browser-based tasks
        if _contains_any(msg_lower, _BROWSER_HINTS) or _contains_any(msg_lower, _DOM_ACTION_HINTS):
            return _browser_plan_contextual(user_input, targets)
        # GUI / vision-based tasks
        return _gui_action_plan(user_input, targets)

    if category == "system_command":
        return _system_plan_contextual(user_input, targets)
    if category == "information_lookup":
        return _lookup_plan(user_input)
    if category == "homework_question":
        return _homework_plan(user_input)
    if category == "memory_store":
        return _memory_plan(user_input)
    if category == "task_request":
        return [
            "understand the requested goal and constraints",
            "select the best tool or subsystem for the next step",
            "execute the next step",
            "verify progress toward the goal",
        ]
    return []


# ── Tool routing ─────────────────────────────────────────────────────────────

def recommend_tool(user_input: str, category: str | None = None) -> str:
    """Return the best initial tool family for the request."""
    msg = user_input.lower()
    category = category or classify_intent(user_input)

    if category == "homework_question":
        return "code"

    if category == "information_lookup":
        return "web"

    if category == "system_command":
        if "screenshot" in msg or "take a screenshot" in msg:
            return "screenshot"
        if "stop everything" in msg or "stop all" in msg:
            return "task_manager"
        if "close" in msg and ("window" in msg or "app" in msg):
            return "window_manager"
        if _contains_any(msg, _APP_HINTS):
            return "window_manager"
        return "terminal_safe"

    if category == "automation_task":
        # Sub-routing: app launch vs vision vs browser_control
        if "screenshot" in msg or "take a screenshot" in msg:
            return "screenshot"
        if _contains_any(msg, _APP_HINTS) and not _contains_any(msg, _BROWSER_HINTS):
            return "window_manager"
        if _contains_any(msg, _VISION_ACTION_HINTS):
            return "vision"
        if _contains_any(msg, _BROWSER_HINTS) or _contains_any(msg, _DOM_ACTION_HINTS):
            return "browser_control"
        # Scroll, generic GUI
        if "scroll" in msg:
            return "computer_use"
        return "vision"

    if category == "memory_store":
        return "utilities"

    return ""


# ── Execution notes ──────────────────────────────────────────────────────────

def _build_execution_notes(user_input: str, category: str, preferred_tool: str) -> str:
    """Generate a 1-sentence execution approach note."""
    msg_lower = user_input.strip().lower()

    if category == "simple_chat":
        return "Respond conversationally."

    if category == "homework_question":
        return "Use python execution tool for computation if needed."

    if category == "information_lookup":
        return "Use web search tool to find the answer."

    if category == "memory_store":
        return "Extract the fact and write to facts.json."

    if category == "system_command":
        if preferred_tool == "screenshot":
            return "Use screenshot tool to capture current screen."
        if preferred_tool == "task_manager":
            return "Stop all active tasks safely."
        if preferred_tool == "window_manager":
            return "Use hyprctl or window_manager commands."
        return "Use terminal_safe for controlled command execution."

    if category == "automation_task":
        if preferred_tool == "browser_control":
            site = ""
            for s in _SITE_URLS:
                if s in msg_lower:
                    site = s
                    break
            if site:
                return f"Use browser_control DOM automation for {site}."
            return "Use browser_control for DOM-based web automation."
        if preferred_tool == "vision":
            return "Vision model returns coordinates, executor performs the action."
        if preferred_tool == "computer_use":
            return "Use computer_use for direct GUI interaction."
        return "Use vision for perception, executor for actions."

    return "Select appropriate tool and execute step by step."


# ── Main analysis entry point ────────────────────────────────────────────────

def analyze_request(user_input: str) -> dict:
    """Build the initial decision packet used by the agent loop.

    Returns a structured analysis with:
        category, task_title, preferred_tool, todo_plan,
        needs_plan, execution_notes, uses_browser
    """
    category = classify_intent(user_input)
    todo_plan = generate_todo_plan(user_input, category)
    preferred_tool = recommend_tool(user_input, category)
    execution_notes = _build_execution_notes(user_input, category, preferred_tool)
    needs_plan = category in {
        "automation_task", "system_command", "task_request",
        "information_lookup", "homework_question", "memory_store",
    }
    return {
        "category": category,
        "task_title": build_task_title(user_input, category),
        "preferred_tool": preferred_tool,
        "todo_plan": todo_plan,
        "needs_plan": needs_plan and bool(todo_plan),
        "execution_notes": execution_notes,
        "uses_browser": _contains_any(user_input.lower(), _BROWSER_HINTS),
    }


def format_analysis_for_prompt(analysis: dict) -> str:
    """Serialize the initial brain analysis into prompt-friendly text."""
    todo = analysis.get("todo_plan", analysis.get("todo", []))
    todo_block = "\n".join(f"  {i + 1}. {step}" for i, step in enumerate(todo)) or "  (none)"
    preferred_tool = analysis.get("preferred_tool") or "none"
    execution_notes = analysis.get("execution_notes", "")
    return (
        "BRAIN ANALYSIS\n"
        f"Intent category: {analysis.get('category', 'task_request')}\n"
        f"Preferred tool: {preferred_tool}\n"
        f"Needs structured plan: {bool(analysis.get('needs_plan'))}\n"
        f"Execution approach: {execution_notes}\n"
        "TODO plan:\n"
        f"{todo_block}"
    )


# ── Model routing ────────────────────────────────────────────────────────────

def route(user_input: str) -> str:
    """Return AVRIL's single primary reasoning model."""
    _ = user_input
    return config.PRIMARY_MODEL


def initialize_brain():
    print(f"[Brain] Primary model ready: {config.PRIMARY_MODEL}")


# ── Training examples (reference/validation dataset) ─────────────────────────

TRAINING_EXAMPLES = [
    {"input": "hi", "category": "simple_chat", "preferred_tool": "", "needs_plan": False},
    {"input": "How are you?", "category": "simple_chat", "preferred_tool": "", "needs_plan": False},
    {"input": "What is the derivative of x^2?", "category": "homework_question", "preferred_tool": "code", "needs_plan": True},
    {"input": "Calculate 572 * 941", "category": "homework_question", "preferred_tool": "code", "needs_plan": True},
    {"input": "Open YouTube", "category": "automation_task", "preferred_tool": "browser_control", "needs_plan": True},
    {"input": "Search YouTube for lofi music", "category": "automation_task", "preferred_tool": "browser_control", "needs_plan": True},
    {"input": "Open Firefox", "category": "system_command", "preferred_tool": "window_manager", "needs_plan": True},
    {"input": "Close the current window", "category": "system_command", "preferred_tool": "window_manager", "needs_plan": True},
    {"input": "Remember that my exam is on Monday", "category": "memory_store", "preferred_tool": "utilities", "needs_plan": True},
    {"input": "What is the capital of France?", "category": "information_lookup", "preferred_tool": "web", "needs_plan": True},
    {"input": "Take a screenshot", "category": "automation_task", "preferred_tool": "screenshot", "needs_plan": True},
    {"input": "Scroll down", "category": "automation_task", "preferred_tool": "computer_use", "needs_plan": True},
    {"input": "Search Google for weather in Delhi", "category": "automation_task", "preferred_tool": "browser_control", "needs_plan": True},
    {"input": "Tell me a joke", "category": "simple_chat", "preferred_tool": "", "needs_plan": False},
    {"input": "Open ChatGPT website", "category": "automation_task", "preferred_tool": "browser_control", "needs_plan": True},
    {"input": "Type hello in the search box", "category": "automation_task", "preferred_tool": "vision", "needs_plan": True},
    {"input": "Click the third video", "category": "automation_task", "preferred_tool": "vision", "needs_plan": True},
    {"input": "Download this PDF", "category": "automation_task", "preferred_tool": "browser_control", "needs_plan": True},
    {"input": "What do you see on the screen?", "category": "automation_task", "preferred_tool": "vision", "needs_plan": True},
    {"input": "Stop everything you are doing", "category": "system_command", "preferred_tool": "task_manager", "needs_plan": True},
]
