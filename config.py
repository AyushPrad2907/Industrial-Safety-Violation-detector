import os
from pathlib import Path
from dotenv import load_dotenv

# Base Directory of the Project
BASE_DIR = Path(__file__).resolve().parent

# Automatically locate and load .env file if it exists
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# Telegram Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Database & Storage
DB_PATH = str(BASE_DIR / os.getenv("DB_NAME", "violations.db"))
EVIDENCE_DIR = str(BASE_DIR / os.getenv("EVIDENCE_DIR", "evidence"))

# Detection & Application Defaults
DEFAULT_CAMERA_NAME = os.getenv("DEFAULT_CAMERA_NAME", "Cam-1")
DEFAULT_MODEL_WEIGHTS = os.getenv("DEFAULT_MODEL_WEIGHTS", "yolov8n.pt")
DEFAULT_PPE_MODEL_WEIGHTS = os.getenv("DEFAULT_PPE_MODEL_WEIGHTS", "models/ppe_yolov8n_best.pt")
DEFAULT_CONFIDENCE = float(os.getenv("DEFAULT_CONFIDENCE", "0.4"))
DEFAULT_PPE_CONFIDENCE = float(os.getenv("DEFAULT_PPE_CONFIDENCE", "0.35"))
DEFAULT_ASSOCIATION_THRESHOLD = float(os.getenv("DEFAULT_ASSOCIATION_THRESHOLD", "0.35"))
DEFAULT_COOLDOWN = int(os.getenv("DEFAULT_COOLDOWN_SECONDS", "10"))

# Phase 5: Temporal Violation Engine Defaults
DEFAULT_TEMPORAL_WINDOW_SIZE = int(os.getenv("TEMPORAL_WINDOW_SIZE", "12"))
DEFAULT_VIOLATION_RATIO_THRESHOLD = float(os.getenv("VIOLATION_RATIO_THRESHOLD", "0.70"))
DEFAULT_MIN_OBSERVABLE_FRAMES = int(os.getenv("MIN_OBSERVABLE_FRAMES", "5"))
DEFAULT_RESOLUTION_RATIO_THRESHOLD = float(os.getenv("RESOLUTION_RATIO_THRESHOLD", "0.60"))
DEFAULT_TRACK_HISTORY_TTL = int(os.getenv("TRACK_HISTORY_TTL", "30"))

# Phase 6: Persistence, Evidence, & Alerting Configuration
DATABASE_PATH = str(BASE_DIR / os.getenv("DATABASE_PATH", "data/violations.db"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", TELEGRAM_TOKEN).strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_ALERTS_ENABLED = os.getenv("TELEGRAM_ALERTS_ENABLED", "false").strip().lower() in ("true", "1", "yes")
DEFAULT_TELEGRAM_ALERT_COOLDOWN_SECONDS = int(os.getenv("TELEGRAM_ALERT_COOLDOWN_SECONDS", "60"))

def has_telegram_credentials() -> bool:
    """Return True if both Telegram Token and Chat ID are configured."""
    return bool((TELEGRAM_BOT_TOKEN or TELEGRAM_TOKEN) and TELEGRAM_CHAT_ID)
