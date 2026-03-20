# ========================= tools/executor.py =========================
"""
Executor tool — atomic GUI action executor.

Performs mouse/keyboard actions using ydotool (Wayland).
WRITE-ONLY — does not inspect the screen. Use vision.py first
to get coordinates, then pass them to executor.

All coordinate inputs are in LOGICAL pixels (Wayland scaled).
The monitor scale correction is applied automatically from config.

Commands (pass via "command" field):
  CLICK x y              — left click at (x, y)
  CLICK x y right        — right click at (x, y)
  CLICK x y double       — double click at (x, y)
  TYPE x y text          — click at (x, y) then type text
  SCROLL x y up [n]      — scroll up n times at (x, y)  [default n=3]
  SCROLL x y down [n]    — scroll down n times at (x, y)
  WAIT seconds           — pause for N seconds
  PRESS key              — press a key (e.g. Return, ctrl+l, Tab, Escape)
  MOVE x y               — move mouse to (x, y) without clicking

Multiple commands via "commands" list:
  {"commands": ["CLICK 640 360", "TYPE 640 360 hello world", "PRESS Return"]}

Batch (fastest for sequences — one ydotool call per action):
  {"action": "batch", "commands": [...]}

Special actions:
  {"action": "volume", "level": 75}   — set system volume via pactl
  {"action": "notify", "title": "Avril", "message": "Done!"}  — desktop notification

Requires: ydotoold running — sudo ydotoold &
"""

import re
import subprocess
import time

import config

# ── Button codes for ydotool click ────────────────────────────────────────────
_BTN = {
    "left":   "0xC0",  # press + release
    "right":  "0xC1",
    "middle": "0xC2",
}

# ── Command regex ─────────────────────────────────────────────────────────────
_CMD_RE = re.compile(
    r'^(CLICK|TYPE|SCROLL|WAIT|PRESS|MOVE)\s+(.*)',
    re.IGNORECASE
)


# ── Low-level ydotool helpers ─────────────────────────────────────────────────

def _run(*cmd: str, timeout: int = 5) -> tuple[bool, str]:
    """Run a ydotool command. Returns (success, output)."""
    try:
        r = subprocess.run(
            ["ydotool"] + list(cmd),
            capture_output=True, text=True, timeout=timeout
        )
        ok = r.returncode == 0
        return ok, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return False, "ydotool not found — run: sudo ydotoold &"
    except subprocess.TimeoutExpired:
        return False, f"ydotool timed out after {timeout}s"
    except Exception as e:
        return False, str(e)


def _move(x: int, y: int) -> tuple[bool, str]:
    return _run("mousemove", "--absolute", "-x", str(x), "-y", str(y))


def _click(x: int, y: int, button: str = "left") -> tuple[bool, str]:
    ok, msg = _move(x, y)
    if not ok:
        return ok, msg
    time.sleep(0.15)  # let Hyprland register the move
    code = _BTN.get(button, _BTN["left"])
    return _run("click", code)


def _double_click(x: int, y: int) -> tuple[bool, str]:
    ok, msg = _click(x, y)
    if not ok:
        return ok, msg
    time.sleep(0.1)
    return _run("click", _BTN["left"])


def _type_text(text: str) -> tuple[bool, str]:
    if not text:
        return False, "No text provided"
    return _run("type", "--", text, timeout=15)


def _press_key(key: str) -> tuple[bool, str]:
    return _run("key", "--", key)


def _scroll(x: int, y: int, direction: str, amount: int = 3) -> tuple[bool, str]:
    ok, msg = _move(x, y)
    if not ok:
        return ok, msg
    time.sleep(0.1)
    delta = amount if direction.lower() == "down" else -amount
    return _run("scroll", "--", f"0:{delta * 120}")


# ── Command parser ────────────────────────────────────────────────────────────

