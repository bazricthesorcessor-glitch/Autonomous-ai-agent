# ========================= core/api_server.py =========================
import os
import json
import pathlib
import subprocess
import threading
from datetime import datetime
from flask import Flask, request, jsonify, Response, send_from_directory

import config
from core import context_builder, agent_loop
from personality import loader as personality
from engines import fact_engine, memory_engine, task_manager

app = Flask(__name__)

# ── Guard constants ───────────────────────────────────────────────────────────
_MAX_MSG_LEN = 8000   # Characters — reject oversized payloads before touching AI
_PERSONA_STATE = {"mode": None, "locked": False}

# ── Path to the standalone UI folder ─────────────────────────────────────────
# api_server.py lives in ai-model/core/ → go up two levels → repo root → ui/
_UI_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / 'ui'


_ALLOWED_ORIGINS = {
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'null',  # file:// origin sends "null"
}

@app.after_request
def _add_cors(response):
    """Allow the standalone ui/ folder to talk to this server (localhost + file:// only)."""
    origin = request.headers.get('Origin', '')
    if origin in _ALLOWED_ORIGINS:
        response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response


@app.route('/', defaults={'path': ''}, methods=['OPTIONS', 'GET', 'POST'])
@app.route('/<path:path>', methods=['OPTIONS', 'GET', 'POST'])
def _fallback(path):
    """Handle CORS preflight and return clean 404 for any unregistered path."""
    if request.method == 'OPTIONS':
        return '', 204
    return jsonify({'error': 'Not found', 'path': f'/{path}'}), 404

# ── Helpers ───────────────────────────────────────────────────────────────────

def log_conversation(user_msg: str, ai_msg: str):
    """Appends the interaction to today's raw log file.

    Sanitizes the AI response: strips fake multi-turn dialogue that the
    model sometimes generates (e.g. "**Divyansh:** ...\n**Avril:** ...").
    Only the first real response paragraph is kept.
    """
    import re
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    log_path = config.get_raw_log_path()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    # Strip fake dialogue blocks and training artifacts the LLM appends
    clean = ai_msg.strip()
    # Cut at the first fake conversation / training-data marker
    for marker in [
        '\n**Divyansh:', '\n**Avril:', '\n**Avrirl:',
        '\n[2026-', '\n--- 2026-', '\n---\n\n**',
        '\n---\n[', '\n=== ', '\n[SCHEDULED',
        '\n[User]', '\nAssistant:',
        '\n####', '\n---\n', '\n-----',
        '\nInstruction', '\n**Task List',
        '\nDr. ', '\n**Dr.',
        '\n\n**',
    ]:
        idx = clean.find(marker)
        if idx > 0:
            clean = clean[:idx]
    clean = clean.strip()
    # Cap logged response length to prevent log bloat
    if len(clean) > 400:
        clean = clean[:400] + "..."

    with open(log_path, "a") as f:
        f.write(f"{config.LOG_DELIMITER} {timestamp} | {config.USER_NAME}: {user_msg}\n")
        f.write(f"{config.AI_NAME}: {clean}\n")


def _system_status() -> dict:
    """Return a dict with CPU, RAM, Disk, model info."""
    status = {
        "model": config.CHAT_MODEL,
        "decision_model": config.DECISION_MODEL,
    }
    # Try psutil first (most accurate)
    try:
        import psutil
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        status["cpu_percent"] = psutil.cpu_percent(interval=0.2)
        status["ram_used_gb"] = round(mem.used / 1e9, 1)
        status["ram_total_gb"] = round(mem.total / 1e9, 1)
        status["ram_percent"] = mem.percent
        status["disk_used_gb"] = round(disk.used / 1e9, 1)
        status["disk_total_gb"] = round(disk.total / 1e9, 1)
        status["disk_percent"] = disk.percent
        return status
    except ImportError:
        pass

    # Fallback: /proc/meminfo + df
    try:
        with open("/proc/meminfo") as f:
            mem_lines = {l.split(':')[0]: l.split(':')[1].strip() for l in f}
        total_kb = int(mem_lines.get("MemTotal", "0 kB").split()[0])
        avail_kb = int(mem_lines.get("MemAvailable", "0 kB").split()[0])
        used_kb = total_kb - avail_kb
        status["ram_used_gb"] = round(used_kb / 1e6, 1)
        status["ram_total_gb"] = round(total_kb / 1e6, 1)
        status["ram_percent"] = round(used_kb / total_kb * 100, 1) if total_kb else 0
    except Exception:
        pass

    try:
        df = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=3)
        lines = df.stdout.strip().split('\n')
        if len(lines) > 1:
            parts = lines[1].split()
            status["disk_info"] = f"{parts[2]} used / {parts[1]} total ({parts[4]})"
    except Exception:
        pass

    return status


