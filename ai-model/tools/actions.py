# ========================= tools/actions.py =========================
"""
Mouse/keyboard automation via ydotool (Wayland-native).

Supported actions (pass via args dict):
  mouse_move  : {"action": "mouse_move", "x": int, "y": int}
  mouse_click : {"action": "mouse_click", "button": "left"|"right"|"middle"}
  type_text   : {"action": "type_text", "text": str}
  press_key   : {"action": "press_key", "key": str}  e.g. "ctrl+c", "Return"
  scroll      : {"action": "scroll", "direction": "up"|"down", "amount": int}

NOTE: Risky tool — requires WhatsApp confirmation before execution.
      ydotool must be running: sudo ydotoold
"""
import subprocess

_BUTTON_CODES = {
    'left':   '0xC0',   # 0x40 (press) | 0x80 (release) = click
    'right':  '0xC1',
    'middle': '0xC2',
}


def _run(cmd: list) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        return "ok"
    return result.stderr.strip() or "unknown error"


def run_tool(args=None):
    if args is None:
        args = {}

    action = args.get('action', '')

    try:
        if action == 'mouse_move':
            x = int(args.get('x', 0))
            y = int(args.get('y', 0))
            out = _run(['ydotool', 'mousemove', '--absolute', '-x', str(x), '-y', str(y)])
            return f"Mouse moved to ({x}, {y})" if out == "ok" else f"Error: {out}"

        elif action == 'mouse_click':
            btn = args.get('button', 'left')
            code = _BUTTON_CODES.get(btn, _BUTTON_CODES['left'])
            out = _run(['ydotool', 'click', code])
            return f"Clicked {btn}" if out == "ok" else f"Error: {out}"

        elif action == 'type_text':
            text = args.get('text', '')
            if not text:
                return "Error: no text provided"
            out = _run(['ydotool', 'type', '--', text])
            return "Text typed" if out == "ok" else f"Error: {out}"

        elif action == 'press_key':
            key = args.get('key', '')
            if not key:
                return "Error: no key provided"
            out = _run(['ydotool', 'key', key])
            return f"Key pressed: {key}" if out == "ok" else f"Error: {out}"

        elif action == 'scroll':
            direction = args.get('direction', 'down')
            amount = int(args.get('amount', 3))
            # Positive y = scroll down, negative y = scroll up
            delta = amount if direction == 'down' else -amount
            out = _run(['ydotool', 'scroll', '--', f'0:{delta * 120}'])
            return f"Scrolled {direction} x{amount}" if out == "ok" else f"Error: {out}"

        else:
            return (
                f"Unknown action: '{action}'. "
                "Available: mouse_move, mouse_click, type_text, press_key, scroll"
            )

    except FileNotFoundError:
        return "Error: ydotool not found. Install: sudo pacman -S ydotool / ensure ydotoold is running"
    except subprocess.TimeoutExpired:
        return "Error: ydotool command timed out"
    except Exception as e:
        return f"Error in actions tool: {str(e)}"
