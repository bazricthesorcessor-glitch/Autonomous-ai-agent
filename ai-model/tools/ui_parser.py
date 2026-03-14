# ========================= tools/ui_parser.py =========================
"""
UI Parser — YOLO-based GUI element detection + targeted OCR.

Replaces the OCR-only screen_map pipeline with a detection-first
approach: a YOLO model locates UI components (buttons, inputs, icons,
menus, cards, lists), then tesseract runs OCR *only on detected boxes*
for text recognition.

Pipeline:
  1. grim fullscreen capture
  2. YOLO UI detection model → bounding boxes + class labels
  3. tesseract OCR on each detected box → text content
  4. merge into structured element list
  5. cache to screen_map.json

Fallback: if no YOLO model is available, delegates to the existing
screen_map.scan() OCR-only pipeline so nothing breaks.

Model setup:
  Place a YOLOv8 .pt model trained on UI elements at the path
  configured in config.UI_MODEL_PATH (default: ai-model/models/ui_detect.pt).
  Or set the path in config/system_config.json under "ui_model_path".

  Supported classes (configurable via _CLASS_MAP):
    button, input, icon, menu, card, list, checkbox, radio,
    dropdown, toggle, link, image, text, header, nav, search_bar

Usage:
  from tools import ui_parser
  elements = ui_parser.parse_screen()
  el = ui_parser.find_element("Search")
  # el = {"type":"input", "text":"Search", "x":500, "y":110, "w":250, ...}
"""

import os
import subprocess
import json
import time

import config

# ── Paths ─────────────────────────────────────────────────────────────────────

_SCREENSHOT_PATH = os.path.join(config.SCREENSHOT_DIR, "_ui_parse.png")
_MAP_CACHE = os.path.join(config.SCREENSHOT_DIR, "screen_map.json")

# Screen resolution — coordinates are in these native pixels.
# Updated automatically on first capture; set defaults for 1920x1200.
SCREEN_W = 1920
SCREEN_H = 1200

# Model path: check config, fallback to default location
_DEFAULT_MODEL_PATH = os.path.join(config.BASE_DIR, "models", "ui_detect.pt")
UI_MODEL_PATH = getattr(config, 'UI_MODEL_PATH', _DEFAULT_MODEL_PATH)

# ── YOLO model (lazy-loaded) ─────────────────────────────────────────────────

_model = None
_model_loaded = False  # distinguishes "not tried" from "tried and failed"


def _load_model():
    """Lazily load the YOLO model. Returns the model or None."""
    global _model, _model_loaded
    if _model_loaded:
        return _model

    _model_loaded = True

    if not os.path.isfile(UI_MODEL_PATH):
        print(f"[ui_parser] No UI model at {UI_MODEL_PATH} — using OCR fallback")
        return None

    try:
        from ultralytics import YOLO
        _model = YOLO(UI_MODEL_PATH)
        # Warm up with a tiny dummy inference to load weights
        import numpy as np
        _dummy = np.zeros((64, 64, 3), dtype=np.uint8)
        _model.predict(_dummy, verbose=False)
        print(f"[ui_parser] YOLO model loaded: {UI_MODEL_PATH}")
    except ImportError:
        print("[ui_parser] ultralytics not installed — pip install ultralytics")
        _model = None
    except Exception as e:
        print(f"[ui_parser] Failed to load model: {e}")
        _model = None

    return _model


def is_model_available() -> bool:
    """Check if a YOLO model is loaded and ready."""
    return _load_model() is not None


# ── Class label mapping ──────────────────────────────────────────────────────
# Maps YOLO class IDs to semantic type names.
# This needs to match whatever classes the model was trained on.
# Override by placing a class_map.json next to the model file.

_DEFAULT_CLASS_MAP = {
    0: "button",
    1: "input",
    2: "icon",
    3: "menu",
    4: "card",
    5: "list",
    6: "checkbox",
    7: "radio",
    8: "dropdown",
    9: "toggle",
    10: "link",
    11: "image",
    12: "text",
    13: "header",
    14: "nav",
    15: "search_bar",
}

_class_map = None


