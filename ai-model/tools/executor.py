"""Atomic GUI action executor for AVRIL.

Commands are parsed as atomic actions and converted into ydotool calls.

Supported commands:
  MOVE x y
  CLICK x y
  TYPE x y text to enter
  SCROLL x y up|down [amount]
  WAIT seconds
  PRESS key
"""

from __future__ import annotations

import shlex
import subprocess
import time


def _ydotool(*cmd: str) -> str:
    try:
        result = subprocess.run(["ydotool", *cmd], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return "ok"
        return result.stderr.strip() or "unknown error"
    except FileNotFoundError:
        return "ydotool not found"
    except subprocess.TimeoutExpired:
        return "ydotool timed out"


def _move(x: int, y: int) -> str:
    return _ydotool("mousemove", "--absolute", "-x", str(x), "-y", str(y))


def _click() -> str:
    return _ydotool("click", "0xC0")


def _type(text: str) -> str:
    return _ydotool("type", "--", text)


def _press(key: str) -> str:
    return _ydotool("key", key)


def _scroll(direction: str, amount: int) -> str:
    delta = amount if direction == "down" else -amount
    return _ydotool("scroll", "--", f"0:{delta * 120}")


def _run_atomic(command: str) -> str:
    parts = shlex.split(command)
    if not parts:
        return "Error: empty command"

    op = parts[0].upper()
    if op == "MOVE" and len(parts) >= 3:
        x = int(parts[1])
        y = int(parts[2])
        out = _move(x, y)
        return f"MOVE ({x}, {y})" if out == "ok" else f"Error: {out}"

    if op == "CLICK" and len(parts) >= 3:
        x = int(parts[1])
        y = int(parts[2])
        out = _move(x, y)
        if out != "ok":
            return f"Error: {out}"
        time.sleep(0.1)
        out = _click()
        return f"CLICK ({x}, {y})" if out == "ok" else f"Error: {out}"

    if op == "TYPE" and len(parts) >= 4:
        x = int(parts[1])
        y = int(parts[2])
        text = command.split(parts[2], 1)[1].strip()
        out = _move(x, y)
        if out != "ok":
            return f"Error: {out}"
        time.sleep(0.1)
        out = _click()
        if out != "ok":
            return f"Error: {out}"
        time.sleep(0.1)
        out = _type(text)
        return f"TYPE ({x}, {y}) {text}" if out == "ok" else f"Error: {out}"

    if op == "SCROLL" and len(parts) >= 4:
        x = int(parts[1])
        y = int(parts[2])
        direction = parts[3].lower()
        amount = int(parts[4]) if len(parts) >= 5 else 3
        out = _move(x, y)
        if out != "ok":
            return f"Error: {out}"
        time.sleep(0.1)
        out = _scroll(direction, amount)
        return f"SCROLL ({x}, {y}) {direction} x{amount}" if out == "ok" else f"Error: {out}"

    if op == "WAIT" and len(parts) >= 2:
        seconds = min(max(float(parts[1]), 0.0), 10.0)
        time.sleep(seconds)
        return f"WAIT {seconds}"

    if op == "PRESS" and len(parts) >= 2:
        key = parts[1]
        out = _press(key)
        return f"PRESS {key}" if out == "ok" else f"Error: {out}"

    return f"Error: unsupported command '{command}'"


def run_tool(args: dict = None) -> str:
    if args is None:
        args = {}

    commands = args.get("commands")
    command = str(args.get("command", "")).strip()
    if commands is None:
        commands = [command] if command else []
    elif isinstance(commands, str):
        commands = [commands]

    if not commands:
        return "Error: provide 'command' or 'commands'"

    results = [_run_atomic(str(item)) for item in commands]
    return "\n".join(results)