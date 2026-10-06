import logging
from typing import Optional, Dict, Any, Set
import numpy as np

import database
import evidence
from telegram_alert import TelegramAlertManager, TelegramAlertStatus
from temporal_engine import ViolationEvent, ViolationStatus

logger = logging.getLogger(__name__)

class ViolationHandler:
    """
    Central Phase 6 Event Handler:
    Coordinates Evidence Capture -> SQLite Persistence -> Rate-limited Telegram Alerts
    for CONFIRMED ViolationEvents.
    """

    def __init__(
        self,
        alert_manager: Optional[TelegramAlertManager] = None,
        db_path: Optional[str] = None,
        evidence_dir: Optional[str] = None
    ):
        self.alert_manager = alert_manager or TelegramAlertManager()
        self.db_path = db_path
        self.evidence_dir = evidence_dir
        # In-memory set to prevent reprocessing the exact same event_id
        self.processed_events: Set[str] = set()

    def handle_violation(
        self,
        event: ViolationEvent,
        frame: np.ndarray,
        now: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Processes a ViolationEvent:
        1. Verifies event.status == CONFIRMED.
        2. Deduplicates event_id in memory.
        3. Captures cropped evidence image with metadata banner.
        4. Inserts violation record into SQLite database.
        5. Dispatches rate-limited Telegram alert.

        Returns structured status dict:
            {
                "event_id": str,
                "processed": bool,
                "evidence_path": Optional[str],
                "db_saved": bool,
                "telegram_status": str,
                "reason": str
            }
        """
        # 1. Status Guard: Phase 6 handles only CONFIRMED violations
        if event.status != ViolationStatus.CONFIRMED:
            return {
                "event_id": event.event_id,
                "processed": False,
                "evidence_path": None,
                "db_saved": False,
                "telegram_status": "SKIPPED_NOT_CONFIRMED",
                "reason": f"Event status is {event.status.value}, not CONFIRMED"
            }

        # 2. In-memory deduplication check
        if event.event_id in self.processed_events:
            return {
                "event_id": event.event_id,
                "processed": False,
                "evidence_path": None,
                "db_saved": True,  # Already in DB
                "telegram_status": "SKIPPED_DUPLICATE_EVENT",
                "reason": "Event ID has already been processed"
            }

        # 3. Capture Evidence Snapshot
        evidence_path = None
        try:
            evidence_path = evidence.capture_evidence(
                event=event,
                frame=frame,
                output_dir=self.evidence_dir
            )
        except Exception as e:
            logger.error(f"Failed to capture evidence for event {event.event_id}: {e}")

        # 4. Save to SQLite database (resilient to evidence failures)
        db_saved = False
        try:
            db_saved = database.save_violation(
                event=event,
                evidence_path=evidence_path,
                db_path=self.db_path
            )
        except Exception as e:
            logger.error(f"Failed to save violation {event.event_id} to database: {e}")

        # 5. Attempt Telegram Alert (resilient to alert failures)
        telegram_status = TelegramAlertStatus.DISABLED.value
        try:
            res_status = self.alert_manager.send_alert(
                event=event,
                evidence_path=evidence_path,
                now=now
            )
            telegram_status = res_status.value
        except Exception as e:
            logger.error(f"Failed to send Telegram alert for event {event.event_id}: {e}")
            telegram_status = TelegramAlertStatus.FAILED.value

        # Mark event as processed in memory
        self.processed_events.add(event.event_id)

        return {
            "event_id": event.event_id,
            "processed": True,
            "evidence_path": evidence_path,
            "db_saved": db_saved,
            "telegram_status": telegram_status,
            "reason": "Successfully processed confirmed violation"
        }

    def reset(self):
        """Clears in-memory processed event IDs and alert manager cooldowns."""
        self.processed_events.clear()
        if hasattr(self.alert_manager, "last_alert_time"):
            self.alert_manager.last_alert_time.clear()

