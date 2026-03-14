#!/usr/bin/env python3
"""
split_dataset.py — Split labeled UI data into train/val sets.

Expects raw/ to contain image files (.png) with matching YOLO label
files (.txt) side-by-side:
    raw/ui_20260314_120000_123.png
    raw/ui_20260314_120000_123.txt

Performs an 80/20 random split into:
    train/images/  +  train/labels/
    val/images/    +  val/labels/

Usage:
    python scripts/split_dataset.py
    python scripts/split_dataset.py --ratio 0.85  # 85% train
    python scripts/split_dataset.py --zip          # also create ui_dataset.zip for Colab
"""

import os
import sys
import shutil
import random
import zipfile
import argparse

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_SCRIPT_DIR)
_DATASET_DIR = os.path.join(_BASE_DIR, "datasets", "ui_detect")


def find_labeled_pairs(raw_dir: str) -> list[tuple[str, str]]:
    """Find image files that have matching .txt label files."""
    pairs = []
    for fname in sorted(os.listdir(raw_dir)):
        if not fname.lower().endswith(".png"):
            continue
        img_path = os.path.join(raw_dir, fname)
        lbl_path = os.path.join(raw_dir, fname.rsplit(".", 1)[0] + ".txt")
        if os.path.isfile(lbl_path):
            pairs.append((img_path, lbl_path))
    return pairs


def main():
    parser = argparse.ArgumentParser(
        description="Split labeled UI dataset into train/val"
    )
    parser.add_argument(
        "--ratio", type=float, default=0.8,
        help="Train ratio (default: 0.8 = 80%% train, 20%% val)"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility (default: 42)"
    )
    parser.add_argument(
        "--dataset", type=str, default=_DATASET_DIR,
        help=f"Dataset root directory (default: {_DATASET_DIR})"
    )
    args = parser.parse_args()

    raw_dir = os.path.join(args.dataset, "raw")
    if not os.path.isdir(raw_dir):
        print(f"Error: raw/ directory not found at {raw_dir}")
        sys.exit(1)

    pairs = find_labeled_pairs(raw_dir)
    if not pairs:
        unlabeled = len([f for f in os.listdir(raw_dir) if f.endswith(".png")])
        print(f"No labeled pairs found in {raw_dir}")
        if unlabeled:
            print(f"  Found {unlabeled} images but no matching .txt label files.")
            print("  Label your images first (CVAT/Label Studio → YOLO format).")
        sys.exit(1)

    print(f"Found {len(pairs)} labeled image-label pairs")

    # Shuffle and split
    random.seed(args.seed)
    random.shuffle(pairs)

    split_idx = int(len(pairs) * args.ratio)
    train_pairs = pairs[:split_idx]
    val_pairs = pairs[split_idx:]

    print(f"Split: {len(train_pairs)} train, {len(val_pairs)} val")

    # Create output directories
    dirs = {
        "train_img": os.path.join(args.dataset, "train", "images"),
        "train_lbl": os.path.join(args.dataset, "train", "labels"),
        "val_img": os.path.join(args.dataset, "val", "images"),
        "val_lbl": os.path.join(args.dataset, "val", "labels"),
    }
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)

    # Copy files
    def copy_pairs(pair_list, img_dir, lbl_dir, label):
        for img_path, lbl_path in pair_list:
            shutil.copy2(img_path, os.path.join(img_dir, os.path.basename(img_path)))
            shutil.copy2(lbl_path, os.path.join(lbl_dir, os.path.basename(lbl_path)))
        print(f"  {label}: {len(pair_list)} pairs → {img_dir}")

    copy_pairs(train_pairs, dirs["train_img"], dirs["train_lbl"], "train")
    copy_pairs(val_pairs, dirs["val_img"], dirs["val_lbl"], "val")

    print(f"\nDone. Dataset ready at {args.dataset}")
    print("Next: python scripts/train_ui_model.py")


if __name__ == "__main__":
    main()
