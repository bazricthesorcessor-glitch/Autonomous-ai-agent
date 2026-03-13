# ========================= config.py =========================
import os
import json
from datetime import date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DIR = os.path.join(BASE_DIR, "memory")
DAILY_DIR = os.path.join(MEMORY_DIR, "daily")

# Ensure base directories exist
os.makedirs(DAILY_DIR, exist_ok=True)

# === File Paths ===
IDENTITY_FILE = os.path.join(MEMORY_DIR, "identity.json")
TASKS_FILE = os.path.join(MEMORY_DIR, "tasks.json")
GOALS_FILE = os.path.join(MEMORY_DIR, "goals.json")
SYSTEM_STATE_FILE = os.path.join(MEMORY_DIR, "system_state.json")
VECTOR_STORE = os.path.join(MEMORY_DIR, "vector_store.json")
FACTS_FILE = os.path.join(MEMORY_DIR, "facts.json")
SCREEN_CACHE_FILE  = os.path.join(MEMORY_DIR, "screen_cache.json")
TODOS_FILE         = os.path.join(MEMORY_DIR, "todos.json")

# Temp folder for live screenshots and OCR output
SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshot")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# UI detection model (YOLO .pt file) — set in system_config.json or use default
MODELS_DIR = os.path.join(BASE_DIR, "models")
os.makedirs(MODELS_DIR, exist_ok=True)
UI_MODEL_PATH = os.path.join(MODELS_DIR, "ui_detect.pt")

# === Constants ===
USER_NAME = "Divyansh"
AI_NAME = "Avril"
LOG_DELIMITER = "---"

# === Memory Window Constants ===
RAW_DAYS_WINDOW = 10        # Keep 10 days of raw logs
SUMMARY_DAYS_WINDOW = 10    # Keep 10 days of summaries (Day 11-20)
MAX_RAW_TOKENS_PER_DAY = 8000  # Safety cap per day

# === Model Config (Updated to Phi4-Mini) ===
DECISION_MODEL = "phi4-mini:3.8b"   # Faster planner/router
CHAT_MODEL = "phi4-mini:3.8b"       # Fast general chat
CODE_MODEL = "qwen2.5-coder:7b-instruct-q4_K_M" # Specialist coder
EMBED_MODEL = "nomic-embed-text-v2-moe:latest"  # Embeddings

# === Helper Functions ===
def get_today_dir():
    """Returns the path to today's memory folder."""
    today_str = date.today().strftime("%Y-%m-%d")
    path = os.path.join(DAILY_DIR, today_str)
    os.makedirs(path, exist_ok=True)
    return path

def get_raw_log_path():
    return os.path.join(get_today_dir(), "raw.log")

def get_summary_path(target_date_str):
    """Returns path to summary for a specific date string YYYY-MM-DD."""
    return os.path.join(DAILY_DIR, target_date_str, "summary.txt")

def safe_load_json(path, default=None):
    """Safely load JSON, returning default if corrupted or missing."""
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default
