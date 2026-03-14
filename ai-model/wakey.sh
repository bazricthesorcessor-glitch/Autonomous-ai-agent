#!/usr/bin/env bash
# wakey.sh — Start Avril in the background and open the UI.
# Called by the 'wakey' fish function.
# The script launches Avril detached so it survives terminal close.

AVRIL_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="/tmp/avril.log"
HEALTH_URL="http://localhost:8000/health"
UI_URL="http://localhost:8000/app"
PYTHON="${PYTHON:-python3}"

# ── 1. Check if already running ──────────────────────────────────────────────
if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
    echo "[wakey] Avril is already running — opening UI."
    xdg-open "$UI_URL" > /dev/null 2>&1
    exit 0
fi

# ── 2. Launch Avril detached (survives terminal close) ────────────────────────
echo "[wakey] Starting Avril..."
nohup "$PYTHON" "$AVRIL_DIR/main.py" >> "$LOG_FILE" 2>&1 &
AVRIL_PID=$!
disown "$AVRIL_PID" 2>/dev/null || true
echo "[wakey] Brain PID: $AVRIL_PID  (log: $LOG_FILE)"

# ── 3. Wait for the server to become ready (up to 20 s) ──────────────────────
READY=0
for i in $(seq 1 20); do
    sleep 1
    if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
        READY=1
        echo "[wakey] Avril is up! (${i}s)"
        break
    fi
    printf "[wakey] Waiting... (%d/20)\r" "$i"
done

if [ "$READY" -eq 0 ]; then
    echo ""
    echo "[wakey] Server did not respond in time. Check $LOG_FILE"
    exit 1
fi

echo ""

# ── 4. Open browser UI ────────────────────────────────────────────────────────
xdg-open "$UI_URL" > /dev/null 2>&1 &

# ── 5. Short delay so the browser gets a moment to open ──────────────────────
sleep 0.5
