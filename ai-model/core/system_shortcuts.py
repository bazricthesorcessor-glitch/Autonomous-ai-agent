# ========================= core/system_shortcuts.py =========================
"""
System shortcut awareness for Avril.

Gives the planner knowledge of Hyprland keyboard shortcuts so it can use
press_key (via actions tool) instead of slow mouse automation.

IMPORTANT: Update SHORTCUTS to match your actual hyprland.conf keybinds.
"""

# ── Hyprland keybindings ──────────────────────────────────────────────────────
# Keys use ydotool key format: Super = super_l, Return = Return, etc.
SHORTCUTS = {
    # Terminals
    "open_terminal":          "super_l+Return",
    # Windows
    "close_window":           "super_l+q",
    "toggle_fullscreen":      "super_l+f",
    "toggle_float":           "super_l+shift_l+space",
    # Workspaces
    "switch_workspace_1":     "super_l+1",
    "switch_workspace_2":     "super_l+2",
    "switch_workspace_3":     "super_l+3",
    "switch_workspace_4":     "super_l+4",
    "switch_workspace_5":     "super_l+5",
    # App launcher (wofi/rofi)
    "launcher":               "super_l+d",
    # Browser
    "browser":                "super_l+b",
    # Screenshots
    "screenshot_fullscreen":  "Print",
    "screenshot_region":      "super_l+Print",
    # Focus
    "focus_left":             "super_l+h",
    "focus_right":            "super_l+l",
    "focus_up":               "super_l+k",
    "focus_down":             "super_l+j",
    # Move window
    "move_left":              "super_l+shift_l+h",
    "move_right":             "super_l+shift_l+l",
    # Misc
    "lock_screen":            "super_l+shift_l+x",
    "reload_config":          "super_l+shift_l+r",
}

# ── Mouse gestures (for planner awareness, not direct execution) ──────────────
GESTURES = {
    "swipe_left":   "three-finger swipe left  → next workspace",
    "swipe_right":  "three-finger swipe right → prev workspace",
    "swipe_up":     "three-finger swipe up    → overview/expose",
}


def get_shortcuts_prompt() -> str:
    """
    Returns a compact string describing available shortcuts for the planner.
    Inject this into the planner system prompt so it prefers shortcuts over mouse.
    """
    lines = ["SYSTEM SHORTCUTS (use actions/press_key instead of mouse when possible):"]
    for action, key in SHORTCUTS.items():
        lines.append(f"  {action:30s} → {key}")
    return "\n".join(lines)


def get_key_for(action: str) -> str | None:
    """Look up the key binding for a named action."""
    return SHORTCUTS.get(action)
