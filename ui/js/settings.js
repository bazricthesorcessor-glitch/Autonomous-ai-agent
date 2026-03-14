/**
 * settings.js — App-wide state, persisted to localStorage.
 * This module has no DOM dependencies; safe to load first.
 */

const Settings = (() => {
  const STORAGE_KEY = 'avril_settings_v1';

  const _defaults = {
    personality: 'default',
    personalityLocked: false,
    extraPrompt: '',
    activeMode: false,
    screenWatch: false,
  };

  let _state = { ..._defaults };

  function load() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) _state = { ..._defaults, ...JSON.parse(raw) };
    } catch (e) {
      console.warn('[Settings] Load failed:', e);
      _state = { ..._defaults };
    }
  }

  function save() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(_state));
    } catch (e) {
      console.warn('[Settings] Save failed:', e);
    }
  }

  function get(key) {
    return _state[key];
  }

  function set(key, value) {
    _state[key] = value;
    save();
  }

  function getAll() {
    return { ..._state };
  }

  return { load, save, get, set, getAll };
})();
