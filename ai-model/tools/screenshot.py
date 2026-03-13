import subprocess
import os

def run_tool(args):
    """
    Takes a screenshot (Wayland only), performs OCR, and returns text.
    """
    screenshot_path = "/tmp/screen_capture.png"

    # 1. Capture (Wayland - Grim)
    try:
        with open(os.devnull, 'w') as devnull:
            subprocess.run(["grim", screenshot_path], check=True, stdout=devnull, stderr=devnull)
    except FileNotFoundError:
        return "Error: 'grim' not found. This tool requires a Wayland session."
    except subprocess.CalledProcessError:
        return "Error: Failed to capture screen."

    # 2. OCR (Tesseract with PSM 3 for full screen layout)
    try:
        result = subprocess.run(
            ["tesseract", screenshot_path, "stdout", "--psm", "3"],
            capture_output=True,
            text=True,
            check=True
        )
        extracted_text = result.stdout.strip()
    except FileNotFoundError:
        return "Error: 'tesseract' not found. Run: sudo pacman -S tesseract"
    except subprocess.CalledProcessError:
        return "Error: OCR failed to read text."

    # 3. Clean and Truncate
    lines = [line.strip() for line in extracted_text.split('\n') if line.strip()]
    clean_text = "\n".join(lines)

    if not clean_text:
        return "Screen captured, but Tesseract found no readable text."

    # Truncate to save context for the Brain
    return f"[OCR RESULT]\n{clean_text[:2000]}"