def _handle_command(cmd: str):
    """
    Handle !command prefixes without invoking the agent loop.
    Returns response string, or None if not a command.
    """
    stripped = cmd.strip()
    if not stripped.startswith('!'):
        return None

    parts = stripped[1:].lower().split(maxsplit=1)
    action = parts[0] if parts else ""

    if action == "status":
        s = _system_status()
        lines = ["System Status:"]
        if "cpu_percent" in s:
            lines.append(f"  CPU     : {s['cpu_percent']}%")
        if "ram_used_gb" in s:
            lines.append(f"  RAM     : {s['ram_used_gb']} / {s['ram_total_gb']} GB  ({s['ram_percent']}%)")
        if "disk_used_gb" in s:
            lines.append(f"  Disk    : {s['disk_used_gb']} / {s['disk_total_gb']} GB  ({s['disk_percent']}%)")
        elif "disk_info" in s:
            lines.append(f"  Disk    : {s['disk_info']}")
        lines.append(f"  Model   : {s['model']}")
        lines.append(f"  Planner : {s['decision_model']}")
        return "\n".join(lines)

    if action == "tasks":
        tasks = task_manager.get_active_tasks()
        if not tasks:
            return "No active tasks."
        lines = [f"Active Tasks ({len(tasks)}):"]
        for t in tasks:
            steps = len(t.get("steps", []))
            lines.append(f"  [{t['id']}] {t['title']} — {steps} steps — {t.get('status', '?')}")
        return "\n".join(lines)

    if action == "abort":
        task_manager.abandon_all_active("user requested abort via !abort")
        return "All active tasks have been aborted."

    if action == "memory":
        try:
            data = config.safe_load_json(config.VECTOR_STORE, [])
            count = len(data) if isinstance(data, list) else 0
        except Exception:
            count = 0
        facts = fact_engine.get_active_facts()
        lines = [f"Vector memory: {count} entries"]
        if facts:
            lines.append(f"Known facts ({len(facts)}):")
            for k, v in list(facts.items())[:10]:
                lines.append(f"  {k}: {v}")
        else:
            lines.append("No facts stored yet.")
        return "\n".join(lines)

    if action == "restart":
        return (
            "To restart the server:\n"
            "  cd /home/dmannu/divyansh/ai-model && python main.py\n"
            "Or: systemctl --user restart avril  (if service is configured)"
        )

    return f"Unknown command: !{action}\nAvailable: !status  !tasks  !abort  !memory  !restart"


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    user_message = data.get('message', '').strip()

    if not user_message:
        return jsonify({'error': 'No message provided'}), 400

    if len(user_message) > _MAX_MSG_LEN:
        return jsonify({'error': f'Message too long ({len(user_message)} chars; max {_MAX_MSG_LEN})'}), 413

    print(f"Received: {user_message}")

    # 0. Handle !commands — bypass agent loop entirely
    cmd_response = _handle_command(user_message)
    if cmd_response is not None:
        log_conversation(user_message, cmd_response)
        return jsonify({'response': cmd_response})

    try:
        # Fast path: greetings skip context + embedding; chat questions skip
        # only the planner but still get memory context.
        active_tasks = task_manager.get_active_tasks()
        fast = agent_loop.classify_fast_path(user_message) if not active_tasks else 'agent'

        if fast == 'greeting':
            if _PERSONA_STATE["locked"] and _PERSONA_STATE["mode"]:
                persona_prompt = personality.get_persona_for_mode(_PERSONA_STATE["mode"])
            else:
                persona_prompt = personality.get_persona(user_message)
            ai_response = agent_loop.run_turn(user_message, persona_prompt, memory_context="")
            log_conversation(user_message, ai_response)
            return jsonify({'response': ai_response})

        if fast == 'chat':
            # Tier 2: build memory context (for identity/fact recall) but skip planner
            try:
                fact_engine.process_fact_query(user_message)
            except Exception as fe:
                print(f"[FactEngine] {fe}")
            memory_context = context_builder.build_context(user_message)
            if _PERSONA_STATE["locked"] and _PERSONA_STATE["mode"]:
                persona_prompt = personality.get_persona_for_mode(_PERSONA_STATE["mode"])
            else:
                persona_prompt = personality.get_persona(user_message)
            now_str = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
            persona_prompt += f"\nCurrent date and time: {now_str}"
            ai_response = agent_loop.run_turn(user_message, persona_prompt, memory_context)
            log_conversation(user_message, ai_response)
            return jsonify({'response': ai_response})

        # Normal path: full context building + agent loop
        # 1. Extract facts FIRST so they're available during context build
        try:
            fact_engine.process_fact_query(user_message)
        except Exception as fe:
            print(f"[FactEngine] {fe}")

        # 2. Build memory context (now includes newly extracted facts)
        memory_context = context_builder.build_context(user_message)

        # 3. Select persona (locked persona overrides keyword detection)
        if _PERSONA_STATE["locked"] and _PERSONA_STATE["mode"]:
            persona_prompt = personality.get_persona_for_mode(_PERSONA_STATE["mode"])
        else:
            persona_prompt = personality.get_persona(user_message)

        # Inject current time into persona so the model always knows it
        now_str = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
        persona_prompt += f"\nCurrent date and time: {now_str}"

        # 4. Run agent loop (plan → tool → respond)
        ai_response = agent_loop.run_turn(user_message, persona_prompt, memory_context)

        # 5. Log
        log_conversation(user_message, ai_response)

        # 6. Store user message in vector memory (background — don't block response)
        def _bg_store(msg):
            try:
                memory_engine.add_memory(msg)
            except Exception as me:
                print(f"[MemoryEngine] add_memory failed: {me}")
        threading.Thread(target=_bg_store, args=(user_message,), daemon=True).start()

        return jsonify({'response': ai_response})

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'online', 'model': config.CHAT_MODEL})


