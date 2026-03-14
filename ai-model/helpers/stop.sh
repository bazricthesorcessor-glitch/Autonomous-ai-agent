#!/usr/bin/env bash
# ========================= helpers/stop.sh =========================
# Gracefully stops the Avril AI daemon.
#
# Usage:
#   bash helpers/stop.sh
# -----------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AI_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$AI_DIR/helpers/.avril.pid"

_info()  { printf '\033[1;36m[Avril]\033[0m %s\n' "$*"; }
_ok()    { printf '\033[1;32m[Avril]\033[0m %s\n' "$*"; }
_err()   { printf '\033[1;31m[Avril]\033[0m %s\n' "$*"; }

if [[ ! -f "$PID_FILE" ]]; then
    _err "No PID file found — Avril may not be running."
    # Try to find and kill by process name as fallback
    PID=$(pgrep -f "python3.*main\.py" | head -1 || true)
    if [[ -n "$PID" ]]; then
        _info "Found Avril process: PID $PID"
        kill "$PID" 2>/dev/null && _ok "Stopped." || _err "Could not stop PID $PID"
    else
        _info "No Avril process found."
    fi
    exit 0
fi

PID=$(cat "$PID_FILE")

if kill -0 "$PID" 2>/dev/null; then
    _info "Stopping Avril (PID $PID)..."
    kill "$PID"
    # Wait for clean exit
    for i in $(seq 1 10); do
        if ! kill -0 "$PID" 2>/dev/null; then
            break
        fi
        sleep 0.5
    done
    # Force kill if still alive
    if kill -0 "$PID" 2>/dev/null; then
        _info "Force killing..."
        kill -9 "$PID" 2>/dev/null
    fi
    _ok "Avril stopped."
else
    _info "Process $PID is not running (stale PID file)."
fi

rm -f "$PID_FILE"
