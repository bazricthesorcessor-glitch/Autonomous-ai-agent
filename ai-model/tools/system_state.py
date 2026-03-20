# ========================= tools/system_state.py =========================
"""
Live system state aggregator.

Queries all available IPC sources in parallel and returns a single
SystemSnapshot dict. Zero screenshots, zero vision model calls.

Sources:
  caelestia shell mpris   — currently playing track, player, status
  hyprctl activewindow    — focused app + window title
  hyprctl clients -j      — all open windows + workspaces
  hyprctl monitors -j     — focused workspace
  pactl list sinks short  — audio sink state (RUNNING / IDLE)
  pactl list sink-inputs  — which app is producing audio

Everything is best-effort — if a source fails it just returns empty fields.
Never raises.
"""

import json
import re
import subprocess
import threading
import time as _time
from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MediaState:
    playing:        bool   = False
    player:         str    = ""    # "vlc", "firefox", "spotify", "mpv" …
    title:          str    = ""    # "Moon Princess"
    artist:         str    = ""    # "One Piece"
    album:          str    = ""
    status:         str    = ""    # "Playing" | "Paused" | "Stopped"
    position_sec:   float  = 0.0
    duration_sec:   float  = 0.0
    source:         str    = ""    # "caelestia" | "pactl" | "none"

    @property
    def display(self) -> str:
        if not self.playing:
            return "nothing playing"
        parts = [self.title] if self.title else []
        if self.artist:
            parts.append(f"by {self.artist}")
        if self.player:
            parts.append(f"[{self.player}]")
        return " ".join(parts) if parts else "unknown track"


@dataclass
class WindowState:
    focused_app:    str    = ""    # "firefox", "code", "kate" …
    focused_title:  str    = ""    # full window title
    focused_class:  str    = ""    # WM_CLASS e.g. "firefox"
    workspace:      int    = 0
    all_apps:       list   = field(default_factory=list)  # list of app class strings


@dataclass
class AudioSinkState:
    running:        bool   = False
    sink_name:      str    = ""
    sink_state:     str    = ""    # "RUNNING" | "IDLE" | "SUSPENDED"
    volume_pct:     int    = 0
    active_apps:    list   = field(default_factory=list)  # app names pushing audio


@dataclass
class SystemSnapshot:
    media:          MediaState      = field(default_factory=MediaState)
    window:         WindowState     = field(default_factory=WindowState)
    audio:          AudioSinkState  = field(default_factory=AudioSinkState)
    raw_errors:     list            = field(default_factory=list)

    @property
    def summary(self) -> str:
        """One-line human summary for the LLM context block."""
        parts = []

        # Active app
        if self.window.focused_app:
            title = self.window.focused_title
            app   = self.window.focused_class or self.window.focused_app
            parts.append(f"Focused: {app} — {title[:60]}" if title else f"Focused: {app}")

        # Media
        if self.media.playing:
            parts.append(f"Playing: {self.media.display} ({self.media.status})")
        elif self.audio.running:
            apps = ", ".join(self.audio.active_apps) if self.audio.active_apps else "unknown app"
            parts.append(f"Audio running ({apps}), no MPRIS track info")

        # All open apps (brief)
        if self.window.all_apps:
            unique = list(dict.fromkeys(self.window.all_apps))[:6]
            parts.append(f"Open apps: {', '.join(unique)}")

        return " | ".join(parts) if parts else "System state unknown"

    def to_context_block(self) -> str:
        """Multi-line block for LLM system prompt injection."""
        lines = ["[LIVE SYSTEM STATE]"]

        if self.window.focused_app:
            lines.append(f"Focused app : {self.window.focused_class or self.window.focused_app}")
            if self.window.focused_title:
                lines.append(f"Window title: {self.window.focused_title[:80]}")
            lines.append(f"Workspace   : {self.window.workspace}")

        if self.window.all_apps:
            unique = list(dict.fromkeys(self.window.all_apps))
            lines.append(f"Open apps   : {', '.join(unique[:8])}")

        if self.media.playing:
            lines.append(f"Now playing : {self.media.title or '?'}"
                         + (f" — {self.media.artist}" if self.media.artist else "")
                         + (f" [{self.media.player}]" if self.media.player else ""))
            lines.append(f"Media status: {self.media.status}")
            if self.media.duration_sec > 0:
                pos  = int(self.media.position_sec)
                dur  = int(self.media.duration_sec)
                pct  = int(pos / dur * 100)
                lines.append(f"Progress    : {pos//60}:{pos%60:02d} / {dur//60}:{dur%60:02d} ({pct}%)")
        elif self.audio.running:
            apps = ", ".join(self.audio.active_apps) if self.audio.active_apps else "?"
            lines.append(f"Audio       : RUNNING ({apps}) — no track metadata")
        else:
            lines.append("Audio       : silent")

        if self.audio.volume_pct:
            lines.append(f"Volume      : {self.audio.volume_pct}%")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Individual source queries