def _execute_one(raw_command: str) -> str:
    """
    Parse and execute one command string.
    Returns a human-readable result line.
    """
    raw = raw_command.strip()
    if not raw:
        return "skip (empty)"

    m = _CMD_RE.match(raw)
    if not m:
        return f"Error: unrecognised command format '{raw}'"

    op   = m.group(1).upper()
    rest = m.group(2).strip()

    # ── WAIT ──────────────────────────────────────────────────────────────────
    if op == "WAIT":
        try:
            seconds = float(rest.split()[0])
            seconds = max(0.1, min(seconds, 30))
            time.sleep(seconds)
            return f"Waited {seconds}s"
        except ValueError:
            return f"Error: WAIT needs a number, got '{rest}'"

    # ── PRESS ─────────────────────────────────────────────────────────────────
    if op == "PRESS":
        key = rest.strip()
        if not key:
            return "Error: PRESS needs a key"
        ok, msg = _press_key(key)
        return f"Pressed {key}" if ok else f"Error pressing {key}: {msg}"

    # ── MOVE ──────────────────────────────────────────────────────────────────
    if op == "MOVE":
        parts = rest.split()
        if len(parts) < 2:
            return f"Error: MOVE needs x y, got '{rest}'"
        try:
            x, y = int(parts[0]), int(parts[1])
            ok, msg = _move(x, y)
            return f"Moved to ({x},{y})" if ok else f"Error: {msg}"
        except ValueError:
            return "Error: MOVE coordinates must be integers"

    # ── CLICK ─────────────────────────────────────────────────────────────────
    if op == "CLICK":
        parts = rest.split()
        if len(parts) < 2:
            return f"Error: CLICK needs x y, got '{rest}'"
        try:
            x, y   = int(parts[0]), int(parts[1])
            button = "left"
            double = False
            if len(parts) > 2:
                modifier = parts[2].lower()
                if modifier == "right":
                    button = "right"
                elif modifier == "double":
                    double = True
                elif modifier == "middle":
                    button = "middle"

            if double:
                ok, msg = _double_click(x, y)
                return f"Double-clicked ({x},{y})" if ok else f"Error: {msg}"
            else:
                ok, msg = _click(x, y, button)
                return f"Clicked ({x},{y}) [{button}]" if ok else f"Error: {msg}"
        except ValueError:
            return "Error: CLICK coordinates must be integers"

    # ── TYPE ──────────────────────────────────────────────────────────────────
    if op == "TYPE":
        parts = rest.split(None, 2)
        if len(parts) < 3:
            # TYPE without coordinates — type at current focus
            ok, msg = _type_text(rest)
            return f"Typed: '{rest}'" if ok else f"Error typing: {msg}"
        try:
            x, y = int(parts[0]), int(parts[1])
            text = parts[2]
            ok, msg = _click(x, y)
            if not ok:
                return f"Error clicking before type: {msg}"
            time.sleep(0.2)
            ok, msg = _type_text(text)
            return f"Typed '{text}' at ({x},{y})" if ok else f"Error typing: {msg}"
        except ValueError:
            return "Error: TYPE x y text — coordinates must be integers"

    # ── SCROLL ────────────────────────────────────────────────────────────────
    if op == "SCROLL":
        parts = rest.split()
        if len(parts) < 3:
            return "Error: SCROLL needs x y direction [amount]"
        try:
            x, y      = int(parts[0]), int(parts[1])
            direction = parts[2].lower()
            if direction not in ("up", "down"):
                return "Error: SCROLL direction must be 'up' or 'down'"
            amount = int(parts[3]) if len(parts) > 3 else 3
            ok, msg = _scroll(x, y, direction, amount)
            return f"Scrolled {direction} x{amount} at ({x},{y})" if ok else f"Error: {msg}"
        except ValueError:
            return "Error: SCROLL coordinates and amount must be integers"

    return f"Error: unhandled op '{op}'"


# ── Public dispatcher ─────────────────────────────────────────────────────────

def run_tool(args: dict = None) -> str:
    if args is None:
        args = {}

    action = str(args.get("action", "")).strip().lower()

    # ── volume ────────────────────────────────────────────────────────────────
    if action == "volume":
        level = max(0, min(int(args.get("level", 50)), 150))
        try:
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
                check=True, timeout=5,
            )
            return f"Volume set to {level}%"
        except Exception as e:
            return f"Error setting volume: {e}"

    # ── notify ────────────────────────────────────────────────────────────────
    if action == "notify":
        title      = args.get("title",      "Avril")
        message    = args.get("message",    "")
        timeout_ms = int(args.get("timeout_ms", 10000))
        try:
            subprocess.Popen(["notify-send", "-t", str(timeout_ms), title, message])
            return f"Notification sent: {title} — {message}"
        except FileNotFoundError:
            return "Error: notify-send not installed (sudo pacman -S libnotify)"
        except Exception as e:
            return f"Error sending notification: {e}"

    # ── batch ─────────────────────────────────────────────────────────────────
    if action == "batch":
        commands = args.get("commands", [])
        if not commands:
            return "[Executor] No commands in batch."
        results = []
        for cmd in commands:
            result = _execute_one(str(cmd))
            results.append(f"  {cmd!r} → {result}")
            if result.lower().startswith("error"):
                results.append("  [batch stopped on error]")
                break
            time.sleep(0.1)
        return "Batch results:\n" + "\n".join(results)

    # ── single command ────────────────────────────────────────────────────────
    command = str(args.get("command", "")).strip()
    if command:
        return _execute_one(command)

    # ── commands list ─────────────────────────────────────────────────────────
    commands = args.get("commands", [])
    if commands:
        results = []
        for cmd in commands:
            result = _execute_one(str(cmd))
            results.append(f"  {cmd!r} → {result}")
            if result.lower().startswith("error"):
                results.append("  [stopped on error]")
                break
            time.sleep(0.1)
        return "Results:\n" + "\n".join(results)

    return (
        "[Executor] No command provided. "
        "Use 'command': 'CLICK x y' or 'commands': [...] or "
        "'action': 'volume'/'notify'/'batch'"
    )
