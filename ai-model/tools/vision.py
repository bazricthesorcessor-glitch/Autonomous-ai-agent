# ========================= tools/vision.py =========================
"""
Vision tool — structured perception for GUI automation via MAI-UI.

Actions:
  locate         — find an element, return coordinates
  act            — let MAI-UI decide what action to take
  page_state     — check LOADING / READY (OCR heuristic)
  wait_ready     — block until page looks READY
  monitor_response — wait until text output stops changing
  read_screen    — OCR the current screen
  list_elements  — ask MAI-UI to list interactive elements
  verify_task    — verify a task completed (hash+audio+vision)
                   {"action": "verify_task", "task": "play venom on youtube", "video": true}
"""

import hashlib
import os
import re
import time
import json
import subprocess
import base64
import threading

import config

_VISION_SCREENSHOT = os.path.join(config.SCREENSHOT_DIR, "_vision_locate.png")
_VERIFY_SHOT_1     = os.path.join(config.SCREENSHOT_DIR, "_verify_1.png")

_CONFIDENCE_THRESHOLD = 0.70
_MAX_VERIFY_RETRIES   = 2


# ── Screen capture helpers ────────────────────────────────────────────────────

def _capture_screen() -> bool:
    try:
        subprocess.run(["grim", _VISION_SCREENSHOT],
                       check=True, capture_output=True, timeout=8)
        return True
    except Exception:
        return False

