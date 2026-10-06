import os, requests
# Set env vars: TELEGRAM_TOKEN (from @BotFather) and TELEGRAM_CHAT_ID
def send_telegram(text, image_path=None):
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    try:
        base = f"https://api.telegram.org/bot{token}"
        if image_path:
            with open(image_path, "rb") as f:
                requests.post(f"{base}/sendPhoto", data={"chat_id": chat, "caption": text},
                              files={"photo": f}, timeout=10)
        else:
            requests.post(f"{base}/sendMessage", data={"chat_id": chat, "text": text}, timeout=10)
        return True
    except Exception:
        return False
