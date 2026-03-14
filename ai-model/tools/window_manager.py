# ========================= tools/window_manager.py =========================
"""
Hyprland window management via hyprctl.

Supported actions (pass via args dict):
  list_windows   : {}  → returns list of open windows
  focus_window   : {"app": str}  → focus window matching class/title
  launch_app     : {"app": str}  → launch an application
  close_window   : {"app": str (optional)}  → close active or named window
  get_active     : {}  → get info about the currently focused window

This is a SAFE tool — no confirmation required.
Use this BEFORE resorting to mouse automation.
"""
import json
import subprocess


def _run(cmd: list, timeout: int = 5) -> tuple[int, str, str]:
    """Run a subprocess command. Returns (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except Exception as e:
        return -1, "", str(e)


def _list_windows() -> str:
    code, out, err = _run(["hyprctl", "-j", "clients"])
    if code != 0:
        return f"Error listing windows: {err}"
    try:
        clients = json.loads(out)
        if not clients:
            return "No open windows found."
        lines = []
        for c in clients:
            title = c.get("title", "").strip()
            wm_class = c.get("class", "").strip()
            workspace = c.get("workspace", {}).get("name", "?")
            lines.append(f"  [{wm_class}] {title}  (workspace: {workspace})")
        return f"Open windows ({len(lines)}):\n" + "\n".join(lines)
    except Exception as e:
        return f"Error parsing window list: {e}"


def _focus_window(app: str) -> str:
    if not app:
        return "Error: 'app' argument is required for focus_window"
    # hyprctl dispatch focuswindow accepts class name or title
    code, out, err = _run(["hyprctl", "dispatch", "focuswindow", app])
    if code == 0:
        return f"Focused window: {app}"
    # Try title match as fallback
    code2, out2, err2 = _run(["hyprctl", "dispatch", "focuswindow", f"title:{app}"])
    if code2 == 0:
        return f"Focused window by title: {app}"
    return f"Could not focus '{app}': {err or err2}"


def _launch_app(app: str) -> str:
    if not app:
        return "Error: 'app' argument is required for launch_app"
    code, out, err = _run(["hyprctl", "dispatch", "exec", app])
    if code == 0:
        return f"Launched: {app}"
    return f"Error launching '{app}': {err}"


def _close_window(app: str = "") -> str:
    if app:
        # Focus first, then close
        _focus_window(app)
    code, out, err = _run(["hyprctl", "dispatch", "closewindow", "active"])
    if code == 0:
        return f"Closed window{f': {app}' if app else ' (active)'}"
    # Fallback — killactive
    code2, out2, err2 = _run(["hyprctl", "dispatch", "killactive"])
    if code2 == 0:
        return f"Closed active window"
    return f"Error closing window: {err or err2}"


def _get_active() -> str:
    code, out, err = _run(["hyprctl", "-j", "activewindow"])
    if code != 0:
        return f"Error getting active window: {err}"
    try:
        data = json.loads(out)
        title = data.get("title", "unknown")
        wm_class = data.get("class", "unknown")
        at = data.get("at", [0, 0])
        size = data.get("size", [0, 0])
        workspace = data.get("workspace", {}).get("name", "?")
        return (
            f"Active window:\n"
            f"  Class    : {wm_class}\n"
            f"  Title    : {title}\n"
            f"  Position : {at[0]},{at[1]}\n"
            f"  Size     : {size[0]}x{size[1]}\n"
            f"  Workspace: {workspace}"
        )
    except Exception as e:
        return f"Error parsing active window: {e}"


def run_tool(args=None):
    """
    Window management for Hyprland.

    Args:
        args (dict): Must contain 'action'. Extra keys depend on action.

    Returns:
        str: Result string.
    """
    if args is None:
        args = {}

    action = args.get("action", "")

    try:
        if action == "list_windows":
            return _list_windows()

        elif action == "focus_window":
            return _focus_window(args.get("app", ""))

        elif action in ("launch_app", "open"):
            return _launch_app(args.get("app", ""))

        elif action == "close_window":
            return _close_window(args.get("app", ""))

        elif action == "get_active":
            return _get_active()

        else:
            return (
                f"Unknown action: '{action}'. "
                "Available: list_windows, focus_window, launch_app, open, close_window, get_active"
            )

    except Exception as e:
        return f"Error in window_manager tool: {str(e)}"
