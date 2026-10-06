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
DEFAULT_MODEL_WEIGHTS = os.getenv("DEFAULT_MODEL_WEIGHTS", "best.pt")
DEFAULT_CONFIDENCE = float(os.getenv("DEFAULT_CONFIDENCE", "0.4"))
DEFAULT_COOLDOWN = int(os.getenv("DEFAULT_COOLDOWN_SECONDS", "10"))

def has_telegram_credentials() -> bool:
    """Return True if both Telegram Token and Chat ID are configured."""
    return bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)
