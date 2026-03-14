/**
 * api.js — Network abstraction layer.
 * All fetch() calls live here. UI components never call fetch() directly.
 */

const API_BASE = window.location.origin;

const API = (() => {
  async function _post(path, body) {
    const res = await fetch(API_BASE + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  async function _get(path, params = {}) {
    const url = new URL(API_BASE + path);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  /**
   * Send a chat message.
   * @param {string} message
   * @returns {Promise<{response: string}>}
   */
  async function sendMessage(message) {
    return _post('/chat', { message });
  }

  /**
   * Get system status (CPU, RAM, Disk, models).
   * @returns {Promise<object>}
   */
  async function getStatus() {
    return _get('/status');
  }

  /**
   * Get all active tasks.
   * @returns {Promise<{tasks: Array, count: number}>}
   */
  async function getTasks() {
    return _get('/tasks');
  }

  /**
   * Get conversation log lines.
   * @param {number} lines
   * @returns {Promise<{log: string, lines: number}>}
   */
  async function getLogs(lines = 100) {
    return _get('/logs', { lines });
  }

  /**
   * Set active persona mode. Backend respects locked flag.
   * @param {string} mode  — 'default' | 'coding' | 'teacher' | 'assistant'
   * @param {boolean} locked — prevent auto-switching
   * @returns {Promise<{mode: string, locked: boolean}>}
   */
  async function setPersona(mode, locked = false) {
    return _post('/persona', { mode, locked });
  }

  /**
   * Get latest screen OCR cache.
   * @returns {Promise<{text: string, timestamp: string, mode: string}>}
   */
  async function getScreen() {
    return _get('/screen');
  }

  /**
   * Get recent tool activity feed.
   * @param {number} limit
   * @returns {Promise<{feed: Array, count: number}>}
   */
  async function getToolFeed(limit = 15) {
    return _get('/tool-feed', { limit });
  }

  /**
   * Health check.
   * @returns {Promise<{status: string, model: string}>}
   */
  async function getHealth() {
    return _get('/health');
  }

  /**
   * Get autonomous mode state.
   * @returns {Promise<{enabled: boolean}>}
   */
  async function getAutonomous() {
    return _get('/autonomous');
  }

  /**
   * Enable or disable autonomous background tasks.
   * @param {boolean} enabled
   * @returns {Promise<{enabled: boolean, status: string}>}
   */
  async function setAutonomous(enabled) {
    return _post('/autonomous', { enabled });
  }

  /**
   * Get all todos.
   * @returns {Promise<{todos: Array, count: number}>}
   */
  async function getTodos() {
    return _get('/todos');
  }

  /**
   * Update a todo item's status.
   * @param {string} id
   * @param {string} status  'pending' | 'in_progress' | 'done'
   */
  async function updateTodo(id, status) {
    const res = await fetch(`${API_BASE}/todos/${encodeURIComponent(id)}`, {
      method:  'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ status }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  return { sendMessage, getStatus, getTasks, getLogs, setPersona, getScreen, getHealth,
           getToolFeed, getAutonomous, setAutonomous, getTodos, updateTodo };
})();
