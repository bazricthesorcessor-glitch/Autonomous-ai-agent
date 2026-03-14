#!/usr/bin/env bash
# ========================= helpers/start.sh =========================
# Starts Avril AI backend as a background daemon and opens the UI.
# The AI survives terminal close (uses setsid to fully detach).
#
# Usage:
#   bash helpers/start.sh          — start + open UI
#   bash helpers/start.sh --quiet  — start without opening browser
# -----------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AI_DIR="$(dirname "$SCRIPT_DIR")"        # ai-model/
VENV_PYTHON="$AI_DIR/.venv/bin/python"
PID_FILE="$AI_DIR/helpers/.avril.pid"
LOG_FILE="$AI_DIR/helpers/avril.log"
PORT=8000
UI_URL="http://localhost:$PORT/app"

# ── helpers ──────────────────────────────────────────────────────────

_info()  { printf '\033[1;36m[Avril]\033[0m %s\n' "$*"; }
_ok()    { printf '\033[1;32m[Avril]\033[0m %s\n' "$*"; }
_err()   { printf '\033[1;31m[Avril]\033[0m %s\n' "$*"; }

_is_running() {
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        rm -f "$PID_FILE"
    fi
    return 1
}

_wait_for_server() {
    local max_wait=30
    local waited=0
    while (( waited < max_wait )); do
        if curl -sf "http://localhost:$PORT/health" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
        (( waited++ ))
    done
    return 1
}

# ── main ─────────────────────────────────────────────────────────────

# Already running?
if _is_running; then
    _ok "Avril is already running (PID $(cat "$PID_FILE"))"
    firefox "$UI_URL" 2>/dev/null &
    exit 0
fi

_info "Starting Avril..."

# Verify venv Python exists
if [[ ! -x "$VENV_PYTHON" ]]; then
    _err "Virtual environment not found: $VENV_PYTHON"
    _err "Run: python3 -m venv $AI_DIR/.venv && $AI_DIR/.venv/bin/pip install flask ollama flask-cors numpy"
    exit 1
fi

# Launch as a fully detached daemon via setsid
# Uses venv Python so all dependencies are available
# stdout/stderr go to log file, process gets its own session
setsid "$VENV_PYTHON" "$AI_DIR/main.py" \
    >> "$LOG_FILE" 2>&1 &
AVRIL_PID=$!

# Save PID
echo "$AVRIL_PID" > "$PID_FILE"

_info "Daemon started (PID $AVRIL_PID) — log: $LOG_FILE"

# Wait for the server to be ready
_info "Waiting for server on port $PORT..."
if _wait_for_server; then
    _ok "Avril is live at $UI_URL"
else
    _err "Server did not respond within 30s — check $LOG_FILE"
    exit 1
fi

# Open UI in Firefox (unless --quiet)
if [[ "${1:-}" != "--quiet" ]]; then
    firefox "$UI_URL" 2>/dev/null &
    _ok "UI opened in Firefox"
fi

_ok "You can close this terminal — Avril keeps running."
_info "To stop:  bash $SCRIPT_DIR/stop.sh"
