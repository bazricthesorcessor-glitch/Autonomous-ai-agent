# core/autonomous_mode.py
"""
Global autonomous mode flag.

When True  → goal scheduler fires background tasks (health check, task resume, etc.)
When False → all scheduled/autonomous tasks are suspended; Avril is purely reactive.

State is persisted to memory/system_state.json so it survives restarts.
Default: True (enabled on first start).
"""

import json
import os
import tempfile
import threading
import config

_lock    = threading.Lock()
_enabled = True   # Will be overwritten by _load() on import


def is_enabled() -> bool:
    """Return True if autonomous background tasks are currently running."""
    with _lock:
        return _enabled


def set_enabled(value: bool) -> None:
    """Enable or disable autonomous tasks. Persists state immediately."""
    global _enabled
    with _lock:
        _enabled = bool(value)
        _persist()
    status = "enabled" if _enabled else "disabled"
    print(f"[AutonomousMode] Autonomous tasks {status}.")


def _persist() -> None:
    """Write current flag to system_state.json (called under _lock).
    Uses atomic temp-file write to prevent corruption on crash."""
    try:
        state = config.safe_load_json(config.SYSTEM_STATE_FILE, {})
        state["autonomous_enabled"] = _enabled
        dir_name = os.path.dirname(config.SYSTEM_STATE_FILE)
        fd, tmp = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(state, f, indent=2)
            os.replace(tmp, config.SYSTEM_STATE_FILE)
        except Exception:
            os.unlink(tmp)
            raise
    except Exception as e:
        print(f"[AutonomousMode] Failed to persist: {e}")


def _load() -> None:
    """Read autonomous_enabled from system_state.json at import time."""
    global _enabled
    try:
        state = config.safe_load_json(config.SYSTEM_STATE_FILE, {})
        if "autonomous_enabled" in state:
            _enabled = bool(state["autonomous_enabled"])
    except Exception:
        pass


_load()
