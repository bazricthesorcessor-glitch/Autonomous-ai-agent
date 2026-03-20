# ========================= core/voice.py =========================
"""
TTS voice output for Avril using edge-tts.

Voices:
  VOICE_NORMAL — en-IN-NeerjaNeural (warm Indian English, default)
  VOICE_HINDI  — hi-IN-SwaraNeural  (Hindi/Devanagari text)

Moods change prosody (rate + pitch):
  normal  — base voice
  sad     — slower, slightly lower pitch
  crying  — slowest, lowest pitch
  firm    — slightly faster, higher pitch (authority)

Usage:
  from core.voice import speak_and_play
  speak_and_play("Divyansh, uth jao!", mood="firm")
"""

import asyncio
import os
import tempfile
import threading

# ── Voice configuration ───────────────────────────────────────────────────────

VOICE_NORMAL = "en-IN-NeerjaNeural"   # warm Indian English — default
VOICE_HINDI  = "hi-IN-SwaraNeural"    # Hindi/Devanagari script

_RATE_MAP = {
    "normal":  "+0%",
    "sad":     "-15%",
    "crying":  "-22%",
    "firm":    "+8%",
}
_PITCH_MAP = {
    "normal":  "+0Hz",
    "sad":     "-8Hz",
    "crying":  "-14Hz",
    "firm":    "+4Hz",
}


# ── Detection helpers ─────────────────────────────────────────────────────────

def _is_primarily_hindi(text: str) -> bool:
    """Return True if >10% of characters are Devanagari script."""
    devnagari = sum(1 for c in text if '\u0900' <= c <= '\u097F')
    return devnagari > len(text) * 0.10


def _detect_voice(text: str) -> str:
    return VOICE_HINDI if _is_primarily_hindi(text) else VOICE_NORMAL


# ── Core async generation (edge-tts) ─────────────────────────────────────────

async def _generate_async(text: str, voice: str, output_path: str,
                           rate: str = "+0%", pitch: str = "+0Hz"):
    """Generate TTS audio and save to output_path."""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(output_path)


def _generate(text: str, voice: str, output_path: str,
              rate: str = "+0%", pitch: str = "+0Hz"):
    """Sync wrapper around the async generator."""
    asyncio.run(_generate_async(text, voice, output_path, rate=rate, pitch=pitch))


# ── Public API ────────────────────────────────────────────────────────────────

def speak(text: str, mood: str = "normal") -> str:
    """
    Generate TTS audio for the given text and mood.
    Returns the path to the generated MP3 file.
    Caller is responsible for cleanup.

    mood: "normal" | "sad" | "crying" | "firm"
    """
    if not text or not text.strip():
        return ""

    voice = _detect_voice(text)
    rate  = _RATE_MAP.get(mood, "+0%")
    pitch = _PITCH_MAP.get(mood, "+0Hz")

    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)

    try:
        _generate(text, voice, path, rate=rate, pitch=pitch)
        return path
    except Exception as e:
        print(f"[Voice] TTS generation failed: {e}")
        try:
            os.unlink(path)
        except Exception:
            pass
        return ""


def speak_and_play(text: str, mood: str = "normal"):
    """
    Generate TTS audio and immediately play it via mpv (non-blocking).
    The temp file is cleaned up after 60 seconds.

    Requires mpv to be installed: sudo pacman -S mpv
    """
    path = speak(text, mood=mood)
    if not path:
        return

    # Non-blocking playback via mpv
    import subprocess
    try:
        subprocess.Popen(
            ["mpv", "--really-quiet", "--no-video", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        # mpv not installed — try paplay/aplay as fallbacks
        for player in ("paplay", "aplay"):
            try:
                subprocess.Popen(
                    [player, path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                break
            except FileNotFoundError:
                continue
    except Exception as e:
        print(f"[Voice] Playback failed: {e}")

    # Cleanup after 60s (gives plenty of time for long sentences)
    def _cleanup():
        import time
        time.sleep(60)
        try:
            if os.path.exists(path):
                os.unlink(path)
        except Exception:
            pass

    threading.Thread(target=_cleanup, daemon=True).start()


def speak_and_play_sync(text: str, mood: str = "normal"):
    """
    Generate TTS audio and wait for playback to finish.
    Used when the caller needs to know when audio is done (e.g. shutdown sequence).
    """
    path = speak(text, mood=mood)
    if not path:
        return

    import subprocess
    try:
        subprocess.run(
            ["mpv", "--really-quiet", "--no-video", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"[Voice] Sync playback failed: {e}")
    finally:
        try:
            if os.path.exists(path):
                os.unlink(path)
        except Exception:
            pass