def _load_screenshot_b64() -> str | None:
    try:
        with open(_VISION_SCREENSHOT, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return None

def _b64(path: str) -> str | None:
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return None

def _take_hash() -> str:
    """Capture a verify screenshot and return MD5 of the PNG bytes."""
    try:
        subprocess.run(["grim", _VERIFY_SHOT_1],
                       check=True, capture_output=True, timeout=8)
        with open(_VERIFY_SHOT_1, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return ""


# ── MAI-UI helpers ────────────────────────────────────────────────────────────

def _mai_ui_locate(query: str) -> dict | None:
    if not _capture_screen():
        return None
    img_b64 = _load_screenshot_b64()
    if not img_b64:
        return None
    try:
        from ollama import Client
        client = Client(host='http://localhost:11434')
        prompt = (
            f"Screen resolution is 1920x1200. "
            f"I want to: {query}. "
            f"Look at the screenshot and give me the exact pixel coordinates (x,y) "
            f"of the element I should interact with. "
            f"Reply with ONLY the coordinates in 'x,y' format, e.g. '854,312'. "
            f"If the element is not visible, reply 'NOT_FOUND'."
        )
        response = client.chat(
            model=config.VISION_MODEL,
            messages=[{"role": "user", "content": prompt, "images": [img_b64]}],
            options={"temperature": 0.0, "num_predict": 30},
        )
        raw = response["message"]["content"].strip()
        if "NOT_FOUND" in raw.upper():
            return None
        coord_match = re.search(r'(\d{2,4})\s*[,x]\s*(\d{2,4})', raw)
        if coord_match:
            x, y = int(coord_match.group(1)), int(coord_match.group(2))
            if x > 0 and y > 0:
                return {"x": x, "y": y, "text": query, "layer": "mai_ui"}
    except Exception as e:
        print(f"[Vision] MAI-UI locate failed: {e}")
    return None

def _mai_ui_act(task: str) -> dict | None:
    if not _capture_screen():
        return None
    img_b64 = _load_screenshot_b64()
    if not img_b64:
        return None
    try:
        from ollama import Client
        client = Client(host='http://localhost:11434')
        prompt = (
            f"Screen resolution is 1920x1200. Task: {task}\n"
            f"Look at the screenshot. What is the single best next action?\n"
            f"Reply ONLY with a JSON object (no markdown):\n"
            f'  {{"action": "click", "x": 854, "y": 312}}\n'
            f'  {{"action": "type", "text": "hello"}}\n'
            f'  {{"action": "scroll", "direction": "down", "amount": 3}}\n'
            f'  {{"action": "press", "key": "Return"}}\n'
            f'  {{"action": "ask_user", "question": "..."}}\n'
            f'  {{"action": "done"}}\n'
        )
        response = client.chat(
            model=config.VISION_MODEL,
            messages=[{"role": "user", "content": prompt, "images": [img_b64]}],
            options={"temperature": 0.0, "num_predict": 80},
        )
        raw = re.sub(r"```json\s*|```", "", response["message"]["content"].strip()).strip()
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "action" in parsed:
            return parsed
    except Exception as e:
        print(f"[Vision] MAI-UI act failed: {e}")
    return None

def _mai_ui_list_elements() -> str:
    if not _capture_screen():
        return "[Vision] Screenshot failed."
    img_b64 = _load_screenshot_b64()
    if not img_b64:
        return "[Vision] Could not load screenshot."
    try:
        from ollama import Client
        client = Client(host='http://localhost:11434')
        response = client.chat(
            model=config.VISION_MODEL,
            messages=[{"role": "user", "content":
                "List all interactive UI elements visible on this screen. "
                "For each: element type, label/text, approximate position (x,y). "
                "Format: [button] 'Sign In' at (960, 400)",
                "images": [img_b64]}],
            options={"temperature": 0.0, "num_predict": 400},
        )
        return response["message"]["content"].strip()
    except Exception as e:
        return f"[Vision] List elements failed: {e}"


# ── OCR + page state ──────────────────────────────────────────────────────────

def _ocr_screen() -> str:
    try:
        if not _capture_screen():
            return "[Vision] Screenshot failed."
        result = subprocess.run(
            ["tesseract", _VISION_SCREENSHOT, "stdout", "--psm", "3"],
            capture_output=True, text=True, timeout=30,
        )
        text = result.stdout.strip()
        return text[:3000] if text else "[Vision] No text detected on screen."
    except Exception as e:
        return f"[Vision] OCR failed: {e}"

def _page_state_ocr() -> str:
    text = _ocr_screen().lower()
    if any(w in text for w in ["loading", "please wait", "connecting"]):
        return "LOADING"
    if any(w in text for w in ["error", "404", "not found", "failed"]):
        return "ERROR"
    if text and len(text) > 50:
        return "READY"
    return "UNKNOWN"

def _wait_ready_poll(timeout: float = 10.0, interval: float = 1.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = _page_state_ocr()
        if state in ("READY", "ERROR"):
            return state
        time.sleep(interval)
    return "TIMEOUT"

def _monitor_response_poll(timeout: float = 18.0, interval: float = 2.0,
                            stable_polls: int = 2) -> str:
    prev_text = ""
    stable_count = 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = _ocr_screen()
        if current == prev_text:
            stable_count += 1
            if stable_count >= stable_polls:
                return f"STABLE (output stopped changing after {stable_count} polls)"
        else:
            stable_count = 0
        prev_text = current
        time.sleep(interval)
    return "TIMEOUT (output may still be streaming)"


# ── Audio check ───────────────────────────────────────────────────────────────

def _audio_check() -> dict:
    """Uses caelestia MPRIS first, falls back to pactl."""
    try:
        from tools.system_state import get_snapshot
        snap = get_snapshot()
        if snap.media.playing:
            return {
                "playing": True,
                "sink":    snap.audio.sink_name,
                "state":   "RUNNING",
                "app":     snap.media.player,
                "volume":  str(snap.audio.volume_pct) + "%",
                "detail":  f"Audio RUNNING — {snap.media.display} via {snap.media.player}",
                "title":   snap.media.title,
                "artist":  snap.media.artist,
                "status":  snap.media.status,
            }
        if snap.audio.running:
            apps = ", ".join(snap.audio.active_apps) if snap.audio.active_apps else "?"
            return {
                "playing": True,
                "sink":    snap.audio.sink_name,
                "state":   "RUNNING",
                "app":     apps,
                "volume":  str(snap.audio.volume_pct) + "%",
                "detail":  f"Audio RUNNING ({apps}) at {snap.audio.volume_pct}%",
                "title":   "", "artist":  "", "status":  "Playing",
            }
        return {
            "playing": False,
            "sink":    snap.audio.sink_name,
            "state":   snap.audio.sink_state or "IDLE",
            "app":     "",
            "volume":  str(snap.audio.volume_pct) + "%",
            "detail":  f"Audio {snap.audio.sink_state} (volume: {snap.audio.volume_pct}%)",
            "title":   "", "artist":  "", "status":  "Stopped",
        }
    except Exception as e:
        result = {"playing": False, "sink": "", "state": "UNKNOWN",
                  "app": "", "volume": "", "detail": f"audio check failed: {e}",
                  "title": "", "artist": "", "status": ""}
        try:
            r = subprocess.run(["pactl", "list", "sinks", "short"],
                               capture_output=True, text=True, timeout=4)
            for line in r.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 5:
                    result["state"]   = parts[-1].upper()
                    result["playing"] = result["state"] == "RUNNING"
                    result["detail"]  = f"Audio {result['state']} (pactl fallback)"
                    break
        except Exception:
            pass
        return result


# ── Verify: scene description ─────────────────────────────────────────────────

def _vision_describe_scene(frames: list[str], task_description: str) -> dict:
    """Send 1–3 frames to MAI-UI, get activity list with confidences."""
    try:
        from ollama import Client
        client = Client(host='http://localhost:11434')
    except Exception as e:
        return {"activities": [], "raw": str(e), "parse_ok": False}

    n = len(frames)
    frame_note = (
        f"I am sending {n} screenshot{'s' if n > 1 else ''} "
        + ("taken 2 seconds apart. Look for changes between frames to detect motion/video. "
           if n > 1 else ". ")
    )
    prompt = (
        f"{frame_note}Task that was just attempted: {task_description}\n\n"
        "Describe what is currently happening on screen. "
        "For each activity you detect, give a confidence from 0.0 to 1.0.\n\n"
        "Reply with ONLY a JSON array:\n"
        "[\n"
        "  {\"label\": \"video_playing\", \"confidence\": 0.95},\n"
        "  {\"label\": \"coding\",        \"confidence\": 0.05}\n"
        "]\n\n"
        "Use ONLY these labels: "
        "video_playing, audio_playing, coding, browsing, chess, idle, "
        "error, task_done, task_failed, unknown\n"
        "Include ALL that apply. Omit labels with confidence < 0.05."
    )
    raw = ""
    try:
        response = client.chat(
            model=config.VISION_MODEL,
            messages=[{"role": "user", "content": prompt, "images": frames}],
            options={"temperature": 0.0, "num_predict": 200},
        )
        raw       = response["message"]["content"].strip()
        raw_clean = re.sub(r"```json\s*|```", "", raw).strip()
        start = raw_clean.find("[")
        end   = raw_clean.rfind("]")
        if start != -1 and end != -1:
            activities = json.loads(raw_clean[start:end + 1])
            cleaned = [
                {"label": str(a["label"]).lower().strip(),
                 "confidence": max(0.0, min(1.0, float(a["confidence"])))}
                for a in activities
                if isinstance(a, dict) and "label" in a and "confidence" in a
            ]
            return {"activities": cleaned, "raw": raw, "parse_ok": True}
    except Exception as e:
        print(f"[Verify] Vision scene parse failed: {e} | raw: {raw[:200]}")
    return {"activities": [], "raw": raw, "parse_ok": False}


def _interpret_scene(vision: dict, audio: dict, task_description: str) -> dict:
    """Combine vision activity list + audio into a scene descriptor."""
    acts = {a["label"]: a["confidence"] for a in vision.get("activities", [])}

    audio_playing = audio.get("playing", False)
    audio_detail  = audio.get("detail",  "")
    audio_app     = audio.get("app",     "")
    audio_title   = audio.get("title",   "")
    audio_artist  = audio.get("artist",  "")
    audio_conf    = 0.95 if audio_playing else 0.0

    scene_parts = []
    confidences  = []

    vid_conf = acts.get("video_playing", 0.0)

    if audio_playing and vid_conf >= 0.5:
        scene_parts.append("video")
        confidences.append(min(0.99, (vid_conf + audio_conf) / 2 + 0.15))
    elif audio_playing and vid_conf < 0.3:
        if audio_title:
            track = audio_title + (f" by {audio_artist}" if audio_artist else "")
            scene_parts.append(f"music ({track})")
        else:
            scene_parts.append(f"music/audio ({audio_app})" if audio_app else "music/audio")
        confidences.append(min(0.95, audio_conf * 0.9))
    elif audio_playing and 0.3 <= vid_conf < 0.5:
        scene_parts.append("possible video/audio")
        confidences.append(0.5)
    elif not audio_playing and vid_conf >= 0.6:
        scene_parts.append("video (muted or unfocused)")
        confidences.append(vid_conf * 0.8)

    code_conf = acts.get("coding", 0.0)
    if code_conf >= 0.4:
        scene_parts.append("coding")
        confidences.append(code_conf)

    browse_conf = acts.get("browsing", 0.0)
    if browse_conf >= 0.4 and "video" not in " ".join(scene_parts):
        scene_parts.append("browsing")
        confidences.append(browse_conf)

    chess_conf = acts.get("chess", 0.0)
    if chess_conf >= 0.4:
        scene_parts.append("chess")
        confidences.append(chess_conf)

    err_conf = acts.get("error", 0.0)
    if err_conf >= 0.5:
        scene_parts.append("ERROR on screen")
        confidences.append(err_conf)

    done_conf   = acts.get("task_done",   0.0)
    failed_conf = acts.get("task_failed", 0.0)

    idle_conf = acts.get("idle", 0.0)
    if not scene_parts and idle_conf >= 0.4:
        scene_parts.append("idle")
        confidences.append(idle_conf)

    if not scene_parts and not audio_playing:
        scene_parts.append("unknown")
        confidences.append(0.1)

    overall_conf = max(confidences) if confidences else 0.1
    if not vision.get("parse_ok") and not audio_playing:
        overall_conf = 0.1

    task_lower    = task_description.lower()
    is_video_task = any(w in task_lower for w in ("play", "watch", "video", "youtube", "vlc", "episode", "stream"))
    is_music_task = any(w in task_lower for w in ("music", "song", "playlist", "spotify", "lofi"))
    is_code_task  = any(w in task_lower for w in ("code", "script", "write", "open vscode", "terminal"))

    if done_conf >= 0.7:
        task_done = True
    elif failed_conf >= 0.6:
        task_done = False
    elif is_video_task:
        task_done = "video" in " ".join(scene_parts) or "music" in " ".join(scene_parts)
    elif is_music_task:
        task_done = audio_playing
    elif is_code_task:
        task_done = "coding" in scene_parts
    else:
        task_done = bool(scene_parts) and "idle" not in scene_parts and "ERROR" not in " ".join(scene_parts)

    scene_str = " + ".join(scene_parts) if scene_parts else "unknown"
    return {
        "done":           task_done,
        "scene":          scene_str,
        "confidence":     round(overall_conf, 3),
        "detail":         f"{scene_str}, confidence {overall_conf:.2f}\nAudio: {audio_detail}\nVision: {vision.get('activities', [])}",
        "method":         "audio+vision" if audio_playing else ("vision_only" if vision.get("parse_ok") else "audio_only"),
        "activities":     vision.get("activities", []),
        "low_confidence": overall_conf < _CONFIDENCE_THRESHOLD,
    }


def _title_check_fallback(task_description: str) -> dict:
    try:
        r = subprocess.run(["hyprctl", "clients", "-j"],
                           capture_output=True, text=True, timeout=3)
        clients = json.loads(r.stdout)
        for c in clients:
            cls   = c.get("class", "").lower()
            title = c.get("title", "").lower()
            if any(p in cls for p in ("vlc", "mpv", "celluloid", "totem")):
                if title.strip() not in {"vlc media player", "mpv", ""}:
                    return {"done": True, "scene": "video", "confidence": 0.75,
                            "detail": f"title_check: {c.get('title', '')}",
                            "method": "title_check", "activities": [], "low_confidence": False}
    except Exception:
        pass
    return {"done": False, "scene": "unknown", "confidence": 0.1,
            "detail": "title_check: no active media player",
            "method": "title_check", "activities": [], "low_confidence": True}


# ── Main verify function ──────────────────────────────────────────────────────

def verify_task_done(task_description: str, is_video: bool = False,
                     _retry_count: int = 0) -> dict:
    """
    Verify task completion.

    VIDEO:  hash1 → 2s → hash2
      changed + audio → "video" 0.95  (no MAI-UI)
      changed, no audio → 1 frame MAI-UI + 0.15 boost
      unchanged + audio → "music/audio" 0.90  (no MAI-UI)
      unchanged, no audio → 1 frame MAI-UI diagnose

    NON-VIDEO:  1 frame MAI-UI + screen-change +0.15 boost

    Retries up to 2x if confidence < 0.70.
    """
    audio_result = {}

    def _do_audio():
        audio_result.update(_audio_check())

    audio_thread = threading.Thread(target=_do_audio, daemon=True)
    audio_thread.start()

    if is_video:
        h1 = _take_hash()
        time.sleep(2)
        h2 = _take_hash()
        audio_thread.join(timeout=4)

        audio_playing  = audio_result.get("playing", False)
        audio_detail   = audio_result.get("detail",  "")
        audio_app      = audio_result.get("app",     "")
        screen_changed = bool(h1 and h2 and h1 != h2)

        if screen_changed and audio_playing:
            return {"done": True, "scene": "video", "confidence": 0.95,
                    "detail": f"Screen changed + audio running ({audio_app or audio_detail})",
                    "method": "hash+audio", "activities": [], "low_confidence": False}

        if screen_changed and not audio_playing:
            f1 = _b64(_VERIFY_SHOT_1)
            if f1:
                vision_result = _vision_describe_scene([f1], task_description)
                result = _interpret_scene(vision_result, audio_result, task_description)
                result["confidence"]     = min(0.90, result["confidence"] + 0.15)
                result["detail"]         = f"[screen changed, audio silent] {result['detail']}"
                result["low_confidence"] = result["confidence"] < _CONFIDENCE_THRESHOLD
                return result
            return _title_check_fallback(task_description)

        if not screen_changed and audio_playing:
            title  = audio_result.get("title", "")
            artist = audio_result.get("artist", "")
            scene  = (f"music ({title}" + (f" by {artist}" if artist else "") + ")"
                      if title else
                      (f"music/audio ({audio_app})" if audio_app else "music/audio"))
            return {"done": True, "scene": scene, "confidence": 0.90,
                    "detail": f"Screen unchanged, {audio_detail}",
                    "method": "audio_only", "activities": [], "low_confidence": False}

        f1 = _b64(_VERIFY_SHOT_1)
        if not f1:
            return _title_check_fallback(task_description)
        vision_result = _vision_describe_scene([f1], task_description)
        result = _interpret_scene(vision_result, audio_result, task_description)
        if result["low_confidence"] and _retry_count < _MAX_VERIFY_RETRIES:
            print(f"[Verify] Low confidence ({result['confidence']:.2f}), retrying ({_retry_count+1}/{_MAX_VERIFY_RETRIES})...")
            time.sleep(2)
            return verify_task_done(task_description, is_video=True, _retry_count=_retry_count + 1)
        return result

    else:
        try:
            pre_hash = config.safe_load_json(config.SCREEN_CACHE_FILE, {}).get("screen_hash", "")
        except Exception:
            pre_hash = ""

        h_now = _take_hash()
        audio_thread.join(timeout=4)
        screen_changed = bool(pre_hash and h_now and pre_hash != h_now)

        f1 = _b64(_VERIFY_SHOT_1)
        if not f1:
            if audio_result.get("playing"):
                return {"done": True, "scene": f"audio ({audio_result.get('app', '')})",
                        "confidence": 0.70, "detail": audio_result.get("detail", ""),
                        "method": "audio_only", "activities": [], "low_confidence": False}
            return {"done": False, "scene": "unknown", "confidence": 0.1,
                    "detail": "screenshot failed", "method": "none",
                    "activities": [], "low_confidence": True}

        vision_result = _vision_describe_scene([f1], task_description)
        result = _interpret_scene(vision_result, audio_result, task_description)

        if screen_changed and result["confidence"] < 0.85:
            result["confidence"]     = min(0.85, result["confidence"] + 0.15)
            result["detail"]         = f"[screen changed] {result['detail']}"
            result["low_confidence"] = result["confidence"] < _CONFIDENCE_THRESHOLD

        if result["low_confidence"] and _retry_count < _MAX_VERIFY_RETRIES:
            print(f"[Verify] Low confidence ({result['confidence']:.2f}), retrying ({_retry_count+1}/{_MAX_VERIFY_RETRIES})...")
            time.sleep(2)
            return verify_task_done(task_description, is_video=False, _retry_count=_retry_count + 1)
        return result


# ── Public dispatcher ─────────────────────────────────────────────────────────

def run_tool(args: dict = None) -> str:
    if args is None:
        args = {}

    action = str(args.get("action", "")).strip().lower()
    query  = str(args.get("query",  "")).strip()
    task   = str(args.get("task",   "")).strip()

    if action == "locate":
        if not query:
            return "[Vision] 'query' is required for locate."
        result = _mai_ui_locate(query)
        if result:
            return json.dumps({"state": "FOUND", "layer": "mai_ui",
                               "coordinates": [result["x"], result["y"]],
                               "text": result.get("text", "")})
        return json.dumps({"state": "NOT_FOUND", "query": query})

    if action == "act":
        if not task:
            return "[Vision] 'task' is required for act."
        result = _mai_ui_act(task)
        if result:
            return json.dumps(result)
        return json.dumps({"action": "error", "message": "MAI-UI could not determine action"})

    if action == "page_state":
        return _page_state_ocr()

    if action == "wait_ready":
        return _wait_ready_poll(
            timeout  = float(args.get("timeout",  config.PERCEPTION_TIMEOUT)),
            interval = float(args.get("interval", config.PERCEPTION_POLL_INTERVAL)),
        )

    if action == "monitor_response":
        return _monitor_response_poll(
            timeout      = float(args.get("timeout",      config.MONITOR_RESPONSE_TIMEOUT)),
            interval     = float(args.get("interval",     config.PERCEPTION_POLL_INTERVAL)),
            stable_polls = int(args.get("stable_polls",   config.RESPONSE_STABLE_POLLS)),
        )

    if action == "list_elements":
        return _mai_ui_list_elements()

    if action == "read_screen":
        return _ocr_screen()

    if action == "verify_task":
        if not task:
            return "[Vision] 'task' is required for verify_task."
        is_video = bool(args.get("video", False))
        return json.dumps(verify_task_done(task, is_video))

    return (
        f"[Vision] Unknown action '{action}'. "
        "Available: locate, act, page_state, wait_ready, monitor_response, "
        "list_elements, read_screen, verify_task"
    )