@app.route('/tasks', methods=['GET'])
def get_tasks():
    """Return all active tasks as JSON."""
    tasks = task_manager.get_active_tasks()
    return jsonify({'tasks': tasks, 'count': len(tasks)})


@app.route('/status', methods=['GET'])
def get_status():
    """Return system status: CPU, RAM, Disk, models."""
    return jsonify(_system_status())


@app.route('/logs', methods=['GET'])
def get_logs():
    """Return the last N lines of today's raw log."""
    try:
        n = int(request.args.get('lines', 50))
    except (ValueError, TypeError):
        n = 50
    log_path = config.get_raw_log_path()
    if not os.path.exists(log_path):
        return jsonify({'log': '', 'path': log_path})
    try:
        with open(log_path, 'r') as f:
            lines = f.readlines()
        tail = "".join(lines[-n:])
        return jsonify({'log': tail, 'lines': len(lines)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/ui')
def ui():
    """Serve the Avril local text console UI."""
    return Response(_UI_HTML, mimetype='text/html')


@app.route('/persona', methods=['POST'])
def set_persona():
    """Set (and optionally lock) the active persona mode.

    Payload: { "mode": "coding", "locked": true }
    """
    data   = request.json or {}
    mode   = data.get('mode', 'default')
    locked = bool(data.get('locked', False))

    valid_modes = {'default', 'coding', 'teacher', 'assistant'}
    if mode not in valid_modes:
        return jsonify({'error': f'Unknown mode: {mode}. Valid: {sorted(valid_modes)}'}), 400

    _PERSONA_STATE['mode']   = mode
    _PERSONA_STATE['locked'] = locked

    return jsonify({'mode': mode, 'locked': locked, 'status': 'ok'})


@app.route('/tool-feed', methods=['GET'])
def get_tool_feed():
    """Return the last N tool executions for the UI activity feed."""
    n = int(request.args.get('limit', 20))
    feed = agent_loop.get_tool_feed()[:n]
    return jsonify({'feed': feed, 'count': len(feed)})


# ── Autonomous mode ───────────────────────────────────────────────────────────

@app.route('/autonomous', methods=['GET'])
def get_autonomous():
    """Return current autonomous mode state."""
    from core import autonomous_mode
    return jsonify({'enabled': autonomous_mode.is_enabled()})


@app.route('/autonomous', methods=['POST'])
def set_autonomous():
    """Enable or disable autonomous background tasks.
    Payload: { "enabled": true|false }
    """
    from core import autonomous_mode
    data    = request.json or {}
    enabled = bool(data.get('enabled', True))
    autonomous_mode.set_enabled(enabled)
    return jsonify({'enabled': enabled, 'status': 'ok'})


# ── Todos ─────────────────────────────────────────────────────────────────────

@app.route('/todos', methods=['GET'])
def get_todos():
    """Return all todos."""
    from engines import todo_manager
    todos = todo_manager.get_all()
    return jsonify({'todos': todos, 'count': len(todos)})


@app.route('/todos/<todo_id>', methods=['PATCH'])
def update_todo(todo_id):
    """Update the status of a single todo item.
    Payload: { "status": "pending"|"in_progress"|"done" }
    """
    from engines import todo_manager
    data   = request.json or {}
    status = data.get('status', 'done')
    ok     = todo_manager.update_status(todo_id, status)
    if ok:
        return jsonify({'id': todo_id, 'status': status, 'ok': True})
    return jsonify({'error': f"Todo '{todo_id}' not found"}), 404


@app.route('/todos/clear-done', methods=['POST'])
def clear_done_todos():
    """Remove all completed todos."""
    from engines import todo_manager
    removed = todo_manager.clear_done()
    return jsonify({'removed': removed, 'ok': True})


@app.route('/screen', methods=['GET'])
def get_screen():
    """Return the latest screen OCR cache (written by tools/screenshot.py)."""
    path = getattr(config, 'SCREEN_CACHE_FILE', None)
    if not path or not os.path.exists(path):
        return jsonify({'text': '', 'timestamp': '', 'mode': '', 'available': False})
    try:
        data = config.safe_load_json(path, {})
        return jsonify({
            'text':      data.get('last_screen_text', ''),
            'timestamp': data.get('timestamp', ''),
            'mode':      data.get('mode', ''),
            'available': True,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Visual debug endpoint ────────────────────────────────────────────────────

@app.route('/debug-screen', methods=['GET'])
def debug_screen():
    """Trigger a screen scan and return the detected UI elements + screenshot path.

    Useful for debugging what AVRIL "sees" on screen.
    Query params:
      ?app=firefox  — restrict scan to a specific window (default: full screen)
    Returns JSON with:
      - screenshot_path: path to the captured PNG
      - timestamp: when the scan was taken
      - element_count: total detected elements
      - elements: list of {text, x, y, w, h, cx, cy, type, conf}
      - by_type: elements grouped by type for quick inspection
    """
    from tools import screen_map

    app_hint = request.args.get('app', '')
    if app_hint:
        from tools.computer_use import _get_window_region
        min_x, max_x, min_y, max_y = _get_window_region(app_hint)
    else:
        min_x, max_x, min_y, max_y = 0, 99999, 0, 99999

    elements = screen_map.scan(min_x, max_x, min_y, max_y)

    # Group by type for easier debugging
    by_type = {}
    for el in elements:
        t = el.get('type', 'unknown')
        by_type.setdefault(t, []).append({
            'text': el['text'][:60],
            'cx': el['cx'], 'cy': el['cy'],
            'w': el['w'], 'h': el['h'],
        })

    screenshot_path = os.path.join(config.SCREENSHOT_DIR, '_map_screen.png')

    return jsonify({
        'screenshot_path': screenshot_path,
        'timestamp': __import__('time').strftime('%Y-%m-%d %H:%M:%S'),
        'element_count': len(elements),
        'elements': elements,
        'by_type': by_type,
    })


@app.route('/app', strict_slashes=False)
def new_ui_index():
    """Serve the standalone UI index.html from the ui/ folder."""
    if not _UI_DIR.exists():
        return 'UI folder not found at: ' + str(_UI_DIR), 404
    return send_from_directory(str(_UI_DIR), 'index.html')


@app.route('/app/<path:filename>')
def new_ui_static(filename):
    """Serve static assets for the standalone UI (css, js, assets)."""
    if not _UI_DIR.exists():
        return 'UI folder not found', 404
    return send_from_directory(str(_UI_DIR), filename)


# ── Local Text UI ─────────────────────────────────────────────────────────────

_UI_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Avril Console</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #111; color: #d0d0d0;
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px; height: 100vh;
  display: flex; flex-direction: column; overflow: hidden;
}
#header {
  background: #1e1e1e; border-bottom: 1px solid #333;
  padding: 8px 16px; font-size: 14px; color: #a0c4ff;
  display: flex; justify-content: space-between; align-items: center;
  flex-shrink: 0;
}
#header .subtitle { color: #555; font-size: 11px; }
#main { display: flex; flex: 1; overflow: hidden; }
#chat-area {
  flex: 1; display: flex; flex-direction: column;
  border-right: 1px solid #2a2a2a;
}
#messages {
  flex: 1; overflow-y: auto; padding: 12px;
  display: flex; flex-direction: column; gap: 8px;
}
.msg {
  padding: 8px 12px; border-radius: 4px;
  line-height: 1.5; max-width: 90%;
  white-space: pre-wrap; word-break: break-word;
}
.msg.user {
  background: #1a2a3a; border-left: 3px solid #4a9eff;
  align-self: flex-end; color: #c8deff;
}
.msg.avril {
  background: #1e1e1e; border-left: 3px solid #5a5a5a;
  align-self: flex-start; color: #d8d8d8;
}
.msg.system {
  background: #1a1a1a; border-left: 3px solid #444;
  align-self: center; color: #666;
  font-size: 11px; font-style: italic;
}
.msg .sender { font-size: 10px; color: #555; margin-bottom: 3px; }
.msg.user .sender { color: #4a9eff; }
.msg.avril .sender { color: #888; }
#input-area {
  display: flex; padding: 10px;
  border-top: 1px solid #2a2a2a; gap: 8px; flex-shrink: 0;
}
#msg-input {
  flex: 1; background: #1e1e1e; border: 1px solid #333;
  color: #d0d0d0; padding: 8px 12px;
  font-family: inherit; font-size: 13px;
  border-radius: 3px; outline: none;
}
#msg-input:focus { border-color: #4a9eff; }
#send-btn {
  background: #1a3a5a; border: 1px solid #4a9eff;
  color: #4a9eff; padding: 8px 18px;
  font-family: inherit; font-size: 13px;
  cursor: pointer; border-radius: 3px;
}
#send-btn:hover { background: #2a4a6a; }
#send-btn:disabled { opacity: 0.4; cursor: default; }
#thinking {
  display: none; color: #555; font-style: italic;
  font-size: 11px; padding: 4px 12px;
}
#sidebar {
  width: 260px; display: flex;
  flex-direction: column; overflow: hidden; flex-shrink: 0;
}
.panel { border-bottom: 1px solid #2a2a2a; padding: 10px; overflow-y: auto; }
.panel h3 {
  font-size: 11px; text-transform: uppercase;
  letter-spacing: 1px; color: #555; margin-bottom: 8px;
}
#tasks-panel { flex: 1; }
#status-panel { flex-shrink: 0; }
.task-item {
  background: #1a1a1a; border-left: 3px solid #e86c3a;
  padding: 6px 8px; margin-bottom: 6px;
  font-size: 11px; line-height: 1.5;
}
.task-id    { color: #888; font-size: 10px; }
.task-title { color: #e8c47a; font-weight: bold; }
.task-steps { color: #666; font-size: 10px; }
.no-tasks   { color: #444; font-style: italic; font-size: 11px; }
#status-content div { margin-bottom: 4px; color: #999; font-size: 11px; }
.stat-label { color: #555; }
.stat-value { color: #7fc97a; }
</style>
</head>
<body>
<div id="header">
  <span>&#9670; Avril AI Console</span>
  <span class="subtitle" id="header-status">connecting...</span>
</div>
<div id="main">
  <div id="chat-area">
    <div id="messages">
      <div class="msg system">Avril is ready. Use !status !tasks !abort !memory for quick info.</div>
    </div>
    <div id="thinking">Avril is thinking...</div>
    <div id="input-area">
      <input id="msg-input" type="text" placeholder="Message Avril..." autofocus />
      <button id="send-btn">Send</button>
    </div>
  </div>
  <div id="sidebar">
    <div class="panel" id="tasks-panel">
      <h3>Active Tasks</h3>
      <div id="tasks-list"><div class="no-tasks">No active tasks</div></div>
    </div>
    <div class="panel" id="status-panel">
      <h3>System Status</h3>
      <div id="status-content">
        <div><span class="stat-label">Model  : </span><span class="stat-value" id="s-model">-</span></div>
        <div><span class="stat-label">CPU    : </span><span class="stat-value" id="s-cpu">-</span></div>
        <div><span class="stat-label">RAM    : </span><span class="stat-value" id="s-ram">-</span></div>
        <div><span class="stat-label">Disk   : </span><span class="stat-value" id="s-disk">-</span></div>
      </div>
    </div>
  </div>
</div>
<script>
const msgsEl = document.getElementById('messages')
const inputEl = document.getElementById('msg-input')
const sendBtn = document.getElementById('send-btn')
const thinkEl = document.getElementById('thinking')

function scrollBottom() { msgsEl.scrollTop = msgsEl.scrollHeight }

function addMsg(role, text) {
  const div = document.createElement('div')
  div.className = 'msg ' + role
  if (role !== 'system') {
    const s = document.createElement('div')
    s.className = 'sender'
    s.textContent = role === 'user' ? 'You' : 'Avril'
    div.appendChild(s)
  }
  const b = document.createElement('div')
  b.textContent = text
  div.appendChild(b)
  msgsEl.appendChild(div)
  scrollBottom()
}

async function sendMessage() {
  const text = inputEl.value.trim()
  if (!text) return
  inputEl.value = ''
  sendBtn.disabled = true
  thinkEl.style.display = 'block'
  addMsg('user', text)
  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text})
    })
    const d = await res.json()
    addMsg(d.response ? 'avril' : 'system', d.response || ('Error: ' + d.error))
  } catch(e) {
    addMsg('system', 'Network error: ' + e.message)
  } finally {
    sendBtn.disabled = false
    thinkEl.style.display = 'none'
    inputEl.focus()
  }
}

inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
})
sendBtn.addEventListener('click', sendMessage)

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
}