# ─────────────────────────────────────────────────────────────────────────────

def _query_caelestia_mpris() -> MediaState:
    """Query caelestia shell for MPRIS media info."""
    state = MediaState(source="caelestia")
    try:
        # Get active player first
        r = subprocess.run(
            ["caelestia", "shell", "mpris", "getActive", "player"],
            capture_output=True, text=True, timeout=3
        )
        player = r.stdout.strip()
        if not player or r.returncode != 0:
            return state

        def _get(prop: str) -> str:
            try:
                r2 = subprocess.run(
                    ["caelestia", "shell", "mpris", "getActive", prop],
                    capture_output=True, text=True, timeout=3
                )
                return r2.stdout.strip() if r2.returncode == 0 else ""
            except Exception:
                return ""

        status   = _get("playbackStatus")
        title    = _get("trackTitle")
        artist   = _get("trackArtist")
        album    = _get("trackAlbum")
        position = _get("position")
        length   = _get("trackLength")

        state.player = player
        state.status = status
        state.title  = title
        state.artist = artist
        state.album  = album
        state.playing = status.lower() == "playing"

        try:
            state.position_sec = float(position) / 1_000_000 if position else 0.0
        except Exception:
            pass
        try:
            state.duration_sec = float(length) / 1_000_000 if length else 0.0
        except Exception:
            pass

    except FileNotFoundError:
        state.source = "none"  # caelestia not installed
    except Exception:
        state.source = "none"

    return state


def _query_hyprctl_window() -> WindowState:
    """Query hyprctl for active window and all clients."""
    state = WindowState()
    try:
        # Active window
        r = subprocess.run(
            ["hyprctl", "activewindow", "-j"],
            capture_output=True, text=True, timeout=3
        )
        if r.returncode == 0 and r.stdout.strip():
            win = json.loads(r.stdout)
            state.focused_app   = win.get("class", "")
            state.focused_class = win.get("class", "")
            state.focused_title = win.get("title", "")
            state.workspace     = win.get("workspace", {}).get("id", 0)

        # All clients
        r2 = subprocess.run(
            ["hyprctl", "clients", "-j"],
            capture_output=True, text=True, timeout=3
        )
        if r2.returncode == 0 and r2.stdout.strip():
            clients = json.loads(r2.stdout)
            state.all_apps = [
                c.get("class", "").lower()
                for c in clients
                if c.get("class")
            ]

    except Exception:
        pass
    return state


def _query_pactl() -> AudioSinkState:
    """Query pactl for sink state and active audio streams."""
    state = AudioSinkState()
    try:
        # Sink state
        r = subprocess.run(
            ["pactl", "list", "sinks", "short"],
            capture_output=True, text=True, timeout=4
        )
        for line in r.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 5:
                state.sink_name  = parts[1]
                state.sink_state = parts[-1].upper()
                state.running    = state.sink_state == "RUNNING"
                break

        # Volume
        r2 = subprocess.run(
            ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
            capture_output=True, text=True, timeout=3
        )
        m = re.search(r'(\d+)%', r2.stdout)
        if m:
            state.volume_pct = int(m.group(1))

        # Active app streams
        r3 = subprocess.run(
            ["pactl", "list", "sink-inputs"],
            capture_output=True, text=True, timeout=4
        )
        apps = re.findall(
            r'application\.name\s*=\s*"([^"]+)"',
            r3.stdout, re.IGNORECASE
        )
        state.active_apps = list(dict.fromkeys(apps))  # deduplicated

    except Exception:
        pass
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Main aggregator
# ─────────────────────────────────────────────────────────────────────────────

