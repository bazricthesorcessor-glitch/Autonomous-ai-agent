#!/usr/bin/env python3
"""
collect_ui_data.py — Screenshot collector for UI detection training data.

Captures fullscreen screenshots via grim and saves them to the raw/
dataset directory. Use burst mode to rapidly collect many samples while
you switch between apps and windows.

Usage:
    # Single screenshot
    python scripts/collect_ui_data.py

    # Burst: 50 screenshots, 2 seconds apart
    python scripts/collect_ui_data.py --burst 50 --delay 2

    # Custom output dir
    python scripts/collect_ui_data.py --burst 30 --delay 3 --out /tmp/ui_shots

After collecting, label with CVAT or Label Studio (YOLO 1.1 format),
then run split_dataset.py to create train/val split.
"""

import os
import sys
import time
import argparse
import subprocess
from datetime import datetime

# Default output directory
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_SCRIPT_DIR)
_DEFAULT_OUT = os.path.join(_BASE_DIR, "datasets", "ui_detect", "raw")


def capture_screenshot(out_dir: str) -> str | None:
    """Capture one fullscreen screenshot via grim. Returns saved path or None."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # ms precision
    filename = f"ui_{ts}.png"
    path = os.path.join(out_dir, filename)

    try:
        subprocess.run(
            ["grim", path],
            check=True, capture_output=True, timeout=10,
        )
        return path
    except FileNotFoundError:
        print("Error: 'grim' not found. Install it: sudo pacman -S grim")
        return None
    except subprocess.CalledProcessError as e:
        print(f"Error: grim failed — {e.stderr.decode().strip()}")
        return None
    except subprocess.TimeoutExpired:
        print("Error: grim timed out")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Collect desktop screenshots for UI detection training"
    )
    parser.add_argument(
        "--burst", type=int, default=1,
        help="Number of screenshots to capture (default: 1)"
    )
    parser.add_argument(
        "--delay", type=float, default=2.0,
        help="Seconds between burst captures (default: 2.0)"
    )
    parser.add_argument(
        "--out", type=str, default=_DEFAULT_OUT,
        help=f"Output directory (default: {_DEFAULT_OUT})"
    )
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    existing = len([f for f in os.listdir(args.out) if f.endswith(".png")])
    print(f"Output: {args.out}")
    print(f"Existing images: {existing}")
    print(f"Capturing {args.burst} screenshot(s), {args.delay}s apart")
    print()

    if args.burst > 1:
        print("Switch between apps/windows during capture for variety.")
        print("Starting in 3 seconds...")
        time.sleep(3)

    saved = 0
    for i in range(args.burst):
        path = capture_screenshot(args.out)
        if path:
            saved += 1
            size_kb = os.path.getsize(path) / 1024
            print(f"  [{saved}/{args.burst}] {os.path.basename(path)}  ({size_kb:.0f} KB)")
        else:
            print(f"  [{i+1}/{args.burst}] FAILED")
            if i == 0:
                sys.exit(1)

        if i < args.burst - 1:
            time.sleep(args.delay)

    total = existing + saved
    print(f"\nDone. {saved} new screenshots saved. Total in raw/: {total}")
    print()
    print("Next steps:")
    print("  1. Label images with CVAT (cvat.ai) or Label Studio (labelstud.io)")
    print("     - Create a project with these 16 classes (in order):")
    print("       button, input, icon, menu, card, list, checkbox, radio,")
    print("       dropdown, toggle, link, image, text, header, nav, search_bar")
    print("     - Draw bounding boxes around UI elements")
    print("     - Export as YOLO 1.1 format (txt files with: class_id cx cy w h)")
    print("  2. Place .txt label files alongside images in raw/")
    print("  3. Run: python scripts/split_dataset.py")
    print("  4. Run: python scripts/train_ui_model.py")


if __name__ == "__main__":
    main()