function updateTasks(tasks) {
  const el = document.getElementById('tasks-list')
  if (!tasks || !tasks.length) {
    el.innerHTML = '<div class="no-tasks">No active tasks</div>'
    return
  }
  el.innerHTML = tasks.map(t =>
    '<div class="task-item">' +
    '<div class="task-id">[' + esc(t.id) + ']</div>' +
    '<div class="task-title">' + esc(t.title) + '</div>' +
    '<div class="task-steps">' + (t.steps||[]).length + ' steps</div>' +
    '</div>'
  ).join('')
}

function updateStatus(s) {
  const set = (id, v) => { const e=document.getElementById(id); if(e) e.textContent=v }
  set('s-model', (s.model||'').split(':')[0])
  if (s.cpu_percent !== undefined) set('s-cpu', s.cpu_percent + '%')
  if (s.ram_used_gb !== undefined) set('s-ram', s.ram_used_gb + ' / ' + s.ram_total_gb + ' GB')
  if (s.disk_used_gb !== undefined) set('s-disk', s.disk_used_gb + ' / ' + s.disk_total_gb + ' GB')
  else if (s.disk_info) set('s-disk', s.disk_info)
  document.getElementById('header-status').textContent = 'online'
}

async function poll() {
  try {
    const [tr, sr] = await Promise.all([fetch('/tasks'), fetch('/status')])
    updateTasks((await tr.json()).tasks || [])
    updateStatus(await sr.json())
  } catch { document.getElementById('header-status').textContent = 'offline' }
}

poll()
setInterval(poll, 5000)
</script>
</body>
</html>"""
