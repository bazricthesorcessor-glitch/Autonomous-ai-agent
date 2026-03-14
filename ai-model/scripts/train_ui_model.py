#!/usr/bin/env python3
"""
train_ui_model.py — Fine-tune YOLOv8-nano for desktop UI element detection.

Downloads yolov8n.pt (COCO pretrained) as starting weights and fine-tunes
on the labeled UI dataset. Augmentation is tuned for UI content: no rotation,
no flips, reduced mosaic, minimal hue shift.

On completion, copies best.pt → ai-model/models/ui_detect.pt for immediate
use by ui_parser.py (just restart the Flask server).

Usage:
    python scripts/train_ui_model.py
    python scripts/train_ui_model.py --epochs 50 --batch 4   # lower VRAM
    python scripts/train_ui_model.py --device cpu             # CPU-only

Requirements:
    pip install ultralytics torch torchvision
"""

import os
import sys
import shutil
import argparse

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.dirname(_SCRIPT_DIR)
_DATASET_DIR = os.path.join(_BASE_DIR, "datasets", "ui_detect")
_DATA_YAML = os.path.join(_DATASET_DIR, "data.yaml")
_MODELS_DIR = os.path.join(_BASE_DIR, "models")
_DEPLOY_PATH = os.path.join(_MODELS_DIR, "ui_detect.pt")


def check_dataset():
    """Verify dataset exists and has images."""
    train_imgs = os.path.join(_DATASET_DIR, "train", "images")
    val_imgs = os.path.join(_DATASET_DIR, "val", "images")

    if not os.path.isdir(train_imgs):
        print(f"Error: train/images not found at {train_imgs}")
        print("Run collect_ui_data.py → label → split_dataset.py first.")
        sys.exit(1)

    n_train = len([f for f in os.listdir(train_imgs) if f.endswith(".png")])
    n_val = len([f for f in os.listdir(val_imgs) if f.endswith(".png")]) if os.path.isdir(val_imgs) else 0

    if n_train == 0:
        print("Error: No training images found. Collect and label data first.")
        sys.exit(1)

    print(f"Dataset: {n_train} train, {n_val} val images")
    if n_train < 50:
        print(f"Warning: Only {n_train} training images. 200+ recommended for good results.")

    return n_train, n_val


def main():
    parser = argparse.ArgumentParser(
        description="Fine-tune YOLOv8-nano for UI element detection"
    )
    parser.add_argument("--epochs", type=int, default=100, help="Training epochs (default: 100)")
    parser.add_argument("--batch", type=int, default=8, help="Batch size (default: 8, lower for less VRAM)")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size (default: 640)")
    parser.add_argument("--patience", type=int, default=15, help="Early stopping patience (default: 15)")
    parser.add_argument("--device", type=str, default="0", help="Device: '0' for GPU, 'cpu' for CPU (default: 0)")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    args = parser.parse_args()

    # Verify dataset
    n_train, n_val = check_dataset()

    # Import ultralytics
    try:
        from ultralytics import YOLO
    except ImportError:
        print("Error: ultralytics not installed.")
        print("Run: pip install ultralytics torch torchvision")
        sys.exit(1)

    # Load pretrained YOLOv8-nano
    if args.resume:
        last_pt = os.path.join(_BASE_DIR, "runs", "detect", "ui_detect", "weights", "last.pt")
        if not os.path.isfile(last_pt):
            print(f"Error: No checkpoint found at {last_pt}")
            sys.exit(1)
        print(f"Resuming from {last_pt}")
        model = YOLO(last_pt)
    else:
        print("Loading YOLOv8-nano pretrained weights (yolov8n.pt)...")
        model = YOLO("yolov8n.pt")  # auto-downloads from Ultralytics hub

    # Train with UI-specific augmentation settings
    print(f"\nStarting training: {args.epochs} epochs, batch={args.batch}, imgsz={args.imgsz}")
    print(f"Device: {args.device}")
    print(f"Early stopping patience: {args.patience}")
    print()

    results = model.train(
        data=_DATA_YAML,
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        patience=args.patience,
        device=args.device,

        # Project/name for organizing runs
        project=os.path.join(_BASE_DIR, "runs", "detect"),
        name="ui_detect",
        exist_ok=True,

        # UI-specific augmentation tuning
        degrees=0.0,       # No rotation — UIs are axis-aligned
        flipud=0.0,        # No vertical flip
        fliplr=0.0,        # No horizontal flip — UIs have fixed left-right layout
        mosaic=0.3,        # Reduced mosaic — full mosaic distorts UI spatial relationships
        hsv_h=0.005,       # Minimal hue shift — UI color schemes are meaningful
        hsv_s=0.3,         # Moderate saturation variation
        hsv_v=0.3,         # Moderate brightness variation (simulates dark/light themes)
        scale=0.3,         # Moderate scale jitter
        translate=0.1,     # Small translation

        # General settings
        workers=4,
        verbose=True,
        save=True,
        plots=True,
    )

    # Check results
    best_pt = os.path.join(_BASE_DIR, "runs", "detect", "ui_detect", "weights", "best.pt")
    if not os.path.isfile(best_pt):
        print("\nWarning: best.pt not found — training may have failed.")
        sys.exit(1)

    # Deploy: copy best.pt to models/ui_detect.pt
    os.makedirs(_MODELS_DIR, exist_ok=True)
    shutil.copy2(best_pt, _DEPLOY_PATH)
    size_mb = os.path.getsize(_DEPLOY_PATH) / (1024 * 1024)
    print(f"\nModel deployed: {_DEPLOY_PATH} ({size_mb:.1f} MB)")

    # Print summary
    print("\n" + "=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)
    print(f"  Best weights: {best_pt}")
    print(f"  Deployed to:  {_DEPLOY_PATH}")
    print(f"  Model size:   {size_mb:.1f} MB")
    print(f"  Results dir:  {os.path.join(_BASE_DIR, 'runs', 'detect', 'ui_detect')}")
    print()
    print("Next steps:")
    print("  1. Restart the Flask server to load the new model")
    print("  2. Test: curl http://localhost:8000/ui-parse")
    print("     Should show 'source: yolo' instead of 'source: ocr'")
    print("  3. Test smart_click/type_into via /chat")
    print()
    print("To inspect metrics:")
    print(f"  ls {os.path.join(_BASE_DIR, 'runs', 'detect', 'ui_detect')}")
    print("  (contains confusion_matrix.png, results.png, PR_curve.png, etc.)")


if __name__ == "__main__":
    main()
