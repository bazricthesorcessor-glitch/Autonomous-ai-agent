# ========================= core/brain.py =========================
"""Central brain helpers for AVRIL.

The brain is responsible for:
  - classifying user intent
  - generating an initial structured task plan
  - recommending tool routing
  - selecting the single primary reasoning model
"""

from __future__ import annotations

import re

import config

INTENT_CATEGORIES = (
    "simple_chat",
    "homework_question",
    "task_request",
    "memory_store",
    "system_command",
    "information_lookup",
    "automation_task",
)

_SYSTEM_COMMAND_HINTS = {
    "run", "execute", "terminal", "shell", "command", "install", "service",
    "systemctl", "journalctl", "nmcli", "git ", "python ", "pip ", "npm ",
    "launch", "start app", "restart", "stop",
}

_AUTOMATION_HINTS = {
    "open", "search", "click", "type", "press", "scroll", "navigate",
    "youtube", "browser", "website", "page", "tab", "window", "gui",
    "screen", "ocr", "screenshot", "desktop", "firefox", "chrome",
}

_MEMORY_HINTS = {
    "remember", "don't forget", "do not forget", "save this", "store this",
    "my name is", "i like", "i prefer", "my favorite", "note that",
}

_LOOKUP_HINTS = {
    "look up", "lookup", "find information", "find out", "who is", "what is",
    "when did", "where is", "latest", "news", "search the web", "fetch",
    "wikipedia", "tell me about",
}

_HOMEWORK_HINTS = {
    "derivative", "integral", "prove", "equation", "calculate", "solve",
    "homework", "assignment", "x^", "x²", "probability", "statistics",
    "physics", "chemistry", "math", "algebra", "geometry",
}

_SIMPLE_CHAT_HINTS = {
    "hi", "hello", "hey", "thanks", "thank you", "how are you", "what's up",
    "who are you", "your name", "good morning", "good night",
}

_BROWSER_HINTS = {
    "http://", "https://", "www.", "youtube", "google", "gmail", "wikipedia",
    "duckduckgo", "web", "browser", "site", "page",
}

_APP_HINTS = {
    "terminal", "kate", "vscode", "settings", "file manager", "app", "application",
}

_MATH_EXPR_RE = re.compile(r"(?<!\w)(?:\d+(?:\.\d+)?|[()+\-*/%]|\*\*)+(?!\w)")


def _contains_any(message: str, words: set[str]) -> bool:
    return any(token in message for token in words)


def classify_intent(user_input: str) -> str:
    """Classify a user message into one of the supported brain categories."""
    msg = user_input.strip().lower()
    if not msg:
        return "simple_chat"

    if _contains_any(msg, _MEMORY_HINTS):
        return "memory_store"
    if _contains_any(msg, _SYSTEM_COMMAND_HINTS):
        return "system_command"
    if _contains_any(msg, _AUTOMATION_HINTS):
        return "automation_task"
    if _contains_any(msg, _HOMEWORK_HINTS) or _MATH_EXPR_RE.search(msg):
        return "homework_question"
    if _contains_any(msg, _LOOKUP_HINTS) or msg.startswith(("who ", "what ", "when ", "where ", "why ", "how ")):
        return "information_lookup"
    if _contains_any(msg, _SIMPLE_CHAT_HINTS):
        return "simple_chat"
    return "task_request"


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


def _browser_plan(user_input: str) -> list[str]:
    query = user_input.strip().rstrip(".?!")
    return [
        "open the target site or browser context",
        "wait for the page to reach READY state",
        "locate the required UI element with the vision interface",
        "execute the next atomic browser or GUI action",
        f"verify the visible result for: {query[:80]}",
    ]


def _system_plan(user_input: str) -> list[str]:
    return [
        "inspect the target application or command context",
        "run the required safe command or launch action",
        "capture the system output or window state",
        "verify the requested change completed successfully",
    ]


def _lookup_plan(user_input: str) -> list[str]:
    return [
        "search or fetch the relevant source",
        "extract the key facts needed to answer",
        "verify the result matches the request",
    ]


def _homework_plan(user_input: str) -> list[str]:
    return [
        "extract the problem statement",
        "use the Python computation tool when calculation is needed",
        "verify the result before responding",
    ]


def generate_todo_plan(user_input: str, category: str | None = None) -> list[str]:
    """Generate a structured step-by-step plan for actionable requests."""
    category = category or classify_intent(user_input)
    if category == "automation_task":
        return _browser_plan(user_input) if _contains_any(user_input.lower(), _BROWSER_HINTS) else [
            "inspect the current screen or app state",
            "locate the required desktop element with vision",
            "execute the next atomic GUI action",
            "verify the UI changed as expected",
        ]
    if category == "system_command":
        return _system_plan(user_input)
    if category == "information_lookup":
        return _lookup_plan(user_input)
    if category == "homework_question":
        return _homework_plan(user_input)
    if category == "task_request":
        return [
            "understand the requested goal and constraints",
            "select the best tool or subsystem for the next step",
            "execute the next step",
            "verify progress toward the goal",
        ]
    if category == "memory_store":
        return [
            "extract the fact that should be remembered",
            "store it in memory",
            "confirm the stored detail",
        ]
    return []


def recommend_tool(user_input: str, category: str | None = None) -> str:
    """Return the best initial tool family for the request."""
    msg = user_input.lower()
    category = category or classify_intent(user_input)

    if category == "homework_question":
        return "code" if _MATH_EXPR_RE.search(msg) or _contains_any(msg, _HOMEWORK_HINTS) else "web"
    if category == "information_lookup":
        return "web"
    if category == "system_command":
        return "window_manager" if _contains_any(msg, _APP_HINTS) else "terminal_safe"
    if category == "automation_task":
        return "browser_control" if _contains_any(msg, _BROWSER_HINTS) else "vision"
    if category == "memory_store":
        return "utilities"
    return ""


def analyze_request(user_input: str) -> dict:
    """Build the initial decision packet used by the agent loop."""
    category = classify_intent(user_input)
    todo = generate_todo_plan(user_input, category)
    preferred_tool = recommend_tool(user_input, category)
    needs_plan = category in {"automation_task", "system_command", "task_request", "information_lookup", "homework_question"}
    return {
        "category": category,
        "title": build_task_title(user_input, category),
        "preferred_tool": preferred_tool,
        "todo": todo,
        "needs_plan": needs_plan and bool(todo),
        "uses_browser": _contains_any(user_input.lower(), _BROWSER_HINTS),
    }


def format_analysis_for_prompt(analysis: dict) -> str:
    """Serialize the initial brain analysis into prompt-friendly text."""
    todo = analysis.get("todo", [])
    todo_block = "\n".join(f"  {i + 1}. {step}" for i, step in enumerate(todo)) or "  (none)"
    preferred_tool = analysis.get("preferred_tool") or "none"
    return (
        "BRAIN ANALYSIS\n"
        f"Intent category: {analysis.get('category', 'task_request')}\n"
        f"Preferred tool: {preferred_tool}\n"
        f"Needs structured plan: {bool(analysis.get('needs_plan'))}\n"
        "TODO plan:\n"
        f"{todo_block}"
    )


def route(user_input: str) -> str:
    """Return AVRIL's single primary reasoning model."""
    _ = user_input
    return config.PRIMARY_MODEL


def initialize_brain():
    print(f"[Brain] Primary model ready: {config.PRIMARY_MODEL}")
