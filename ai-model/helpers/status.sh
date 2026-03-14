#!/usr/bin/env bash
# ========================= helpers/status.sh =========================
# Check if Avril is running and show status.
# -----------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AI_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$AI_DIR/helpers/.avril.pid"
LOG_FILE="$AI_DIR/helpers/avril.log"
PORT=8000

_info()  { printf '\033[1;36m[Avril]\033[0m %s\n' "$*"; }
_ok()    { printf '\033[1;32m[Avril]\033[0m %s\n' "$*"; }
_err()   { printf '\033[1;31m[Avril]\033[0m %s\n' "$*"; }

if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        _ok "Avril is running (PID $PID)"

        # Check API health
        if curl -sf "http://localhost:$PORT/health" >/dev/null 2>&1; then
            _ok "API is responding on port $PORT"
        else
            _err "API is not responding on port $PORT"
        fi

        # Show recent log
        if [[ -f "$LOG_FILE" ]]; then
            _info "Last 5 log lines:"
            tail -5 "$LOG_FILE"
        fi
    else
        _err "PID $PID not running (stale PID file)"
        rm -f "$PID_FILE"
    fi
else
    _err "Avril is not running"
fi