def _get_class_map() -> dict:
    """Load class map, checking for a custom mapping file first."""
    global _class_map
    if _class_map is not None:
        return _class_map

    custom_path = os.path.join(os.path.dirname(UI_MODEL_PATH), "class_map.json")
    if os.path.isfile(custom_path):
        try:
            with open(custom_path, 'r') as f:
                raw = json.load(f)
            # Convert string keys to int if needed
            _class_map = {int(k): v for k, v in raw.items()}
            return _class_map
        except Exception:
            pass

    _class_map = _DEFAULT_CLASS_MAP
    return _class_map


# ── Screenshot capture ────────────────────────────────────────────────────────

def _capture(path: str = None) -> bool:
    """Capture fullscreen via grim. Updates SCREEN_W/H from the image."""
    global SCREEN_W, SCREEN_H
    if path is None:
        path = _SCREENSHOT_PATH
    try:
        subprocess.run(["grim", path], check=True, capture_output=True, timeout=8)
        # Read actual resolution from the captured image
        try:
            from PIL import Image
            with Image.open(path) as img:
                SCREEN_W, SCREEN_H = img.size
        except Exception:
            pass  # keep defaults
        return True
    except Exception:
        return False


# ── OCR on a cropped region ──────────────────────────────────────────────────

def _ocr_region(img_array, x: int, y: int, w: int, h: int) -> str:
    """Run tesseract on a cropped region of the image. Returns text string."""
    try:
        from PIL import Image
        import io

        # Crop the region (img_array is a numpy array from cv2/PIL)
        cropped = img_array[y:y+h, x:x+w]

        # Convert numpy array to PNG bytes for tesseract stdin
        pil_img = Image.fromarray(cropped)
        buf = io.BytesIO()
        pil_img.save(buf, format='PNG')
        png_bytes = buf.getvalue()

        # Run tesseract on stdin
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "--psm", "7", "-l", "eng"],
            input=png_bytes, capture_output=True, timeout=5
        )
        text = result.stdout.decode('utf-8', errors='replace').strip()
        # Clean control characters
        text = ''.join(c for c in text if c.isprintable() or c in '\n\t')
        return text.strip()
    except Exception:
        return ""


def _ocr_fullscreen_tsv(png_path: str) -> str:
    """Fallback: full-page tesseract TSV for when YOLO isn't available."""
    try:
        r = subprocess.run(
            ["tesseract", png_path, "stdout", "--psm", "3", "tsv"],
            capture_output=True, text=True, check=True, timeout=30
        )
        return r.stdout
    except Exception:
        return ""


# ── YOLO detection ────────────────────────────────────────────────────────────

def _detect(img_path: str, confidence: float = 0.25) -> list[dict]:
    """Run YOLO detection on an image. Returns list of raw detections.

    Each detection: {class_id, class_name, confidence, x, y, w, h}
    """
    model = _load_model()
    if model is None:
        return []

    class_map = _get_class_map()

    try:
        results = model.predict(
            img_path,
            conf=confidence,
            verbose=False,
            device='cpu',   # safe default; change to 0 for GPU
        )
    except Exception as e:
        print(f"[ui_parser] Detection error: {e}")
        return []

    detections = []
    for result in results:
        boxes = result.boxes
        if boxes is None:
            continue
        for i in range(len(boxes)):
            xyxy = boxes.xyxy[i].cpu().numpy()
            cls_id = int(boxes.cls[i].cpu().numpy())
            conf = float(boxes.conf[i].cpu().numpy())

            x1, y1, x2, y2 = int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3])
            detections.append({
                "class_id": cls_id,
                "class_name": class_map.get(cls_id, f"class_{cls_id}"),
                "confidence": round(conf, 3),
                "x": x1,
                "y": y1,
                "w": x2 - x1,
                "h": y2 - y1,
            })

    return detections


# ── Full parse pipeline ──────────────────────────────────────────────────────