_snapshot_cache: "SystemSnapshot | None" = None
_snapshot_cache_time: float = 0.0
_SNAPSHOT_TTL: float = 5.0   # seconds — one agent turn is well under this
_snapshot_lock = threading.Lock()


def get_snapshot(force: bool = False) -> "SystemSnapshot":
    """
    Gather all system state in parallel, cached for _SNAPSHOT_TTL seconds.
    Pass force=True to bypass cache (e.g. explicit system_state tool call).
    Returns a SystemSnapshot. Never raises.
    """
    global _snapshot_cache, _snapshot_cache_time

    now = _time.monotonic()

    if not force and _snapshot_cache is not None:
        with _snapshot_lock:
            if now - _snapshot_cache_time < _SNAPSHOT_TTL:
                return _snapshot_cache

    snap   = SystemSnapshot()
    errors = []

    media_result  = [None]
    window_result = [None]
    audio_result  = [None]

    def _do_media():
        try:
            media_result[0] = _query_caelestia_mpris()
        except Exception as e:
            errors.append(f"media: {e}")

    def _do_window():
        try:
            window_result[0] = _query_hyprctl_window()
        except Exception as e:
            errors.append(f"window: {e}")

    def _do_audio():
        try:
            audio_result[0] = _query_pactl()
        except Exception as e:
            errors.append(f"audio: {e}")

    threads = [
        threading.Thread(target=_do_media,  daemon=True),
        threading.Thread(target=_do_window, daemon=True),
        threading.Thread(target=_do_audio,  daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=4)

    snap.media      = media_result[0]  or MediaState()
    snap.window     = window_result[0] or WindowState()
    snap.audio      = audio_result[0]  or AudioSinkState()
    snap.raw_errors = errors

    if not snap.media.playing and snap.audio.running:
        snap.media.source = "pactl_only"
        snap.media.player = ", ".join(snap.audio.active_apps) if snap.audio.active_apps else ""

    with _snapshot_lock:
        _snapshot_cache      = snap
        _snapshot_cache_time = _time.monotonic()

    return snap


# ─────────────────────────────────────────────────────────────────────────────
# Tool interface (so the agent can call it directly)
# ─────────────────────────────────────────────────────────────────────────────

def run_tool(args: dict = None) -> str:
    """
    Agent-callable tool.

    Actions:
      {"action": "snapshot"}        — full system state as formatted block
      {"action": "media"}           — media only (title, artist, status)
      {"action": "window"}          — focused window + open apps
      {"action": "audio"}           — audio sink state
    """
    if args is None:
        args = {}
    action = str(args.get("action", "snapshot")).lower()

    snap = get_snapshot(force=True)

    if action == "media":
        m = snap.media
        if m.playing:
            return (
                f"Playing: {m.title or '?'}"
                + (f" by {m.artist}" if m.artist else "")
                + (f" [{m.player}]" if m.player else "")
                + f" — {m.status}"
            )
        elif snap.audio.running:
            return f"Audio RUNNING ({', '.join(snap.audio.active_apps) or '?'}) but no track metadata"
        return "Nothing playing."

    if action == "window":
        w = snap.window
        lines = []
        if w.focused_class:
            lines.append(f"Focused: {w.focused_class} — {w.focused_title[:60]}")
        if w.all_apps:
            lines.append(f"Open: {', '.join(dict.fromkeys(w.all_apps))}")
        return "\n".join(lines) or "No window info."

    if action == "audio":
        a = snap.audio
        if a.running:
            return f"Audio RUNNING via {', '.join(a.active_apps) or '?'} at {a.volume_pct}%"
        return f"Audio {a.sink_state} (volume: {a.volume_pct}%)"

    # Default: full snapshot block
    return snap.to_context_block()
