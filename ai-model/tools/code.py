# ========================= tools/code.py =========================
"""
Python code execution tool — run snippets with captured output.

Actions:
  run    Execute Python code, capture stdout+stderr   [code=..., timeout=10]
  eval   Evaluate a single expression, return result  [expr=...]
  list   Show available actions

Safety:
  Runs in a restricted namespace — open(), os, subprocess, __import__ are blocked.
  Pre-imported safe modules: math, json, datetime, re, statistics, random, itertools.
  Soft timeout via ThreadPoolExecutor (thread is orphaned on timeout, not killed).
"""

import io
import traceback
import contextlib
import math
import json as _json
import re as _re
import random as _random
import statistics as _statistics
import itertools as _itertools
from datetime import datetime as _datetime, date as _date, timedelta as _timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeout


# ── Safe builtins ─────────────────────────────────────────────────────────────

_BLOCKED = frozenset({
    "open", "exec", "eval", "__import__", "compile",
    "globals", "locals", "vars", "memoryview",
    "getattr", "setattr", "delattr",   # attribute access can escape sandbox
    "type", "super",                     # metaclass tricks
    "breakpoint", "exit", "quit",       # interactive/process control
    "input",                             # blocks on stdin
})


def _make_builtins():
    import builtins
    return {k: getattr(builtins, k) for k in dir(builtins)
            if not k.startswith("__") and k not in _BLOCKED}


_SAFE_GLOBALS = {
    "__builtins__": _make_builtins(),
    "math":         math,
    "json":         _json,
    "re":           _re,
    "random":       _random,
    "statistics":   _statistics,
    "itertools":    _itertools,
    "datetime":     _datetime,
    "date":         _date,
    "timedelta":    _timedelta,
}


# ── Execution helpers ─────────────────────────────────────────────────────────

def _exec_in_sandbox(code: str, stdout_buf, stderr_buf):
    namespace = dict(_SAFE_GLOBALS)
    with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
        exec(code, namespace)  # noqa: S102


def _run(args: dict) -> str:
    code = str(args.get("code", "")).strip()
    if not code:
        return "[code] No 'code' provided."

    timeout = max(1, min(int(args.get("timeout", 10)), 30))
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_exec_in_sandbox, code, stdout_buf, stderr_buf)
        try:
            future.result(timeout=timeout)
        except _FuturesTimeout:
            return f"[code] Execution timed out after {timeout}s."
        except Exception:
            err = traceback.format_exc()
            out = stdout_buf.getvalue()
            parts = []
            if out.strip():
                parts.append(f"Output:\n{out.rstrip()}")
            parts.append(f"Error:\n{err.rstrip()}")
            return "\n\n".join(parts)

    out = stdout_buf.getvalue()
    err = stderr_buf.getvalue()
    if not out.strip() and not err.strip():
        return "[code] Executed successfully (no output)."
    parts = []
    if out.strip():
        parts.append(f"Output:\n{out.rstrip()}")
    if err.strip():
        parts.append(f"Stderr:\n{err.rstrip()}")
    return "\n\n".join(parts)


def _eval(args: dict) -> str:
    expr = str(args.get("expr", "")).strip()
    if not expr:
        return "[code] No 'expr' provided."
    try:
        result = eval(expr, dict(_SAFE_GLOBALS))  # noqa: S307
        return repr(result)
    except Exception as e:
        return f"[code] Error: {e}"


def _list_actions(_: dict) -> str:
    return (
        "Available code actions:\n"
        "  run    Execute Python code    [code=..., timeout=10]\n"
        "  eval   Evaluate expression   [expr=...]\n\n"
        "Pre-imported: math, json, re, random, statistics, itertools, datetime\n"
        "Blocked:      open, os, subprocess, __import__, compile"
    )


# ── Dispatcher ────────────────────────────────────────────────────────────────

_ACTIONS = {
    "run":  _run,
    "eval": _eval,
    "list": _list_actions,
}


def run_tool(args: dict = None) -> str:
    if args is None:
        args = {}
    action = str(args.get("action", "")).strip().lower()
    if not action:
        return "[code] No action specified. Use action='list' to see available tools."
    fn = _ACTIONS.get(action)
    if fn is None:
        return f"[code] Unknown action '{action}'. Available: {', '.join(_ACTIONS)}"
    try:
        return fn(args)
    except Exception as e:
        return f"[code] Error in '{action}': {e}"