def parse_screen(
    min_x: int = 0, max_x: int = 99999,
    min_y: int = 0, max_y: int = 99999,
    confidence: float = 0.25,
) -> list[dict]:
    """Full pipeline: capture → detect → OCR → merge → cache.

    Returns structured element list:
      [{"type":"button", "text":"Submit", "x":100, "y":200, "w":80, "h":30,
        "cx":140, "cy":215, "conf":0.92}, ...]

    If YOLO model is not available, falls back to OCR-only pipeline
    (screen_map.scan).
    """
    # Capture screenshot
    if not _capture(_SCREENSHOT_PATH):
        return []

    model = _load_model()

    if model is None:
        # Fallback to OCR-only pipeline
        from tools import screen_map
        return screen_map.scan(min_x, max_x, min_y, max_y)

    # Run YOLO detection
    detections = _detect(_SCREENSHOT_PATH, confidence)

    if not detections:
        # No detections — fall back to OCR-only
        from tools import screen_map
        return screen_map.scan(min_x, max_x, min_y, max_y)

    # Load image for cropped OCR
    try:
        import numpy as np
        from PIL import Image
        img = np.array(Image.open(_SCREENSHOT_PATH))
    except ImportError:
        print("[ui_parser] PIL not available — skipping per-box OCR")
        img = None
    except Exception as e:
        print(f"[ui_parser] Image load error: {e}")
        img = None

    # Merge: for each detection, run OCR on the bounding box
    elements = []
    for det in detections:
        cx = det["x"] + det["w"] // 2
        cy = det["y"] + det["h"] // 2

        # Filter to requested region
        if not (min_x <= cx <= max_x and min_y <= cy <= max_y):
            continue

        # Run OCR on the detected bounding box
        text = ""
        if img is not None:
            # Expand box slightly for better OCR (pad 4px each side)
            pad = 4
            ox = max(0, det["x"] - pad)
            oy = max(0, det["y"] - pad)
            ow = min(det["w"] + 2 * pad, img.shape[1] - ox)
            oh = min(det["h"] + 2 * pad, img.shape[0] - oy)
            text = _ocr_region(img, ox, oy, ow, oh)

        elements.append({
            "type": det["class_name"],
            "text": text,
            "x": det["x"],
            "y": det["y"],
            "w": det["w"],
            "h": det["h"],
            "cx": cx,
            "cy": cy,
            "click_x": cx,    # exact pixel to click (screen coords)
            "click_y": cy,    # exact pixel to click (screen coords)
            "conf": det["confidence"],
        })

    # Sort top-to-bottom, left-to-right
    elements.sort(key=lambda e: (e["y"], e["x"]))

    # Save to cache (same format as screen_map)
    cache = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "yolo",
        "screen_w": SCREEN_W,
        "screen_h": SCREEN_H,
        "count": len(elements),
        "elements": elements,
    }
    try:
        os.makedirs(os.path.dirname(_MAP_CACHE), exist_ok=True)
        with open(_MAP_CACHE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass

    return elements


# ── Element search ────────────────────────────────────────────────────────────

def find_element(query: str, elements: list[dict] = None) -> dict | None:
    """Find an element by text or type. Loads from cache if elements is None.

    Search priority:
      1. Exact text match
      2. Text substring match
      3. Type match (e.g. query="input" matches type="input")
      4. Fuzzy partial overlap
    """
    if elements is None:
        try:
            with open(_MAP_CACHE, "r") as f:
                cache = json.load(f)
                elements = cache.get("elements", [])
        except Exception:
            return None

    q = query.strip().lower()
    best = None
    best_score = -1

    for el in elements:
        text = (el.get("text") or "").lower()
        el_type = (el.get("type") or "").lower()

        # Exact text match
        if text == q:
            return el

        # Query in element text
        if len(q) >= 2 and q in text:
            score = 95 - abs(len(text) - len(q))
        # Element text in query
        elif len(q) >= 2 and len(text) >= 2 and text in q:
            score = 85 - abs(len(text) - len(q))
        # Type match
        elif q == el_type:
            score = 75
        # Type partial match (e.g. "search" matches "search_bar")
        elif len(q) >= 3 and q in el_type:
            score = 70
        else:
            continue

        if score > best_score:
            best_score = score
            best = el

    return best


def find_elements_by_type(element_type: str, elements: list[dict] = None) -> list[dict]:
    """Return all elements of a specific type (e.g. "button", "input")."""
    if elements is None:
        try:
            with open(_MAP_CACHE, "r") as f:
                cache = json.load(f)
                elements = cache.get("elements", [])
        except Exception:
            return []

    t = element_type.strip().lower()
    return [el for el in elements if (el.get("type") or "").lower() == t]


# ── Formatting for agent context ─────────────────────────────────────────────

def format_elements(elements: list[dict], max_items: int = 40) -> str:
    """Format element list as a readable string for the AI planner."""
    if not elements:
        return "[UI Parse: no elements detected]"

    # Check if elements came from YOLO or OCR fallback
    try:
        with open(_MAP_CACHE, "r") as f:
            cache = json.load(f)
            source = cache.get("source", "ocr")
    except Exception:
        source = "unknown"

    lines = [f"[UI Parse ({source}): {len(elements)} elements]"]
    for el in elements[:max_items]:
        t = el.get("type", "?")
        text = (el.get("text") or "")[:45]
        conf = el.get("conf", 0)
        lines.append(
            f"  [{t:12s}]  \"{text}\"  "
            f"at ({el['cx']}, {el['cy']})  "
            f"size {el['w']}x{el['h']}  "
            f"conf={conf:.2f}"
        )
    if len(elements) > max_items:
        lines.append(f"  ... and {len(elements) - max_items} more")
    return "\n".join(lines)


# ── Tool interface (for registry) ─────────────────────────────────────────────

def run_tool(args: dict = None) -> str:
    """Tool dispatcher for ui_parser.

    Actions:
      parse         — Run full detection + OCR pipeline on current screen
                      {"action": "parse"}
                      {"action": "parse", "app": "firefox"}

      find          — Find an element by text or type
                      {"action": "find", "query": "Search"}

      find_type     — Find all elements of a type
                      {"action": "find_type", "type": "button"}

      status        — Check if YOLO model is loaded
                      {"action": "status"}
    """
    if args is None:
        args = {}

    action = str(args.get("action", "parse")).strip().lower()

    if action == "parse":
        app_hint = str(args.get("app", "")).strip()
        confidence = float(args.get("confidence", 0.25))

        if app_hint:
            from tools.computer_use import _get_window_region
            min_x, max_x, min_y, max_y = _get_window_region(app_hint)
        else:
            min_x, max_x, min_y, max_y = 0, 99999, 0, 99999

        elements = parse_screen(min_x, max_x, min_y, max_y, confidence)
        return format_elements(elements)

    elif action == "find":
        query = str(args.get("query", "")).strip()
        if not query:
            return "Error: 'query' parameter is required"
        el = find_element(query)
        if el:
            return (
                f"Found [{el['type']}] \"{el.get('text', '')}\" "
                f"at ({el['cx']}, {el['cy']})  size {el['w']}x{el['h']}  "
                f"conf={el.get('conf', 0):.2f}"
            )
        return f"Element '{query}' not found. Run parse first to refresh."

    elif action == "find_type":
        el_type = str(args.get("type", "")).strip()
        if not el_type:
            return "Error: 'type' parameter is required"
        results = find_elements_by_type(el_type)
        if not results:
            return f"No elements of type '{el_type}' found."
        lines = [f"Found {len(results)} '{el_type}' elements:"]
        for el in results[:20]:
            lines.append(
                f"  \"{el.get('text', '')[:40]}\"  "
                f"at ({el['cx']}, {el['cy']})  size {el['w']}x{el['h']}"
            )
        return "\n".join(lines)

    elif action == "status":
        available = is_model_available()
        return (
            f"UI Parser status:\n"
            f"  Model path: {UI_MODEL_PATH}\n"
            f"  Model loaded: {'YES' if available else 'NO (using OCR fallback)'}\n"
            f"  Detection: {'YOLO' if available else 'tesseract OCR only'}"
        )

    else:
        return (
            f"Unknown action: '{action}'. "
            "Available: parse, find, find_type, status"
        )
