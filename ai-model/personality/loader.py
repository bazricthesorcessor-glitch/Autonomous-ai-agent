# ========================= personality/loader.py =========================
"""
Picks the right persona prompt based on the user's request.
Brain selects a mode; loader returns the filled prompt string.
"""
import os
import config

_DIR = os.path.dirname(os.path.abspath(__file__))

_MODE_KEYWORDS = {
    'coding':    ['write code', 'python code', 'script for', 'function def', 'debug code',
                  'fix code', 'algorithm', 'compile error', 'syntax error', 'bash script',
                  'write a program', 'refactor', 'write a function', 'traceback'],
    'teacher':   ['explain how', 'teach me', 'how does .* work', 'learn about',
                  'tutorial', 'concept of', 'why does .* work', 'meaning of',
                  'what is the difference between'],
    'assistant': ['open ', 'click ', 'type ', 'run ', 'execute ', 'screenshot',
                  'move file', 'copy file', 'search for', 'search web', 'play ',
                  'launch ', 'start ', 'show me', 'install ', 'download ',
                  'go to ', 'browse '],
}

_CACHE = {}


def _load_file(mode: str) -> str:
    if mode not in _CACHE:
        path = os.path.join(_DIR, f"{mode}.txt")
        try:
            with open(path, 'r') as f:
                _CACHE[mode] = f.read()
        except FileNotFoundError:
            if mode != 'default':
                _CACHE[mode] = _load_file('default')
            else:
                _CACHE[mode] = f"You are {config.AI_NAME}, a helpful AI assistant for {{user_name}}."
    return _CACHE[mode]


def detect_mode(user_message: str) -> str:
    """Returns the best mode for this message: 'coding', 'teacher', 'assistant', or 'default'."""
    lower = user_message.lower()
    scores = {mode: 0 for mode in _MODE_KEYWORDS}
    for mode, keywords in _MODE_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                scores[mode] += 1
    best = max(scores, key=scores.get)
    # Require at least 1 match; for 'teacher' require 2 to avoid false positives
    # (e.g. "what is my name?" should NOT trigger teacher mode)
    threshold = 2 if best == 'teacher' else 1
    return best if scores[best] >= threshold else 'default'


def get_persona(user_message: str) -> str:
    """Returns the persona prompt string for the given user message."""
    mode = detect_mode(user_message)
    template = _load_file(mode)
    return template.replace('{user_name}', config.USER_NAME)


def get_persona_for_mode(mode: str) -> str:
    """Returns the persona prompt for a specific mode, bypassing keyword detection.
    Used when the user has locked a personality via the UI.
    Falls back to 'default' if mode is unknown."""
    valid = set(_MODE_KEYWORDS.keys()) | {'default'}
    if mode not in valid:
        mode = 'default'
    template = _load_file(mode)
    return template.replace('{user_name}', config.USER_NAME)
