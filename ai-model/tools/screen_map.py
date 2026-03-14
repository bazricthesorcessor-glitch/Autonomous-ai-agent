# ========================= tools/screen_map.py =========================
"""
Screen Element Map — structured layout understanding from OCR.

Instead of raw text, produces a list of UI elements with bounding boxes:

  [
    {"text": "Search",  "x": 820, "y": 85, "w": 600, "h": 36, "cx": 1120, "cy": 103, "type": "search_bar"},
    {"text": "Sign in", "x": 1700, "y": 85, "w": 80, "h": 30, "cx": 1740, "cy": 100, "type": "button"},
  ]

The AI reads this map and reasons:
    element = find("Search")
    click(element["cx"], element["cy"])

No coordinate guessing. No OCR re-runs. One scan → full spatial understanding.

Pipeline:
  1. grim fullscreen capture
  2. tesseract --psm 3 tsv → per-word bounding boxes
  3. Group adjacent words on the same line into elements
  4. Classify each element (search_bar, button, nav, heading, text)
  5. Save to cache/screen_map.json
  6. Return the element list
"""

import os
import subprocess
import json
import time

import config

_CU_PNG = os.path.join(config.SCREENSHOT_DIR, "_map_screen.png")
_MAP_CACHE = os.path.join(config.SCREENSHOT_DIR, "screen_map.json")

# ── Grouping thresholds ───────────────────────────────────────────────────────
_LINE_Y_TOLERANCE = 12     # words within ±12px vertically = same line
_WORD_GAP_MAX     = 40     # words separated by <40px horizontally = same element
_MIN_CONF         = 30     # drop words below this OCR confidence


def _capture() -> bool:
    try:
        subprocess.run(["grim", _CU_PNG], check=True, capture_output=True, timeout=8)
        return True
    except Exception:
        return False


def _ocr_tsv() -> str:
    try:
        r = subprocess.run(
            ["tesseract", _CU_PNG, "stdout", "--psm", "3", "tsv"],
            capture_output=True, text=True, check=True, timeout=30
        )
        return r.stdout
    except Exception:
        return ""


def _parse_words(tsv: str) -> list[dict]:
    """Parse tesseract TSV into a list of word dicts with bounding boxes."""
    words = []
    for line in tsv.strip().split('\n')[1:]:
        parts = line.split('\t')
        if len(parts) < 12:
            continue
        try:
            conf = float(parts[10])
            text = parts[11].strip()
        except (ValueError, IndexError):
            continue
        if conf < _MIN_CONF or not text:
            continue
        try:
            x = int(parts[6])
            y = int(parts[7])
            w = int(parts[8])
            h = int(parts[9])
        except ValueError:
            continue
        if w < 2 or h < 2:
            continue
        words.append({
            "text": text,
            "x": x, "y": y, "w": w, "h": h,
            "conf": conf,
        })
    return words


def _group_into_elements(words: list[dict]) -> list[dict]:
    """
    Group adjacent words on the same line into single elements.
    "Sign" + "in" (close together, same y) → "Sign in" with merged bounding box.
    """
    if not words:
        return []

    # Sort by y (top→bottom), then x (left→right)
    words.sort(key=lambda w: (w["y"], w["x"]))

    elements = []
    current = None

    for word in words:
        if current is None:
            current = {
                "text": word["text"],
                "x": word["x"], "y": word["y"],
                "w": word["w"], "h": word["h"],
                "conf": word["conf"],
                "_words": [word],
            }
            continue

        # Check if this word is on the same line and close enough to merge
        same_line = abs(word["y"] - current["y"]) <= _LINE_Y_TOLERANCE
        gap = word["x"] - (current["x"] + current["w"])

        if same_line and 0 <= gap <= _WORD_GAP_MAX:
            # Merge into current element
            current["text"] += " " + word["text"]
            new_right = word["x"] + word["w"]
            new_bottom = max(current["y"] + current["h"], word["y"] + word["h"])
            current["w"] = new_right - current["x"]
            current["h"] = new_bottom - current["y"]
            current["conf"] = min(current["conf"], word["conf"])
            current["_words"].append(word)
        else:
            # Flush current element, start new one
            elements.append(current)
            current = {
                "text": word["text"],
                "x": word["x"], "y": word["y"],
                "w": word["w"], "h": word["h"],
                "conf": word["conf"],
                "_words": [word],
            }

    if current:
        elements.append(current)

    # Add center coordinates and clean up
    for el in elements:
        el["cx"] = el["x"] + el["w"] // 2
        el["cy"] = el["y"] + el["h"] // 2
        del el["_words"]

    return elements


def _classify(element: dict) -> str:
    """
    Classify an element based on its size and text content.
    Returns: search_bar | button | nav | heading | icon | text
    """
    text = element["text"].lower()
    w = element["w"]
    h = element["h"]

    # Search bars: wide, contain "search"
    if w > 200 and "search" in text:
        return "search_bar"

    # Navigation items at top of screen
    if element["y"] < 80 and w < 200:
        return "nav"

    # Buttons: short text, small area
    word_count = len(element["text"].split())
    if word_count <= 3 and h < 50 and w < 180:
        return "button"

    # Headings: large height
    if h > 30 and word_count <= 6:
        return "heading"

    # Icons: very small, 1-2 chars
    if len(element["text"]) <= 2 and w < 40:
        return "icon"

    return "text"


def scan(min_x=0, max_x=99999, min_y=0, max_y=99999) -> list[dict]:
    """
    Full pipeline: capture → OCR → group → classify → save.
    Optional region bounds to restrict results (e.g. Firefox window only).
    Returns the element list.
    """
    if not _capture():
        return []

    tsv = _ocr_tsv()
    if not tsv:
        return []

    words = _parse_words(tsv)

    # Filter to region
    words = [w for w in words
             if min_x <= w["x"] + w["w"]//2 <= max_x
             and min_y <= w["y"] + w["h"]//2 <= max_y]

    elements = _group_into_elements(words)

    # Classify each element
    for el in elements:
        el["type"] = _classify(el)

    # Save to cache
    cache = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
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


def find_element(query: str, elements: list[dict] = None) -> dict | None:
    """
    Find the best matching element by text.
    Priority: exact match > substring > type match.
    If elements is None, loads from cache.
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
        text = el["text"].lower()

        # Exact match
        if text == q:
            return el   # instant win

        # Query is substring of element text (both must be ≥3 chars)
        if len(q) >= 3 and len(text) >= 3 and q in text:
            score = 90 - abs(len(text) - len(q))
        # Element text is substring of query (both must be ≥3 chars)
        elif len(q) >= 3 and len(text) >= 3 and text in q:
            score = 80 - abs(len(text) - len(q))
        # Type match (e.g. query="search_bar" matches type)
        elif q == el.get("type", ""):
            score = 70
        else:
            continue

        if score > best_score:
            best_score = score
            best = el

    return best


def format_map(elements: list[dict], max_items: int = 30) -> str:
    """Format element list as a readable string for the AI context."""
    if not elements:
        return "[Screen map: no elements detected]"

    lines = [f"[Screen map: {len(elements)} elements]"]
    for el in elements[:max_items]:
        t = el.get("type", "?")
        lines.append(
            f"  [{t:10s}]  \"{el['text'][:50]}\"  "
            f"at ({el['cx']}, {el['cy']})  "
            f"size {el['w']}×{el['h']}  "
            f"conf={el.get('conf', 0):.0f}"
        )
    if len(elements) > max_items:
        lines.append(f"  ... and {len(elements) - max_items} more")
    return "\n".join(lines)
