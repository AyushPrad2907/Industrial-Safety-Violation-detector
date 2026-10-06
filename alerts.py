import requests
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

def send_telegram(text: str, image_path: str = None) -> bool:
    """
    Sends a notification to Telegram with an optional image snapshot.
    Credentials are read from central configuration.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        base = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
        if image_path:
            with open(image_path, "rb") as f:
                res = requests.post(
                    f"{base}/sendPhoto",
                    data={"chat_id": TELEGRAM_CHAT_ID, "caption": text},
                    files={"photo": f},
                    timeout=10
                )
                return res.status_code == 200
        else:
            res = requests.post(
                f"{base}/sendMessage",
                data={"chat_id": TELEGRAM_CHAT_ID, "text": text},
                timeout=10
            )
            return res.status_code == 200
    except Exception:
        return False
