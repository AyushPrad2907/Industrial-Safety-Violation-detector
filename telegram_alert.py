import os
import time
import logging
from datetime import datetime
from typing import Optional, Tuple, Dict
from enum import Enum
import requests

import config
from temporal_engine import ViolationEvent, ViolationStatus

logger = logging.getLogger(__name__)

class TelegramAlertStatus(Enum):
    SENT = "SENT"
    SUPPRESSED_BY_COOLDOWN = "SUPPRESSED_BY_COOLDOWN"
    DISABLED = "DISABLED"
    CREDENTIALS_MISSING = "CREDENTIALS_MISSING"
    FAILED = "FAILED"

class TelegramAlertManager:
    """
    Handles dispatching rate-limited alerts and evidence snapshots to Telegram.
    Enforces in-memory per-worker / per-violation cooldowns to prevent spam.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        cooldown_seconds: Optional[int] = None
    ):
        self.bot_token = (bot_token if bot_token is not None else config.TELEGRAM_BOT_TOKEN).strip()
        self.chat_id = (chat_id if chat_id is not None else config.TELEGRAM_CHAT_ID).strip()
        self.enabled = enabled if enabled is not None else config.TELEGRAM_ALERTS_ENABLED
        self.cooldown_seconds = cooldown_seconds if cooldown_seconds is not None else config.DEFAULT_TELEGRAM_ALERT_COOLDOWN_SECONDS

        # In-memory cooldown tracking: (track_id, violation_type) -> last_sent_timestamp
        self.last_alert_time: Dict[Tuple[int, str], float] = {}

    def is_configured(self) -> bool:
        """Returns True if bot token and chat ID are populated."""
        return bool(self.bot_token and self.chat_id)

    def check_cooldown(self, track_id: int, violation_type: str, now: Optional[float] = None) -> bool:
        """
        Returns True if the cooldown has elapsed and an alert can be sent,
        or False if still in cooldown.
        """
        current_time = now if now is not None else time.time()
        key = (track_id, violation_type)
        last_time = self.last_alert_time.get(key, 0.0)
        return (current_time - last_time) >= self.cooldown_seconds

    def send_alert(self, event: ViolationEvent, evidence_path: Optional[str] = None, now: Optional[float] = None) -> TelegramAlertStatus:
        """
        Sends an alert for a CONFIRMED ViolationEvent.
        First attempts to send photo with caption; falls back to text-only if photo upload fails.
        """
        if not self.enabled:
            return TelegramAlertStatus.DISABLED

        if not self.is_configured():
            logger.info("Telegram alert skipped: bot credentials are not configured.")
            return TelegramAlertStatus.CREDENTIALS_MISSING

        current_time = now if now is not None else time.time()
        v_type_str = event.violation_type.value

        if not self.check_cooldown(event.track_id, v_type_str, current_time):
            logger.info(f"Telegram alert for Worker #{event.track_id} {v_type_str} suppressed by cooldown.")
            return TelegramAlertStatus.SUPPRESSED_BY_COOLDOWN

        caption = self._format_caption(event)
        api_base = f"https://api.telegram.org/bot{self.bot_token}"

        sent_success = False

        # Attempt 1: Send Photo with caption if evidence is provided and exists
        if evidence_path and os.path.exists(evidence_path):
            try:
                with open(evidence_path, "rb") as photo_file:
                    res = requests.post(
                        f"{api_base}/sendPhoto",
                        data={"chat_id": self.chat_id, "caption": caption, "parse_mode": "HTML"},
                        files={"photo": photo_file},
                        timeout=12
                    )
                    if res.status_code == 200:
                        sent_success = True
                    else:
                        logger.warning(f"Telegram sendPhoto failed with HTTP {res.status_code}. Attempting text fallback.")
            except Exception as e:
                logger.warning(f"Error uploading evidence photo to Telegram: {e}. Falling back to text.")

        # Attempt 2: Text-only fallback
        if not sent_success:
            try:
                res = requests.post(
                    f"{api_base}/sendMessage",
                    data={"chat_id": self.chat_id, "text": caption, "parse_mode": "HTML"},
                    timeout=10
                )
                if res.status_code == 200:
                    sent_success = True
                else:
                    logger.error(f"Telegram sendMessage failed with HTTP {res.status_code}: {res.text}")
            except Exception as e:
                logger.error(f"Exception sending Telegram alert: {e}")

        if sent_success:
            self.last_alert_time[(event.track_id, v_type_str)] = current_time
            logger.info(f"Telegram alert sent successfully for Worker #{event.track_id} {v_type_str}.")
            return TelegramAlertStatus.SENT
        else:
            return TelegramAlertStatus.FAILED

    def _format_caption(self, event: ViolationEvent) -> str:
        """Formats a clean, informative HTML alert message."""
        ts_str = datetime.fromtimestamp(event.timestamp).strftime("%Y-%m-%d %H:%M:%S") if isinstance(event.timestamp, (int, float)) else str(event.timestamp)
        v_label = event.violation_type.value.replace("_", " ").title()
        zone_info = "⚠️ Yes (Restricted Area)" if event.is_zone_violation else "No (Transit Area)"

        return (
            f"🚨 <b>PPE SAFETY VIOLATION CONFIRMED</b>\n\n"
            f"👤 <b>Worker:</b> #{event.track_id}\n"
            f"🛑 <b>Violation:</b> {v_label}\n"
            f"⚡ <b>Severity:</b> {event.severity.value}\n"
            f"📊 <b>Decision Score:</b> {event.decision_score:.2f} ({int(event.missing_ratio * 100)}% missing)\n"
            f"📍 <b>Zone Intrusion:</b> {zone_info}\n"
            f"🕒 <b>Time:</b> {ts_str}\n"
            f"🆔 <b>Event ID:</b> <code>{event.event_id}</code>"
        )
