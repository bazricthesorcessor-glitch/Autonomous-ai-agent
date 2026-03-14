/**
 * chat.js — Chat panel: rendering, slash commands, send, new chat.
 * Depends on: api.js, settings.js
 */

const Chat = (() => {
  let _msgsEl   = null;
  let _inputEl  = null;
  let _sendBtn  = null;
  let _thinkEl  = null;
  let _busy     = false;

  const _STORAGE_KEY    = 'avril_chat_history';
  const _MAX_HISTORY    = 200;   // Cap to avoid filling localStorage
  const _MAX_MSG_STORE  = 4000;  // Truncate individual messages at this length
  let   _history        = [];    // [{role, text, ts}]

  // ── Persistence ────────────────────────────────────────────────────────────

  function _saveHistory() {
    try {
      localStorage.setItem(_STORAGE_KEY, JSON.stringify(_history));
    } catch (e) {
      // Storage full — trim and retry once
      _history = _history.slice(-Math.floor(_MAX_HISTORY / 2));
      try { localStorage.setItem(_STORAGE_KEY, JSON.stringify(_history)); } catch {}
    }
  }

  function _loadHistory() {
    try {
      const raw = localStorage.getItem(_STORAGE_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw);
      if (Array.isArray(saved)) {
        saved.forEach(m => addMessage(m.role, m.text, m.ts, true /* replay */));
      }
    } catch {}
  }

  // ── Helpers ────────────────────────────────────────────────────────────────

  function _escHtml(s) {
    return String(s)
      .replace(/&/g,  '&amp;')
      .replace(/</g,  '&lt;')
      .replace(/>/g,  '&gt;')
      .replace(/"/g,  '&quot;');
  }

  function _ts() {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  // ── Todo card renderer ─────────────────────────────────────────────────────

  function _renderTodoCard(jsonStr) {
    let items;
    try { items = JSON.parse(jsonStr); } catch { return ''; }
    if (!Array.isArray(items) || !items.length) return '';

    const doneCount = items.filter(t => t.status === 'done').length;
    const rows = items.map(t => {
      const isDone    = t.status === 'done';
      const isActive  = t.status === 'in_progress';
      const cls       = isDone ? 'todo-done' : isActive ? 'todo-progress' : 'todo-pending';
      const checked   = isDone ? 'checked' : '';
      return `<div class="todo-item ${cls}" data-id="${_escHtml(t.id)}">` +
             `<input type="checkbox" class="todo-cb" data-id="${_escHtml(t.id)}" ${checked}>` +
             `<span class="todo-content">${_escHtml(t.content)}</span></div>`;
    }).join('');

    return `<div class="todo-card">` +
           `<div class="todo-card-header">` +
           `<span class="todo-card-title">Tasks</span>` +
           `<span class="todo-card-count">${doneCount}/${items.length}</span></div>` +
           `<div class="todo-items">${rows}</div></div>`;
  }

  // ── Markdown renderer (subset: code blocks, inline code, bold, italic) ─────

  function _renderMarkdown(raw) {
    if (!raw) return '';

    // Extract __TODOS__ blocks FIRST (before _escHtml, which would corrupt JSON)
    const _todoBlocks = [];
    const _stripped   = raw.replace(/__TODOS__\n?([\s\S]*?)\n?__TODOS__/g, (_, json) => {
      const idx = _todoBlocks.length;
      _todoBlocks.push(json.trim());
      return `___TD_${idx}___`;
    });

    // Escape HTML so injected tags are safe
    let s = _escHtml(_stripped);

    // Fenced code blocks: ```lang?\ncode\n```  — wrapped for copy-button support
    s = s.replace(/```[^\n]*\n?([\s\S]*?)```/g,
      (_, code) => `<div class="code-block"><pre><code>${code.trimEnd()}</code></pre><button class="code-copy-btn" title="Copy code">copy</button></div>`);

    // Inline code: `code`
    s = s.replace(/`([^`\n]+)`/g, '<code>$1</code>');

    // Bold: **text**
    s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

    // Italic: *text*  — uses only lookahead (no lookbehind — avoids Safari/old Chrome bugs)
    s = s.replace(/\*(?!\*)([^*\n]+?)\*(?!\*)/g, '<em>$1</em>');

    // Markdown tables: | col | col | rows
    s = s.replace(/((?:\|[^\n]+\|\s*\n?){2,})/g, (block) => {
      const rows = block.trim().split('\n').filter(r => r.trim());
      const isSep = r => /^\| *[-:| ]+\|$/.test(r.trim());
      const toCell = (r, tag) =>
        r.split('|').slice(1, -1).map(c => `<${tag}>${c.trim()}</${tag}>`).join('');
      let html = '<table class="md-table">';
      if (rows.length >= 2 && isSep(rows[1])) {
        html += `<thead><tr>${toCell(rows[0], 'th')}</tr></thead><tbody>`;
        for (let i = 2; i < rows.length; i++) {
          if (!isSep(rows[i])) html += `<tr>${toCell(rows[i], 'td')}</tr>`;
        }
        html += '</tbody>';
      } else {
        html += '<tbody>';
        for (const r of rows) {
          if (!isSep(r)) html += `<tr>${toCell(r, 'td')}</tr>`;
        }
        html += '</tbody>';
      }
      return html + '</table>';
    });

    // Bullet lists: lines starting with "- "
    s = s.replace(/((?:^- .+\n?)+)/gm, (block) => {
      const items = block.trim().split('\n').map(l => `<li>${l.slice(2)}</li>`).join('');
      return `<ul>${items}</ul>`;
    });

    // Line breaks (preserve newlines outside block elements)
    s = s.replace(/\n(?!<\/(ul|pre|li))/g, '<br>');

    // Restore todo cards (placeholders were set before escaping)
    if (_todoBlocks.length) {
      _todoBlocks.forEach((json, idx) => {
        s = s.replace(`___TD_${idx}___`, _renderTodoCard(json));
      });
    }

    return s;
  }

  // ── Message rendering ──────────────────────────────────────────────────────

  function addMessage(role, text, timestamp, replay = false) {
    const ts  = timestamp || _ts();
    const div = document.createElement('div');
    div.className = `msg msg-${role}`;

    if (role !== 'system') {
      const meta   = document.createElement('div');
      meta.className = 'msg-meta';

      const sender = document.createElement('span');
      sender.className = 'msg-sender';
      sender.textContent = role === 'user' ? 'You' : 'Avril';

      const time   = document.createElement('span');
      time.className = 'msg-time';
      time.textContent = ts;

      meta.appendChild(sender);
      meta.appendChild(time);
      div.appendChild(meta);
    }

    const body = document.createElement('div');
    body.className = 'msg-body';

    if (role === 'avril') {
      body.innerHTML = _renderMarkdown(text);
      // Attach copy handlers to per-code-block copy buttons
      body.querySelectorAll('.code-copy-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const code = btn.previousElementSibling.querySelector('code').textContent;
          navigator.clipboard.writeText(code).then(() => {
            btn.textContent = 'copied!';
            setTimeout(() => { btn.textContent = 'copy'; }, 1500);
          }).catch(() => {
            btn.textContent = 'fail';
            setTimeout(() => { btn.textContent = 'copy'; }, 1500);
          });
        });
      });

      // Attach todo checkbox listeners — check/uncheck updates backend
      body.querySelectorAll('.todo-cb').forEach(cb => {
        cb.addEventListener('change', async () => {
          const id        = cb.dataset.id;
          const newStatus = cb.checked ? 'done' : 'pending';
          const item      = cb.closest('.todo-item');
          if (item) item.className = `todo-item ${cb.checked ? 'todo-done' : 'todo-pending'}`;
          // Update progress counter in card header
          const card = cb.closest('.todo-card');
          if (card) {
            const total   = card.querySelectorAll('.todo-cb').length;
            const done    = card.querySelectorAll('.todo-cb:checked').length;
            const counter = card.querySelector('.todo-card-count');
            if (counter) counter.textContent = `${done}/${total}`;
          }
          try { await API.updateTodo(id, newStatus); }
          catch (e) { console.warn('[Todo] update failed:', e); }
        });
      });
    } else {
      body.textContent = text;
    }

    div.appendChild(body);

    // Copy button on Avril messages
    if (role === 'avril') {
      const actions = document.createElement('div');
      actions.className = 'msg-actions';

      const btn = document.createElement('button');
      btn.className   = 'copy-btn';
      btn.textContent = 'copy';
      btn.addEventListener('click', () => {
        navigator.clipboard.writeText(text).then(() => {
          btn.textContent = 'copied!';
          setTimeout(() => { btn.textContent = 'copy'; }, 1500);
        }).catch(() => {
          btn.textContent = 'failed';
          setTimeout(() => { btn.textContent = 'copy'; }, 1500);
        });
      });

      actions.appendChild(btn);
      div.appendChild(actions);
    }

    _msgsEl.appendChild(div);
    _scrollBottom();

    // Persist user and avril messages (skip system/ephemeral, skip replay to avoid double-store)
    if (!replay && (role === 'user' || role === 'avril')) {
      // Truncate long messages before storing to prevent localStorage overflow
      const stored = text.length > _MAX_MSG_STORE ? text.slice(0, _MAX_MSG_STORE) + '\u2026' : text;
      _history.push({ role, text: stored, ts });
      if (_history.length > _MAX_HISTORY) _history = _history.slice(-_MAX_HISTORY);
      _saveHistory();
    }

    return div;
  }

  function _scrollBottom() {
    requestAnimationFrame(() => { _msgsEl.scrollTop = _msgsEl.scrollHeight; });
  }

  // ── Thinking indicator ─────────────────────────────────────────────────────

  function showThinking() {
    _thinkEl.style.display = 'flex';
    _scrollBottom();
  }

  function hideThinking() {
    _thinkEl.style.display = 'none';
  }

  // ── Core send (used by public API and slash commands) ──────────────────────

  async function sendText(text) {
    if (!text) return;
    addMessage('user', text);
    showThinking();
    _busy = true;
    _updateBtn();

    try {
      const data = await API.sendMessage(text);
      if (data.response !== undefined) {
        addMessage('avril', data.response);
      } else {
        addMessage('system', 'Error: ' + (data.error || 'Empty response'));
      }
    } catch (e) {
      addMessage('system', 'Network error: ' + e.message);
    } finally {
      hideThinking();
      _busy = false;
      _updateBtn();
      _inputEl.focus();
    }
  }

  function _updateBtn() {
    _sendBtn.disabled = _busy;
  }

  // ── Slash command handler ──────────────────────────────────────────────────

  async function _handleSlash(raw) {
    const parts = raw.slice(1).trim().split(/\s+/);
    const cmd   = parts[0].toLowerCase();

    switch (cmd) {
      case 'help': {
        addMessage('system', [
          'Slash commands:',
          '  /help      — this list',
          '  /status    — system status',
          '  /tasks     — active tasks',
          '  /memory    — memory + facts',
          '  /restart   — restart info',
          '',
          'Also works: !status  !tasks  !abort  !memory  !restart',
          '',
          'Keyboard: Ctrl+K → new chat',
        ].join('\n'));
        return;
      }

      case 'status': {
        addMessage('user', '/status');
        showThinking();
        try {
          const s     = await API.getStatus();
          const lines = ['System Status:'];
          if (s.cpu_percent  !== undefined) lines.push(`  CPU    : ${s.cpu_percent}%`);
          if (s.ram_used_gb  !== undefined) lines.push(`  RAM    : ${s.ram_used_gb} / ${s.ram_total_gb} GB  (${s.ram_percent}%)`);
          if (s.disk_used_gb !== undefined) lines.push(`  Disk   : ${s.disk_used_gb} / ${s.disk_total_gb} GB  (${s.disk_percent}%)`);
          else if (s.disk_info)             lines.push(`  Disk   : ${s.disk_info}`);
          if (s.model)                      lines.push(`  Model  : ${s.model}`);
          if (s.decision_model)             lines.push(`  Planner: ${s.decision_model}`);
          addMessage('avril', lines.join('\n'));
        } catch (e) {
          addMessage('system', 'Could not reach /status: ' + e.message);
        } finally {
          hideThinking();
        }
        return;
      }

      case 'tasks': {
        addMessage('user', '/tasks');
        showThinking();
        try {
          const t = await API.getTasks();
          if (!t.tasks || !t.tasks.length) {
            addMessage('avril', 'No active tasks.');
          } else {
            const lines = [`Active Tasks (${t.count}):`];
            t.tasks.forEach(tk => {
              lines.push(`  [${tk.id}] ${tk.title} — ${(tk.steps || []).length} steps`);
            });
            addMessage('avril', lines.join('\n'));
          }
        } catch (e) {
          addMessage('system', 'Could not reach /tasks: ' + e.message);
        } finally {
          hideThinking();
        }
        return;
      }

      case 'memory':
      case 'restart': {
        // Delegate to backend via ! command
        await sendText('!' + cmd);
        return;
      }

      default: {
        addMessage('system', `Unknown command: /${cmd}  (type /help for list)`);
        return;
      }
    }
  }

  // ── Public send (reads input, applies extraPrompt) ─────────────────────────

  async function send() {
    const raw = _inputEl.value.trim();
    if (!raw || _busy) return;
    _busy = true;        // Lock FIRST — prevents double-submit before any async work
    _updateBtn();
    _inputEl.value = '';

    if (raw.startsWith('/')) {
      // Slash command path — always unlock when done
      try {
        await _handleSlash(raw);
      } finally {
        _busy = false;
        _updateBtn();
        _inputEl.focus();
      }
      return;
    }

    // Apply extra prompt prefix (stored in settings)
    const extra   = Settings.get('extraPrompt');
    const payload = extra ? `${extra.trim()}\n\n${raw}` : raw;

    // Show the original (un-prefixed) text in UI, send the full payload to API
    addMessage('user', raw);
    showThinking();

    try {
      const data = await API.sendMessage(payload);
      if (data.response !== undefined) {
        addMessage('avril', data.response);
      } else {
        addMessage('system', 'Error: ' + (data.error || 'Empty response'));
      }
    } catch (e) {
      addMessage('system', 'Network error: ' + e.message);
    } finally {
      hideThinking();
      _busy = false;
      _updateBtn();
      _inputEl.focus();
    }
  }

  // ── New chat ───────────────────────────────────────────────────────────────

  function newChat() {
    _msgsEl.innerHTML = '';
    _history = [];
    try { localStorage.removeItem(_STORAGE_KEY); } catch {}
    addMessage('system', 'New chat started. Memory and facts are preserved.');
    _inputEl.focus();
  }

  // ── Init ───────────────────────────────────────────────────────────────────

  function init() {
    _msgsEl  = document.getElementById('messages');
    _inputEl = document.getElementById('msg-input');
    _sendBtn = document.getElementById('send-btn');
    _thinkEl = document.getElementById('thinking-bar');

    _sendBtn.addEventListener('click', send);
    _inputEl.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });

    document.getElementById('new-chat-btn').addEventListener('click', newChat);

    // Global keyboard shortcut: Ctrl+K → new chat
    document.addEventListener('keydown', e => {
      if (e.ctrlKey && e.key === 'k') { e.preventDefault(); newChat(); }
    });

    // Restore previous session messages, then show ready prompt
    _loadHistory();
    if (_history.length === 0) {
      addMessage('system', 'Avril is ready.  Type /help for frontend commands.');
    }
  }

  return { init, send, sendText, newChat, addMessage, showThinking, hideThinking };
})();
