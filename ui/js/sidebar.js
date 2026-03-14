/**
 * sidebar.js — Three-dot settings panel + real-time status polling.
 * Depends on: api.js, settings.js, chat.js
 */

const Sidebar = (() => {
  let _panelEl   = null;
  let _overlayEl = null;
  let _isOpen    = false;

  let _screenWatchInterval = null;
  let _statusInterval      = null;

  let _taskCache    = [];   // latest [{id, title, steps, status}] from /tasks
  let _toolFeedCache= [];   // latest [{tool, timestamp, result_preview, error}] from /tool-feed
  let _autoEnabled  = true; // cached autonomous mode state

  // ── Panel open / close / toggle ────────────────────────────────────────────

  function open() {
    _buildPanel();       // rebuild to reflect current state before opening
    _isOpen = true;
    _panelEl.classList.add('open');
    _overlayEl.classList.add('active');
  }

  function close() {
    _isOpen = false;
    _panelEl.classList.remove('open');
    _overlayEl.classList.remove('active');
  }

  function toggle() {
    _isOpen ? close() : open();
  }

  // ── Persona ────────────────────────────────────────────────────────────────

  async function _applyPersona(mode) {
    const locked = Settings.get('personalityLocked');
    Settings.set('personality', mode);
    _updateModeButtons(mode);
    try {
      await API.setPersona(mode, locked);
    } catch (e) {
      console.warn('[Sidebar] setPersona failed:', e.message);
    }
  }

  function _updateModeButtons(active) {
    if (!_panelEl) return;
    _panelEl.querySelectorAll('.mode-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.mode === active);
    });
  }

  // ── Screen watch ──────────────────────────────────────────────────────────

  function _startScreenWatch() {
    // Guard prevents duplicate intervals if called more than once (BUG 6).
    // _statusInterval (status) and _screenWatchInterval (screen) are independent
    // — they share the same 5s cadence but never interfere with each other.
    if (_screenWatchInterval) return;
    _fetchAndShowScreen();                          // immediate first read
    _screenWatchInterval = setInterval(_fetchAndShowScreen, 5000);
  }

  async function _fetchAndShowScreen() {
    try {
      const data = await API.getScreen();
      _setScreenText(
        data.text
          ? `[${data.timestamp}]\n${data.text.slice(0, 600)}`
          : 'No screen data yet.'
      );
      // Active Avril form detection
      if (Settings.get('activeMode') && data.text) {
        const lower    = data.text.toLowerCase();
        const formKeys = ['name', 'email', 'address', 'phone', 'submit', 'password'];
        const hits     = formKeys.filter(k => lower.includes(k));
        if (hits.length >= 2) _showFormBanner();
      }
    } catch {
      _setScreenText('Screen data unavailable.');
    }
  }

  function _stopScreenWatch() {
    if (_screenWatchInterval) {
      clearInterval(_screenWatchInterval);
      _screenWatchInterval = null;
    }
    _setScreenText('Screen watch disabled.');
  }

  function _setScreenText(text) {
    const el = document.getElementById('screen-text');
    if (el) el.textContent = text;
  }

  // ── Form-assist banner ────────────────────────────────────────────────────

  function _showFormBanner() {
    if (document.getElementById('form-assist-banner')) return;   // already shown

    const banner = document.createElement('div');
    banner.id        = 'form-assist-banner';
    banner.className = 'form-assist-banner';
    banner.innerHTML = `
      <span>Avril detected a form. Assist filling?</span>
      <button id="fa-yes">Yes</button>
      <button id="fa-no">Dismiss</button>
    `;
    document.body.appendChild(banner);

    document.getElementById('fa-yes').addEventListener('click', () => {
      banner.remove();
      Chat.sendText('There is a form visible on screen. Please help me fill it out.');
    });
    document.getElementById('fa-no').addEventListener('click', () => banner.remove());
  }

  // ── Mini status (header dot + panel stats) ─────────────────────────────────

  async function _refreshStatus() {
    try {
      const s   = await API.getStatus();
      const dot = document.getElementById('header-dot');
      if (dot) { dot.className = 'dot dot-online'; dot.title = 'online'; }

      const set = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
      if (s.cpu_percent  !== undefined) set('mini-cpu',   s.cpu_percent + '%');
      if (s.ram_percent  !== undefined) set('mini-ram',   s.ram_percent + '%');
      if (s.model)                      set('mini-model', s.model.split(':')[0]);
    } catch {
      const dot = document.getElementById('header-dot');
      if (dot) { dot.className = 'dot dot-offline'; dot.title = 'offline'; }
    }
  }

  // ── Task Viewer + Tool Feed ────────────────────────────────────────────────

  async function _refreshTasks() {
    try {
      const data  = await API.getTasks();
      _taskCache  = data.tasks || [];
      _renderTaskViewer();
    } catch {}
  }

  async function _refreshToolFeed() {
    try {
      const data    = await API.getToolFeed(15);
      _toolFeedCache = data.feed || [];
      _renderToolFeed();
    } catch {}
  }

  function _renderTaskViewer() {
    const el = document.getElementById('task-viewer-list');
    if (!el) return;
    if (!_taskCache.length) {
      el.innerHTML = '<div class="feed-empty">No active tasks</div>';
      return;
    }
    el.innerHTML = _taskCache.map(t => `
      <div class="task-card">
        <div class="task-card-title">${_esc(t.title)}</div>
        <div class="task-card-meta">[${_esc(t.id)}] &middot; ${(t.steps||[]).length} steps &middot; ${_esc(t.status||'active')}</div>
      </div>
    `).join('');
  }

  function _renderToolFeed() {
    const el = document.getElementById('tool-feed-list');
    if (!el) return;
    if (!_toolFeedCache.length) {
      el.innerHTML = '<div class="feed-empty">No tool activity yet</div>';
      return;
    }
    el.innerHTML = _toolFeedCache.slice(0, 10).map(f => `
      <div class="feed-item${f.error ? ' feed-item-error' : ''}">
        <div class="feed-item-header">
          <span class="feed-tool">${_esc(f.tool)}</span>
          <span class="feed-ts">${_esc(f.timestamp)}</span>
        </div>
        <div class="feed-result">${_esc((f.result_preview||'').slice(0, 120))}</div>
      </div>
    `).join('');
  }

  // ── Autonomous mode ───────────────────────────────────────────────────────

  async function _fetchAutoState() {
    try {
      const data  = await API.getAutonomous();
      _autoEnabled = data.enabled;
      _updateAutoBtn();
    } catch {}
  }

  function _updateAutoBtn() {
    const btn = document.getElementById('auto-btn');
    if (!btn) return;
    if (_autoEnabled) {
      btn.textContent = '⬢ AUTO';
      btn.className   = 'auto-btn-on';
      btn.title       = 'Autonomous tasks ON — click to pause';
    } else {
      btn.textContent = '⬡ AUTO';
      btn.className   = 'auto-btn-off';
      btn.title       = 'Autonomous tasks OFF — click to resume';
    }
  }

  async function _toggleAuto() {
    const next = !_autoEnabled;
    try {
      await API.setAutonomous(next);
      _autoEnabled = next;
      _updateAutoBtn();
      // Sync the toggle inside the panel if it is open
      const tog = document.getElementById('toggle-autonomous');
      if (tog) tog.checked = _autoEnabled;
    } catch (e) {
      console.warn('[Sidebar] setAutonomous failed:', e.message);
    }
  }

  // ── Sidebar todos ─────────────────────────────────────────────────────────

  async function _refreshTodos() {
    try {
      const data = await API.getTodos();
      _renderSidebarTodos(data.todos || []);
    } catch {}
  }

  function _renderSidebarTodos(todos) {
    const el = document.getElementById('sidebar-todos');
    if (!el) return;
    if (!todos.length) {
      el.innerHTML = '<div class="feed-empty">No todos yet</div>';
      return;
    }
    el.innerHTML = todos.map(t => {
      const isDone    = t.status === 'done';
      const isActive  = t.status === 'in_progress';
      const cls = isDone ? 'stodo-done' : isActive ? 'stodo-progress' : '';
      return `<label class="stodo-item ${cls}">` +
             `<input type="checkbox" class="stodo-cb" data-id="${_esc(t.id)}" ${isDone ? 'checked' : ''}>` +
             `<span class="stodo-text">${_esc(t.content)}</span></label>`;
    }).join('');
    // Attach listeners after render
    el.querySelectorAll('.stodo-cb').forEach(cb => {
      cb.addEventListener('change', async () => {
        const newStatus = cb.checked ? 'done' : 'pending';
        const item = cb.closest('.stodo-item');
        if (item) item.className = `stodo-item ${cb.checked ? 'stodo-done' : ''}`;
        try { await API.updateTodo(cb.dataset.id, newStatus); } catch {}
      });
    });
  }

  // ── Build panel HTML ───────────────────────────────────────────────────────
  // Rebuilt every time the panel is opened so it always reflects current state.

  function _esc(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function _buildPanel() {
    const st    = Settings.getAll();
    const modes = ['default', 'coding', 'teacher', 'assistant'];

    _panelEl.innerHTML = `
      <div class="panel-header">
        <span>Settings</span>
        <button class="close-btn" id="panel-close" title="Close">✕</button>
      </div>

      <div class="panel-body">

        <!-- ── Mode ───────────────────────────────────────────────────── -->
        <section class="settings-section">
          <h3>Mode</h3>
          <div class="mode-buttons">
            ${modes.map(m => `
              <button class="mode-btn${st.personality === m ? ' active' : ''}" data-mode="${m}">
                ${m.charAt(0).toUpperCase() + m.slice(1)}
              </button>`).join('')}
          </div>
        </section>

        <!-- ── Personality ─────────────────────────────────────────────── -->
        <section class="settings-section">
          <h3>Personality</h3>
          <label class="toggle-label">
            <span>Lock Personality</span>
            <input type="checkbox" id="lock-personality" ${st.personalityLocked ? 'checked' : ''}>
            <span class="toggle-switch"></span>
          </label>
          <p class="hint">When locked, Avril won't auto-switch mode based on keywords.</p>
        </section>

        <!-- ── Extra Prompt ────────────────────────────────────────────── -->
        <section class="settings-section">
          <h3>Extra Prompt</h3>
          <textarea id="extra-prompt" rows="3"
            placeholder="Prepended silently to every message…">${_esc(st.extraPrompt)}</textarea>
          <p class="hint">Example: "Always respond concisely and in plain text."</p>
        </section>

        <!-- ── Active Features ─────────────────────────────────────────── -->
        <section class="settings-section">
          <h3>Active Features</h3>

          <div class="toggle-row toggle-row-auto">
            <label class="toggle-label">
              <span>Autonomous Tasks</span>
              <input type="checkbox" id="toggle-autonomous" ${_autoEnabled ? 'checked' : ''}>
              <span class="toggle-switch toggle-switch-auto"></span>
            </label>
            <p class="hint">Background goals run silently — no chat messages. Toggle also changes the AUTO button.</p>
          </div>

          <div class="toggle-row">
            <label class="toggle-label">
              <span>Active Avril</span>
              <input type="checkbox" id="toggle-active" ${st.activeMode ? 'checked' : ''}>
              <span class="toggle-switch"></span>
            </label>
            <p class="hint">Poll screen every 5 s and offer to help with detected forms.</p>
          </div>

          <div class="toggle-row">
            <label class="toggle-label">
              <span>Screen Watch</span>
              <input type="checkbox" id="toggle-screen" ${st.screenWatch ? 'checked' : ''}>
              <span class="toggle-switch"></span>
            </label>
            <p class="hint">Show latest OCR output in this panel.</p>
          </div>
        </section>

        <!-- ── Screen output (visible if screenWatch on) ───────────────── -->
        <section class="settings-section" id="screen-watch-section"
          style="display:${st.screenWatch ? 'block' : 'none'}">
          <h3>Latest Screen</h3>
          <pre id="screen-text" class="screen-pre">Loading…</pre>
        </section>

        <!-- ── Voice ──────────────────────────────────────────────────── -->
        <section class="settings-section">
          <h3>Voice</h3>
          <p class="hint muted">Coming soon.</p>
        </section>

        <!-- ── Active Tasks ───────────────────────────────────────────── -->
        <section class="settings-section">
          <h3>Active Tasks</h3>
          <div id="task-viewer-list" class="feed-list"></div>
        </section>

        <!-- ── Todos ──────────────────────────────────────────────────── -->
        <section class="settings-section">
          <h3>Todos</h3>
          <div id="sidebar-todos" class="feed-list"></div>
          <button id="clear-done-btn" class="hint-btn" style="margin-top:6px">Clear completed</button>
        </section>

        <!-- ── Tool Activity ──────────────────────────────────────────── -->
        <section class="settings-section">
          <h3>Tool Activity</h3>
          <div id="tool-feed-list" class="feed-list"></div>
        </section>

        <!-- ── System mini-stats ──────────────────────────────────────── -->
        <section class="settings-section">
          <h3>System</h3>
          <div class="mini-stat"><span class="sl">CPU  </span><span id="mini-cpu"   class="sv">-</span></div>
          <div class="mini-stat"><span class="sl">RAM  </span><span id="mini-ram"   class="sv">-</span></div>
          <div class="mini-stat"><span class="sl">Model</span><span id="mini-model" class="sv">-</span></div>
        </section>

      </div>
    `;

    // ── Bind events ──────────────────────────────────────────────────────────

    document.getElementById('panel-close').addEventListener('click', close);

    _panelEl.querySelectorAll('.mode-btn').forEach(btn => {
      btn.addEventListener('click', () => _applyPersona(btn.dataset.mode));
    });

    document.getElementById('lock-personality').addEventListener('change', e => {
      Settings.set('personalityLocked', e.target.checked);
      // Push updated lock state to backend with current mode
      API.setPersona(Settings.get('personality'), e.target.checked).catch(() => {});
    });

    document.getElementById('extra-prompt').addEventListener('input', e => {
      Settings.set('extraPrompt', e.target.value);
    });

    document.getElementById('toggle-autonomous').addEventListener('change', async e => {
      try {
        await API.setAutonomous(e.target.checked);
        _autoEnabled = e.target.checked;
        _updateAutoBtn();
      } catch (err) {
        console.warn('[Sidebar] setAutonomous:', err.message);
        e.target.checked = _autoEnabled; // Revert on failure
      }
    });

    document.getElementById('toggle-active').addEventListener('change', e => {
      Settings.set('activeMode', e.target.checked);
      // Screen watch is required for Active Avril; auto-enable it
      if (e.target.checked && !Settings.get('screenWatch')) {
        const sw = document.getElementById('toggle-screen');
        if (sw) sw.checked = true;
        Settings.set('screenWatch', true);
        document.getElementById('screen-watch-section').style.display = 'block';
        _startScreenWatch();
      }
    });

    document.getElementById('toggle-screen').addEventListener('change', e => {
      Settings.set('screenWatch', e.target.checked);
      const section = document.getElementById('screen-watch-section');
      if (e.target.checked) {
        section.style.display = 'block';
        _startScreenWatch();
      } else {
        section.style.display = 'none';
        _stopScreenWatch();
        Settings.set('activeMode', false);            // also disable active mode
        const ta = document.getElementById('toggle-active');
        if (ta) ta.checked = false;
      }
    });

    // Refresh status numbers inside panel immediately
    _refreshStatus();

    // Render cached task/feed/todo data immediately, then fetch fresh
    _renderTaskViewer();
    _renderToolFeed();
    _refreshTasks();
    _refreshToolFeed();
    _refreshTodos();

    // Clear-done todos button
    const clearDoneBtn = document.getElementById('clear-done-btn');
    if (clearDoneBtn) {
      clearDoneBtn.addEventListener('click', async () => {
        try {
          await fetch(window.location.origin + '/todos/clear-done', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }
          });
        } catch {}
        await _refreshTodos();
      });
    }

    // If screen watch was already active, start showing data
    if (Settings.get('screenWatch')) _fetchAndShowScreen();
  }

  // ── Init ───────────────────────────────────────────────────────────────────

  function init() {
    _panelEl   = document.getElementById('settings-panel');
    _overlayEl = document.getElementById('overlay');

    document.getElementById('menu-btn').addEventListener('click', toggle);
    _overlayEl.addEventListener('click', close);

    // Escape key closes panel
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && _isOpen) close();
    });

    // AUTO button in header — click toggles autonomous mode
    const autoBtn = document.getElementById('auto-btn');
    if (autoBtn) autoBtn.addEventListener('click', _toggleAuto);

    // Fetch autonomous mode from backend and update button immediately
    _fetchAutoState();

    // Global status dot polling
    _refreshStatus();
    _statusInterval = setInterval(_refreshStatus, 5000);

    // Background task + todo polling (keeps cache warm; renders on panel open)
    _refreshTasks();
    _refreshTodos();
    setInterval(_refreshTasks, 10000);
    setInterval(_refreshTodos, 15000);

    // Resume screen watch if it was on when page was last closed
    if (Settings.get('screenWatch')) _startScreenWatch();
  }

  return { init, open, close, toggle };
})();
