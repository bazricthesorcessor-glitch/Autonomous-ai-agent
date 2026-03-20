# ========================= core/brain.py =========================
"""Central brain helpers for AVRIL.

Responsibilities:
  - classify user intent (English + Hinglish + mixed)
  - extract actionable targets (URL, app, query, click target)
  - generate context-aware structured task plans
  - recommend tool routing
  - normalize action commands before execution
  - select the primary reasoning model
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
    "file_operation",
    "code_task",
)

# ══════════════════════════════════════════════════════════════════════════════
# KEYWORD HINT SETS
# ══════════════════════════════════════════════════════════════════════════════

_SYSTEM_COMMAND_HINTS = {
    # English
    "run", "execute", "terminal", "shell", "command", "install", "service",
    "systemctl", "journalctl", "nmcli", "git ", "python ", "pip ", "npm ",
    "launch", "start app", "restart", "stop", "reboot", "shutdown", "suspend",
    "close app", "kill process", "check network", "connect wifi", "disconnect",
    "close the current window", "close window", "kill app", "force quit",
    "check wifi", "ping", "traceroute", "ifconfig", "ip addr",
    "mount", "unmount", "chmod", "chown", "df", "du",
    # Hinglish
    "band karo", "band kar do", "band kar", "chalu kar", "chalu karo",
    "install karo", "install kar do", "uninstall karo", "delete karo",
    "restart karo", "reboot karo", "terminal kholo", "command chalao",
    "wifi connect karo", "wifi band karo", "network check karo",
}

_AUTOMATION_HINTS = {
    # English — interaction verbs
    "open", "search", "click", "type", "press", "scroll", "navigate",
    "paste", "drag", "drop", "drag and drop", "right click", "double click",
    "double-click", "right-click", "middle click",
    "hover", "highlight", "select all", "copy", "cut",
    "zoom in", "zoom out", "resize", "move window",
    # Browser / web navigation
    "youtube", "browser", "website", "page", "tab", "gui",
    "screen", "screenshot", "desktop",
    "play", "video", "watch", "stream", "download", "upload", "bookmark",
    "fill out", "fill in", "submit", "login", "log in", "sign in", "sign up",
    "next page", "previous page", "go back", "refresh", "reload",
    "close tab", "new tab", "switch tab", "what do you see",
    "go to", "visit", "navigate to", "open link",
    # Hinglish
    "kholo", "kholna", "khol do", "khol kar",
    "click karo", "click kar", "click karna",
    "type karo", "type kar", "type karna", "likho", "likh do",
    "press karo", "press kar",
    "scroll karo", "scroll kar", "scroll karna",
    "paste karo", "paste kar",
    "copy karo", "copy kar",
    "search karo", "search kar", "dhundo", "dhundho", "dhundna",
    "youtube kholo", "youtube par jao", "youtube pe jao",
    "browser kholo", "website kholo", "tab kholo",
    "download karo", "download kar",
    "login karo", "login kar", "sign in karo",
}

_MEMORY_HINTS = {
    # English
    "remember", "don't forget", "do not forget", "save this", "store this",
    "my name is", "i like", "i prefer", "my favorite", "my favourite",
    "note that", "keep in mind", "make a note",
    "remind me", "set a reminder", "add reminder", "add to list",
    "shopping list", "grocery list", "errand", "errands",
    "i am", "i'm", "my age", "my birthday", "my address",
    "my email", "my phone", "my password",
    # Hinglish
    "yaad rakhna", "yaad dilana", "yaad kar", "yaad rakh",
    "note kar", "note karo", "likh le", "likh lo", "likh kar",
    "save kar", "store kar", "list mein daal", "shopping mein daal",
    "reminder set kar", "remind karna", "bhul mat", "bhulna mat",
    "mera naam", "mujhe pasand", "meri favourite", "mera favourite",
}

_LOOKUP_HINTS = {
    # English
    "look up", "lookup", "find information", "find out", "who is", "what is",
    "when did", "where is", "latest", "news", "search the web", "fetch",
    "wikipedia", "tell me about", "capital of", "how many", "how much",
    "price of", "cost of", "what's the", "what are the", "define",
    "meaning of", "translate", "explain what", "summarize this",
    "who won", "when was", "where was",
    # Hinglish
    "batao", "bata do", "kya hai", "kaun hai", "kab tha", "kahan hai",
    "kya hota hai", "matlab kya", "matlab batao",
    "news kya hai", "kya hua", "latest kya hai",
    "price kya hai", "kitne ka", "kitna hai",
}

_HOMEWORK_HINTS = {
    # Math / science
    "derivative", "integral", "prove", "equation", "calculate", "solve",
    "differentiate", "integrate", "simplify", "factorise", "factorize",
    "homework", "assignment", "x^", "x²", "x³",
    "probability", "statistics", "permutation", "combination",
    "physics", "chemistry", "math", "maths", "algebra", "geometry",
    "trigonometry", "calculus", "matrix", "determinant", "vector",
    "multiply", "divide", "addition", "subtraction",
    "newton", "kirchhoff", "ohm", "bernoulli",
    # CS / DSA homework
    "time complexity", "space complexity", "big o", "algorithm", "sort",
    "binary search", "linked list", "tree traversal", "graph", "bfs", "dfs",
    # Hinglish
    "solve karo", "solve kar do", "calculate karo", "calculate kar do",
    "homework solve", "question solve",
}

_SIMPLE_CHAT_HINTS = {
    # English greetings / small talk
    "hi", "hello", "hey", "thanks", "thank you", "how are you", "what's up",
    "who are you", "your name", "good morning", "good night", "good afternoon",
    "good evening", "tell me a joke", "joke", "what do you think",
    "are you there", "you there", "ping",
    # Hinglish
    "kya haal", "kya kar raha", "kya kiya", "kaisa hai", "kya hua",
    "kya chal raha", "kaise ho", "theek ho", "tune kya", "tumne kya",
    "aapne kya", "kal kya", "aaj kya", "bata", "batao", "suno",
    "kya soch", "kya laga", "kya feel", "mazaa aaya", "thak gaya",
    "kya scene hai", "kya baat hai", "chalo",
}

_FILE_HINTS = {
    # English
    "read file", "open file", "save file", "write to file", "create file",
    "delete file", "rename file", "move file", "copy file",
    "read the file", "show file", "list files", "find file",
    "file contents", "open folder", "open directory",
    # Hinglish
    "file kholo", "file padhna", "file save karo", "file bana do",
    "file delete karo", "folder kholo",
}

_CODE_HINTS = {
    "write code", "write a script", "write a function", "write a program",
    "create a script", "build a script", "code for", "program for",
    "make a function", "implement", "code this", "script this",
    "write python", "write javascript", "write java", "write c++",
    "debug this", "fix this code", "what's wrong with this code",
    "refactor", "optimize this code",
    # Hinglish
    "code likhna", "code likh do", "script bana do", "program bana do",
}

_BROWSER_HINTS = {
    "http://", "https://", "www.", "youtube", "google", "gmail", "wikipedia",
    "duckduckgo", "web", "browser", "site", "page", "chatgpt", "chat.openai",
    "instagram", "facebook", "reddit", "twitter", "x.com", "linkedin",
    "netflix", "spotify", "amazon", "twitch", "discord", "notion",
    "stackoverflow", "github", "claude.ai",
}

_APP_HINTS = {
    # System apps
    "terminal", "konsole", "alacritty", "kitty", "gnome-terminal",
    "kate", "gedit", "mousepad", "nano", "vim", "nvim",
    "vscode", "vs code", "code", "codium",
    "settings", "system settings", "gnome settings",
    "file manager", "dolphin", "nautilus", "thunar", "nemo",
    "firefox", "chrome", "chromium", "brave",
    # Media
    "vlc", "mpv", "rhythmbox", "spotify",
    # Productivity
    "libreoffice", "writer", "calc", "impress",
    "app", "application",
}

# Sub-routing hints ────────────────────────────────────────────────────────────

_VISION_ACTION_HINTS = {
    "click the", "click on the", "tap the", "press the button",
    "select the", "choose the", "pick the",
    "first", "second", "third", "fourth", "fifth",
    "1st", "2nd", "3rd", "4th", "5th",
    "that button", "that link", "that video", "that image", "that icon",
    "what do you see", "what's on the screen", "what is on screen",
    "what's visible", "describe the screen",
    "type hello", "type in the", "type into",
    "double click", "right click",
}

_DOM_ACTION_HINTS = {
    "search youtube", "search google", "search for",
    "open youtube", "open google", "open gmail", "open chatgpt",
    "open wikipedia", "open duckduckgo", "open instagram", "open reddit",
    "type in the search", "fill in", "enter text",
    "submit the form", "log in to", "sign in to",
    "download this", "download the",
}

# ── Regex patterns ────────────────────────────────────────────────────────────

_MATH_EXPR_RE = re.compile(r"(?<!\w)(?:\d+(?:\.\d+)?|[()+\-*/%]|\*\*)+(?!\w)")

_URL_RE = re.compile(r'https?://\S+')

_SEARCH_QUERY_RE = re.compile(
    r'(?:search|look\s+up|find|google|bing)\s+'
    r'(?:on\s+)?(?:youtube|google|the\s+web|duckduckgo|wikipedia|for)?\s*'
    r'(?:for\s+)?(.+)',
    re.IGNORECASE,
)

_CLICK_RE = re.compile(
    r'(?:click|tap|press|select|choose|hit)\s+(?:on\s+)?(?:the\s+)?(.+)',
    re.IGNORECASE,
)

# Catches "open X", "go to X", "navigate to X", "visit X", "launch X"
_OPEN_SITE_RE = re.compile(
    r'(?:open|go\s+to|navigate\s+to|visit|launch|start|load)\s+(?:up\s+)?(\S+)',
    re.IGNORECASE,
)

# Catches "play X", "watch X", "find X on youtube", "put on X", "stream X"
_PLAY_RE = re.compile(
    r'(?:play|watch|find|put\s+on|start|stream|listen\s+to)\s+(.+?)'
    r'(?:\s+(?:on|from|in|at)\s+\w+)?$',
    re.IGNORECASE,
)

# Catches "type X", "type X in the Y", "enter X"
_TYPE_RE = re.compile(
    r'(?:type|enter|write|input)\s+["\']?(.+?)["\']?'
    r'(?:\s+(?:in|into|on|at)\s+.+)?$',
    re.IGNORECASE,
)

_ORDINAL_RE = re.compile(
    r'(first|second|third|fourth|fifth|\d+(?:st|nd|rd|th))\s+(.+)',
    re.IGNORECASE,
)

# ── Site-to-URL mapping (comprehensive) ──────────────────────────────────────

_SITE_URLS = {
    "youtube":       "https://youtube.com",
    "google":        "https://google.com",
    "gmail":         "https://mail.google.com",
    "wikipedia":     "https://en.wikipedia.org",
    "duckduckgo":    "https://duckduckgo.com",
    "github":        "https://github.com",
    "chatgpt":       "https://chat.openai.com",
    "reddit":        "https://reddit.com",
    "twitter":       "https://twitter.com",
    "x":             "https://x.com",
    "instagram":     "https://instagram.com",
    "facebook":      "https://facebook.com",
    "linkedin":      "https://linkedin.com",
    "netflix":       "https://netflix.com",
    "spotify":       "https://open.spotify.com",
    "amazon":        "https://amazon.in",
    "twitch":        "https://twitch.tv",
    "discord":       "https://discord.com/app",
    "notion":        "https://notion.so",
    "stackoverflow": "https://stackoverflow.com",
    "claude":        "https://claude.ai",
    "claude.ai":     "https://claude.ai",
    "whatsapp":      "https://web.whatsapp.com",
    "maps":          "https://maps.google.com",
    "drive":         "https://drive.google.com",
    "docs":          "https://docs.google.com",
    "sheets":        "https://sheets.google.com",
    "meet":          "https://meet.google.com",
}

# ── Action command normalization ──────────────────────────────────────────────

_ACTION_CMD_RE = re.compile(
    r'^(CLICK|TYPE|SCROLL|WAIT|PRESS|MOVE)(?:\s+(.+))?$',
    re.IGNORECASE,
)


def normalize_action_command(raw_command: str) -> str | None:
    """Validate and normalize an executor action command string.

    Valid formats:
        CLICK x y
        TYPE x y text   (legacy)  OR  TYPE text  (MAI-UI style — no coords needed)
        SCROLL x y up|down [amount]
        WAIT seconds
        PRESS key
        MOVE x y
    Returns normalized string or None if invalid.
    """
    raw = raw_command.strip()
    match = _ACTION_CMD_RE.match(raw)
    if not match:
        return None

    op = match.group(1).upper()
    rest = (match.group(2) or "").strip()

    if not rest and op not in ("WAIT",):
        return None

    try:
        parts = shlex.split(rest)
    except ValueError:
        parts = rest.split()

    if not parts:
        return None

    if op in ("CLICK", "MOVE"):
        if len(parts) >= 2:
            try:
                x, y = int(parts[0]), int(parts[1])
                return f"{op} {x} {y}"
            except ValueError:
                pass
        return None

    if op == "TYPE":
        # Legacy: TYPE x y text
        if len(parts) >= 3:
            try:
                x, y = int(parts[0]), int(parts[1])
                text = rest.split(None, 2)[2] if len(rest.split(None, 2)) > 2 else ""
                if text:
                    return f"TYPE {x} {y} {text}"
            except (ValueError, IndexError):
                pass
        # MAI-UI style: TYPE text (no coords — executor types at current focus)
        if parts:
            return f"TYPE {rest}"
        return None

    if op == "SCROLL":
        if len(parts) >= 3:
            try:
                x, y = int(parts[0]), int(parts[1])
                direction = parts[2].lower()
                if direction not in ("up", "down", "left", "right"):
                    return None
                amount = int(parts[3]) if len(parts) > 3 else 3
                return f"SCROLL {x} {y} {direction} {amount}"
            except ValueError:
                pass
        return None

    if op == "WAIT":
        if not rest:
            return "WAIT 1"
        try:
            seconds = float(parts[0])
            return f"WAIT {seconds}"
        except ValueError:
            return None

    if op == "PRESS":
        if parts:
            return f"PRESS {parts[0]}"
        return None

    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _contains_any(message: str, words: set) -> bool:
    """Substring match — good for multi-word phrases."""
    return any(token in message for token in words)


def _contains_any_word(message: str, words: set) -> bool:
    """Word-boundary match — avoids 'hi' matching 'third'."""
    for token in words:
        if " " in token:
            if token in message:
                return True
        else:
            if re.search(r'(?:^|\s)' + re.escape(token) + r'(?:\s|$|[!?.,])', message):
                return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# INTENT CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════

_ACTION_VERBS = {
    "click", "type", "press", "scroll", "open", "search", "download",
    "navigate", "close", "launch", "run", "install", "execute", "submit",
    "paste", "drag", "drag and drop", "right click", "double click",
    "go to", "visit", "play", "watch", "fill", "login", "sign in",
    # Hinglish
    "kholo", "click karo", "type karo", "scroll karo", "download karo",
    "dhundo", "band karo", "chalu karo",
}


def classify_intent(user_input: str) -> str:
    """Classify user message into a brain category.

    Order matters — most specific categories first.
    """
    msg = user_input.strip().lower()
    if not msg:
        return "simple_chat"

    has_action_verb = _contains_any(msg, _ACTION_VERBS)

    # 1. Simple chat — only if no action verb present
    if not has_action_verb and _contains_any_word(msg, _SIMPLE_CHAT_HINTS):
        return "simple_chat"

    # 2. Memory store
    if _contains_any_word(msg, _MEMORY_HINTS):
        return "memory_store"

    # 3. File operation (before system command catches "open")
    if _contains_any(msg, _FILE_HINTS):
        return "file_operation"

    # 4. Code task
    if _contains_any(msg, _CODE_HINTS):
        return "code_task"

    # 5. Desktop app launch/close → system_command (before automation catches "open")
    if _contains_any_word(msg, _APP_HINTS) and not _contains_any(msg, _BROWSER_HINTS):
        return "system_command"
    if _contains_any(msg, _SYSTEM_COMMAND_HINTS):
        return "system_command"

    # 6. Automation (web + GUI interaction)
    if _contains_any(msg, _AUTOMATION_HINTS):
        return "automation_task"

    # 7. Homework / computation
    if _contains_any(msg, _HOMEWORK_HINTS) or _MATH_EXPR_RE.search(msg):
        return "homework_question"

    # 8. Information lookup
    if (
        _contains_any(msg, _LOOKUP_HINTS)
        or msg.startswith(("who ", "what ", "when ", "where ", "why "))
        or (msg.startswith("how ") and not has_action_verb)
    ):
        return "information_lookup"

    # 9. Generic fallback
    return "task_request"


# ══════════════════════════════════════════════════════════════════════════════
# TARGET EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def _extract_targets(user_input: str) -> dict:
    """Extract actionable targets from user input using regex.

    Returns:
        {
            "url":          str | None,
            "app":          str | None,
            "search_query": str | None,
            "click_target": str | None,
            "site":         str | None,
            "type_text":    str | None,
        }
    """
    msg       = user_input.strip()
    msg_lower = msg.lower()

    targets = {
        "url":          None,
        "app":          None,
        "search_query": None,
        "click_target": None,
        "site":         None,
        "type_text":    None,
    }

    # ── Explicit URL ─────────────────────────────────────────────────────────
    url_match = _URL_RE.search(msg)
    if url_match:
        targets["url"] = url_match.group(0)

    # ── Site name ────────────────────────────────────────────────────────────
    for site_name in sorted(_SITE_URLS, key=len, reverse=True):  # longest first avoids "x" eating "x.com"
        if site_name in msg_lower:
            targets["site"] = site_name
            if not targets["url"]:
                targets["url"] = _SITE_URLS[site_name]
            break

    # ── Search query ─────────────────────────────────────────────────────────
    search_match = _SEARCH_QUERY_RE.search(msg)
    if search_match:
        targets["search_query"] = search_match.group(1).strip().rstrip(".!?")
    else:
        play_match = _PLAY_RE.search(msg)
        if play_match:
            targets["search_query"] = play_match.group(1).strip().rstrip(".!?")

    # ── Click target ─────────────────────────────────────────────────────────
    click_match = _CLICK_RE.search(msg)
    if click_match:
        targets["click_target"] = click_match.group(1).strip().rstrip(".!?")

    # ── Type text ────────────────────────────────────────────────────────────
    type_match = _TYPE_RE.search(msg)
    if type_match:
        targets["type_text"] = type_match.group(1).strip().rstrip(".!?")

    # ── App name (only if no browser/site involved) ───────────────────────────
    if not targets["site"] and not targets["url"]:
        open_match = _OPEN_SITE_RE.search(msg)
        if open_match:
            candidate = open_match.group(1).strip().lower().rstrip(".,!?")
            if candidate in _SITE_URLS:
                targets["site"] = candidate
                targets["url"]  = _SITE_URLS[candidate]
            elif _contains_any_word(candidate, _APP_HINTS) or candidate in {
                "firefox", "chrome", "chromium", "brave", "kate", "dolphin",
                "konsole", "alacritty", "kitty", "thunar", "nautilus", "gedit",
                "mousepad", "code", "vscode", "vlc", "mpv", "settings",
            }:
                targets["app"] = candidate

    return targets


# ══════════════════════════════════════════════════════════════════════════════
# TASK TITLE
# ══════════════════════════════════════════════════════════════════════════════

def build_task_title(user_input: str, category: str | None = None) -> str:
    """Create a short task title from the request."""
    category = category or classify_intent(user_input)
    cleaned  = re.sub(r"\s+", " ", user_input).strip(" .,!?")
    if not cleaned:
        return "Task"
    words = cleaned.split()
    title = " ".join(words[:6])
    prefixes = {
        "automation_task":   "Automate:",
        "system_command":    "System:",
        "homework_question": "Solve:",
        "file_operation":    "File:",
        "code_task":         "Code:",
        "information_lookup":"Lookup:",
    }
    prefix = prefixes.get(category, "")
    return f"{prefix} {title}".strip() if prefix else title


# ══════════════════════════════════════════════════════════════════════════════
# PLAN GENERATORS
# ══════════════════════════════════════════════════════════════════════════════

def _youtube_plan(targets: dict) -> list[str]:
    """YouTube: keyboard + vision (MAI-UI). Never Playwright."""
    search_query = targets.get("search_query", "")
    steps = [
        "focus Firefox window via hyprctl (Hyprland native)",
        "open YouTube search results URL directly via firefox CLI",
        f"wait for YouTube search results page to load (query: '{search_query}')",
        "use vision.locate to find first video result",
        "executor CLICK on coordinates returned by vision",
        "verify video started playing",
    ]
    return steps


def _website_plan(user_input: str, targets: dict) -> list[str]:
    """Generic website: open URL + MAI-UI interaction (browser_control.open + computer_use.mai_ui_act)."""
    site  = targets.get("site", "")
    url   = targets.get("url", "https://duckduckgo.com")
    sq    = targets.get("search_query")
    click = targets.get("click_target")
    ttext = targets.get("type_text")

    steps = [
        f"open {url} in Firefox (computer_use open_url)",
        "wait for page to load (vision wait_ready)",
    ]

    if sq:
        steps.append(f"use computer_use mai_ui_act to find search input and type '{sq}'")
        steps.append("use computer_use mai_ui_act to press Enter / submit search")
        steps.append("wait for results to load")
        steps.append("use vision locate or computer_use mai_ui_act to interact with results")
    elif click:
        steps.append(f"use computer_use mai_ui_act to click '{click}'")
        steps.append("wait for response and verify change")
    elif ttext:
        steps.append(f"use computer_use mai_ui_act to find input field and type '{ttext}'")
        steps.append("use computer_use mai_ui_act to submit")
    else:
        steps.append("use vision list_elements to inspect visible UI")
        steps.append("use computer_use mai_ui_act to perform required interaction")
        steps.append("verify result on screen")

    steps.append("task complete")
    return steps


def _gui_action_plan(user_input: str, targets: dict) -> list[str]:
    """Desktop GUI: MAI-UI vision + executor (no OCR, no YOLO)."""
    click_target = targets.get("click_target")
    search_query = targets.get("search_query")
    type_text    = targets.get("type_text")
    msg_lower    = user_input.strip().lower()

    steps = ["capture current screen with MAI-UI (vision list_elements or screenshot)"]

    if click_target:
        ordinal_match = _ORDINAL_RE.search(click_target)
        if ordinal_match:
            ordinal  = ordinal_match.group(1)
            element  = ordinal_match.group(2)
            steps.append(f"use vision locate to find {ordinal} {element.strip()}")
        else:
            steps.append(f"use vision locate to find '{click_target}'")
        steps.append("executor CLICK at coordinates returned by vision")
        steps.append("capture post-click screenshot to verify change")

    elif type_text or "type" in msg_lower or search_query:
        text = type_text or search_query or "the requested text"
        steps.append("use vision locate to find the target input field")
        steps.append("executor CLICK to focus the input field")
        steps.append(f"executor TYPE '{text}'")
        steps.append("capture post-type screenshot to verify")

    elif "scroll" in msg_lower:
        direction = "down" if "down" in msg_lower else "up"
        steps.append(f"executor SCROLL {direction}")
        steps.append("verify screen content has shifted")

    elif "right click" in msg_lower or "right-click" in msg_lower:
        steps.append("use vision locate to find the target element")
        steps.append("executor right-click at coordinates returned by vision")
        steps.append("verify context menu appeared")

    elif "double click" in msg_lower or "double-click" in msg_lower:
        steps.append("use vision locate to find the target element")
        steps.append("executor double-click at coordinates returned by vision")
        steps.append("verify action triggered")

    else:
        steps.append("use computer_use mai_ui_act to perform the requested action")
        steps.append("capture post-action screenshot and verify change")

    return steps


def _system_plan_contextual(user_input: str, targets: dict) -> list[str]:
    """System commands and app control."""
    app       = targets.get("app")
    msg_lower = user_input.strip().lower()

    if "screenshot" in msg_lower:
        return [
            "capture current screen using screenshot tool",
            "store and return the captured data",
        ]

    if any(w in msg_lower for w in ("close", "kill", "quit", "terminate")):
        return [
            "identify the target window or process",
            "send close/kill command via window_manager or terminal_safe",
            "verify the window/process is gone",
        ]

    if any(w in msg_lower for w in ("stop everything", "stop all", "abort all")):
        return [
            "identify all running tasks and processes",
            "cancel active AI tasks",
            "confirm shutdown complete",
        ]

    if "restart" in msg_lower or "reboot" in msg_lower:
        return [
            "warn user about restart",
            "execute restart/reboot command via terminal_safe",
        ]

    if "wifi" in msg_lower or "network" in msg_lower:
        return [
            "check current network status via terminal_safe (nmcli or ip)",
            "perform the requested network action",
            "verify connectivity",
        ]

    if "install" in msg_lower:
        pkg = re.search(r'install\s+(\S+)', msg_lower)
        pkg_name = pkg.group(1) if pkg else "the package"
        return [
            f"verify {pkg_name} is not already installed",
            f"install {pkg_name} via terminal_safe (pacman/pip/npm)",
            "verify installation succeeded",
        ]

    if app:
        return [
            f"check if {app} is already running",
            f"launch {app} using window_manager",
            f"verify {app} window opened",
        ]

    return [
        "inspect the target application or command context",
        "run the required command via terminal_safe or window_manager",
        "capture output and verify the change completed",
    ]


def _lookup_plan(user_input: str) -> list[str]:
    msg_lower = user_input.strip().lower()
    if "wikipedia" in msg_lower:
        return [
            "query Wikipedia via web tool",
            "extract and summarize the relevant section",
            "present a concise answer",
        ]
    return [
        "search the web for the relevant information",
        "retrieve and extract the answer",
        "present a concise explanation",
    ]


def _homework_plan(user_input: str) -> list[str]:
    msg_lower = user_input.strip().lower()
    if any(w in msg_lower for w in ("code", "algorithm", "implement", "program")):
        return [
            "interpret the problem and requirements",
            "design the algorithm or approach",
            "implement using the code execution tool",
            "test and verify the output",
            "present the solution with explanation",
        ]
    return [
        "interpret the mathematical or scientific expression",
        "compute the result using the Python execution tool",
        "verify the answer with a check step",
        "present the answer with step-by-step explanation",
    ]


def _memory_plan(user_input: str) -> list[str]:
    return [
        "extract the key fact or reminder from the message",
        "store it via the remember or facts engine",
        "confirm the stored data back to user",
    ]


def _file_plan(user_input: str, targets: dict) -> list[str]:
    msg_lower = user_input.strip().lower()
    if "read" in msg_lower or "show" in msg_lower or "open" in msg_lower:
        return [
            "locate the target file via file_search",
            "read contents using files tool",
            "present the relevant contents",
        ]
    if "write" in msg_lower or "save" in msg_lower or "create" in msg_lower:
        return [
            "determine file path and content",
            "write file using files tool",
            "verify file was created successfully",
        ]
    if "delete" in msg_lower or "remove" in msg_lower:
        return [
            "confirm the target file path",
            "delete file using files tool (with safety check)",
            "verify deletion",
        ]
    return [
        "locate the target file",
        "perform the requested file operation",
        "verify the result",
    ]


def _code_plan(user_input: str) -> list[str]:
    return [
        "understand the coding task and language requirements",
        "design the solution structure",
        "write the code",
        "test with sample inputs via code execution tool",
        "present the final code with explanation",
    ]


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PLAN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def generate_todo_plan(user_input: str, category: str | None = None) -> list[str]:
    """Generate a structured step-by-step plan for actionable requests."""
    category = category or classify_intent(user_input)
    targets  = _extract_targets(user_input)

    if category == "automation_task":
        msg_lower = user_input.strip().lower()
        site = targets.get("site", "")

        # YouTube always uses keyboard + vision bypass
        if site == "youtube" or "youtube" in msg_lower:
            return _youtube_plan(targets)

        # Other websites
        if (
            _contains_any(msg_lower, _BROWSER_HINTS)
            or targets.get("url")
            or targets.get("site")
            or _contains_any(msg_lower, _DOM_ACTION_HINTS)
        ):
            return _website_plan(user_input, targets)

        # Desktop GUI
        return _gui_action_plan(user_input, targets)

    if category == "system_command":
        return _system_plan_contextual(user_input, targets)

    if category == "information_lookup":
        return _lookup_plan(user_input)

    if category == "homework_question":
        return _homework_plan(user_input)

    if category == "memory_store":
        return _memory_plan(user_input)

    if category == "file_operation":
        return _file_plan(user_input, targets)

    if category == "code_task":
        return _code_plan(user_input)

    if category == "task_request":
        return [
            "understand the requested goal and constraints",
            "select the best tool or subsystem for the next step",
            "execute the first action",
            "verify progress toward the goal",
            "complete remaining steps and confirm done",
        ]

    return []


# ══════════════════════════════════════════════════════════════════════════════
# TOOL ROUTING
# ══════════════════════════════════════════════════════════════════════════════

def recommend_tool(user_input: str, category: str | None = None) -> str:
    """Return the best initial tool family for the request."""
    msg      = user_input.lower()
    category = category or classify_intent(user_input)

    if category == "homework_question":
        return "code"

    if category == "information_lookup":
        return "web"

    if category == "file_operation":
        return "file_search"

    if category == "code_task":
        return "code"

    if category == "system_command":
        if "screenshot" in msg:
            return "screenshot"
        if any(w in msg for w in ("stop everything", "stop all", "abort all")):
            return "task_manager"
        if any(w in msg for w in ("close", "kill")) and any(w in msg for w in ("window", "app")):
            return "window_manager"
        if _contains_any_word(msg, _APP_HINTS):
            return "window_manager"
        return "terminal_safe"

    if category == "automation_task":
        if "screenshot" in msg:
            return "screenshot"

        # YouTube: keyboard + vision only
        if "youtube" in msg:
            return "executor"

        # App launch (not a website)
        if _contains_any_word(msg, _APP_HINTS) and not _contains_any(msg, _BROWSER_HINTS):
            return "window_manager"

        # Any website task → computer_use (mai_ui_act) after opening URL
        if (
            _contains_any(msg, _BROWSER_HINTS)
            or _contains_any(msg, _DOM_ACTION_HINTS)
            or _extract_targets(user_input).get("url")
        ):
            return "computer_use"

        # Vision-hint actions (locate + click)
        if _contains_any(msg, _VISION_ACTION_HINTS):
            return "vision"

        # Scroll, generic GUI
        if "scroll" in msg:
            return "computer_use"

        # Default GUI: MAI-UI
        return "computer_use"

    if category == "memory_store":
        return "remember"

    return ""


# ══════════════════════════════════════════════════════════════════════════════
# EXECUTION NOTES
# ══════════════════════════════════════════════════════════════════════════════

def _build_execution_notes(user_input: str, category: str, preferred_tool: str) -> str:
    """Generate a 1-sentence execution approach note."""
    msg_lower = user_input.strip().lower()

    if category == "simple_chat":
        return "Respond conversationally."

    if category == "homework_question":
        return "Use Python execution tool for computation; show step-by-step working."

    if category == "information_lookup":
        return "Use web search tool to find the answer."

    if category == "memory_store":
        return "Extract the fact and write to remember/facts engine."

    if category == "file_operation":
        return "Use file_search and files tool for all file operations."

    if category == "code_task":
        return "Write, test, and verify code using the code execution tool."

    if category == "system_command":
        if preferred_tool == "screenshot":
            return "Use screenshot tool to capture current screen."
        if preferred_tool == "task_manager":
            return "Stop all active tasks safely."
        if preferred_tool == "window_manager":
            return "Use hyprctl or window_manager to control the window/app."
        return "Use terminal_safe for controlled command execution."

    if category == "automation_task":
        if "youtube" in msg_lower:
            return "Use executor keyboard shortcuts + MAI-UI vision to control YouTube in Firefox."
        if preferred_tool == "computer_use":
            return "Open URL via computer_use, then use mai_ui_act to interact with the page."
        if preferred_tool == "vision":
            return "MAI-UI vision returns coordinates; executor performs the action."
        return "Use computer_use mai_ui_act for direct GUI interaction."

    return "Select appropriate tool and execute step by step."


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ANALYSIS ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def analyze_request(user_input: str, user_ctx=None) -> dict:
    """Build the initial decision packet used by the agent loop.

    Returns:
        {
            category, task_title, preferred_tool, todo_plan,
            needs_plan, execution_notes, uses_browser, mode
        }
    """
    category        = classify_intent(user_input)
    todo_plan       = generate_todo_plan(user_input, category)
    preferred_tool  = recommend_tool(user_input, category)
    execution_notes = _build_execution_notes(user_input, category, preferred_tool)

    needs_plan = category in {
        "automation_task", "system_command", "task_request",
        "information_lookup", "homework_question", "memory_store",
        "file_operation", "code_task",
    }

    try:
        if user_ctx is None:
            from core.context_enricher import build_user_context
            user_ctx = build_user_context()
        mode = user_ctx.detected_mode
    except Exception:
        mode = "general"

    return {
        "category":        category,
        "task_title":      build_task_title(user_input, category),
        "preferred_tool":  preferred_tool,
        "todo_plan":       todo_plan,
        "needs_plan":      needs_plan and bool(todo_plan),
        "execution_notes": execution_notes,
        "uses_browser":    _contains_any(user_input.lower(), _BROWSER_HINTS),
        "mode":            mode,
    }


def format_analysis_for_prompt(analysis: dict) -> str:
    """Serialize the brain analysis into prompt-friendly text."""
    todo = analysis.get("todo_plan", analysis.get("todo", []))
    todo_block = "\n".join(f"  {i + 1}. {step}" for i, step in enumerate(todo)) or "  (none)"
    return (
        "BRAIN ANALYSIS\n"
        f"Intent category: {analysis.get('category', 'task_request')}\n"
        f"Preferred tool: {analysis.get('preferred_tool') or 'none'}\n"
        f"Mode: {analysis.get('mode', 'general')}\n"
        f"Needs structured plan: {bool(analysis.get('needs_plan'))}\n"
        f"Execution approach: {analysis.get('execution_notes', '')}\n"
        "TODO plan:\n"
        f"{todo_block}"
    )


# ── Model routing ─────────────────────────────────────────────────────────────

def route(user_input: str) -> str:
    """Return the primary reasoning model."""
    _ = user_input
    return config.PRIMARY_MODEL


def initialize_brain():
    print(f"[Brain] Primary model ready: {config.PRIMARY_MODEL}")


# ── Training examples ─────────────────────────────────────────────────────────

TRAINING_EXAMPLES = [
    {"input": "hi",                        "category": "simple_chat",       "preferred_tool": "",             "needs_plan": False},
    {"input": "kaise ho",                  "category": "simple_chat",       "preferred_tool": "",             "needs_plan": False},
    {"input": "search youtube for lofi",   "category": "automation_task",   "preferred_tool": "executor",     "needs_plan": True},
    {"input": "open firefox",              "category": "system_command",    "preferred_tool": "window_manager","needs_plan": True},
    {"input": "click the login button",    "category": "automation_task",   "preferred_tool": "vision",       "needs_plan": True},
    {"input": "what is photosynthesis",    "category": "information_lookup","preferred_tool": "web",          "needs_plan": True},
    {"input": "solve x^2 + 3x = 10",      "category": "homework_question", "preferred_tool": "code",         "needs_plan": True},
    {"input": "remember i like coffee",    "category": "memory_store",      "preferred_tool": "remember",     "needs_plan": True},
    {"input": "read the file notes.txt",   "category": "file_operation",    "preferred_tool": "file_search",  "needs_plan": True},
    {"input": "write a python script",     "category": "code_task",         "preferred_tool": "code",         "needs_plan": True},
    {"input": "install neovim",            "category": "system_command",    "preferred_tool": "terminal_safe","needs_plan": True},
    {"input": "go to instagram",           "category": "automation_task",   "preferred_tool": "computer_use", "needs_plan": True},
    {"input": "scroll down",              "category": "automation_task",   "preferred_tool": "computer_use", "needs_plan": True},
    {"input": "right click on the icon",  "category": "automation_task",   "preferred_tool": "vision",       "needs_plan": True},
    {"input": "double click the file",    "category": "automation_task",   "preferred_tool": "vision",       "needs_plan": True},
    {"input": "paste the text",           "category": "automation_task",   "preferred_tool": "computer_use", "needs_plan": True},
    {"input": "yaad rakhna mera password","category": "memory_store",      "preferred_tool": "remember",     "needs_plan": True},
    {"input": "youtube kholo aur lofi",   "category": "automation_task",   "preferred_tool": "executor",     "needs_plan": True},
]