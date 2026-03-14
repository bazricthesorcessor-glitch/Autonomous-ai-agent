#!/usr/bin/env python3
"""
make_grid.py — Generate a coordinate grid reference image for UI detection.

Creates a 1920x1200 image with:
  - Grid lines every N pixels (default: 100px)
  - Coordinate labels at intersections
  - Color-coded zones for quick visual reference
  - Crosshair markers at grid intersections

Use this for:
  - Verifying YOLO coordinate accuracy after training
  - Visual debugging of click coordinates
  - Calibration reference when testing smart_click/type_into

Usage:
    python scripts/make_grid.py                           # default 100px grid
    python scripts/make_grid.py --cell 50                 # finer 50px grid
    python scripts/make_grid.py --cell 200 --out grid.png # coarser grid
    python scripts/make_grid.py --overlay screenshot.png  # grid on top of a screenshot
"""

import os
import sys
import argparse

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_SCRIPT_DIR)
_DEFAULT_OUT = os.path.join(_BASE_DIR, "datasets", "ui_detect", "grid_1920x1200.png")


def make_grid(
    width: int = 1920,
    height: int = 1200,
    cell: int = 100,
    out_path: str = _DEFAULT_OUT,
    overlay_path: str = None,
):
    """Generate a grid reference image."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Error: Pillow not installed. Run: pip install Pillow")
        sys.exit(1)

    # Base image: dark background or overlay
    if overlay_path and os.path.isfile(overlay_path):
        img = Image.open(overlay_path).convert("RGBA")
        img = img.resize((width, height), Image.LANCZOS)
        # Create semi-transparent overlay
        grid_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(grid_layer)
        line_color = (0, 255, 0, 100)     # semi-transparent green
        text_color = (0, 255, 0, 200)
        major_color = (255, 255, 0, 140)  # yellow for major lines
    else:
        img = Image.new("RGB", (width, height), (30, 30, 30))
        grid_layer = None
        draw = ImageDraw.Draw(img)
        line_color = (60, 60, 60)
        text_color = (180, 180, 180)
        major_color = (100, 100, 100)

    # Try to load a monospace font
    font = None
    font_small = None
    for font_path in [
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/noto/NotoSansMono-Regular.ttf",
    ]:
        if os.path.isfile(font_path):
            try:
                from PIL import ImageFont
                font = ImageFont.truetype(font_path, 12)
                font_small = ImageFont.truetype(font_path, 9)
            except Exception:
                pass
            break

    # Draw grid lines
    for x in range(0, width + 1, cell):
        is_major = (x % (cell * 5) == 0) if cell <= 100 else (x % (cell * 2) == 0)
        color = major_color if is_major else line_color
        lw = 2 if is_major else 1
        draw.line([(x, 0), (x, height)], fill=color, width=lw)

    for y in range(0, height + 1, cell):
        is_major = (y % (cell * 5) == 0) if cell <= 100 else (y % (cell * 2) == 0)
        color = major_color if is_major else line_color
        lw = 2 if is_major else 1
        draw.line([(0, y), (width, y)], fill=color, width=lw)

    # Label coordinates at intersections
    label_step = cell if cell >= 100 else cell * 2  # skip labels on fine grids
    for x in range(0, width + 1, label_step):
        for y in range(0, height + 1, label_step):
            # Small crosshair
            ch = 3
            draw.line([(x - ch, y), (x + ch, y)], fill=text_color, width=1)
            draw.line([(x, y - ch), (x, y + ch)], fill=text_color, width=1)

            # Coordinate label
            label = f"{x},{y}"
            f = font_small if cell < 100 else font
            draw.text((x + 3, y + 1), label, fill=text_color, font=f)

    # Draw screen border
    border_color = (255, 100, 100) if grid_layer is None else (255, 100, 100, 200)
    draw.rectangle([(0, 0), (width - 1, height - 1)], outline=border_color, width=2)

    # Title
    title = f"AVRIL Grid Reference — {width}x{height} — {cell}px cells"
    draw.text((10, 5), title, fill=(255, 255, 255) if grid_layer is None else (255, 255, 255, 230), font=font)

    # Screen center marker
    cx, cy = width // 2, height // 2
    center_color = (255, 50, 50) if grid_layer is None else (255, 50, 50, 200)
    draw.line([(cx - 15, cy), (cx + 15, cy)], fill=center_color, width=2)
    draw.line([(cx, cy - 15), (cx, cy + 15)], fill=center_color, width=2)
    draw.text((cx + 5, cy + 5), f"CENTER {cx},{cy}", fill=center_color, font=font)

    # Composite overlay if used
    if grid_layer is not None:
        img = Image.alpha_composite(img, grid_layer)
        img = img.convert("RGB")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    size_kb = os.path.getsize(out_path) / 1024
    print(f"Grid saved: {out_path} ({size_kb:.0f} KB)")
    print(f"  Resolution: {width}x{height}")
    print(f"  Cell size:  {cell}px")
    print(f"  Grid lines: {width // cell + 1} vertical x {height // cell + 1} horizontal")


def main():
    parser = argparse.ArgumentParser(description="Generate coordinate grid reference image")
    parser.add_argument("--width", type=int, default=1920, help="Screen width (default: 1920)")
    parser.add_argument("--height", type=int, default=1200, help="Screen height (default: 1200)")
    parser.add_argument("--cell", type=int, default=100, help="Grid cell size in pixels (default: 100)")
    parser.add_argument("--out", type=str, default=_DEFAULT_OUT, help="Output path")
    parser.add_argument("--overlay", type=str, default=None, help="Overlay grid on this screenshot")
    args = parser.parse_args()

    make_grid(args.width, args.height, args.cell, args.out, args.overlay)


if __name__ == "__main__":
    main()
