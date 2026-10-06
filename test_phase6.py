"""
Test Suite for Phase 6: Evidence Persistence, SQLite Database, and Rate-Limited Telegram Alerts.
All tests use temporary directories and unittest.mock - NO real Telegram network calls or persistent disk pollution.
"""

import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from database import (
    init_db,
    save_violation,
    get_recent_violations,
    get_violation_count,
    get_violation_by_id,
)
from evidence import capture_evidence, sanitize_filename
from telegram_alert import (
    TelegramAlertManager,
    TelegramAlertStatus,
)
from temporal_engine import (
    ViolationEvent,
    ViolationStatus,
    SeverityLevel,
    ViolationType,
)
from violation_handler import ViolationHandler


def create_mock_event(
    event_id: str = "evt_001",
    track_id: int = 1,
    violation_type: ViolationType = ViolationType.MISSING_HELMET,
    severity: SeverityLevel = SeverityLevel.HIGH,
    status: ViolationStatus = ViolationStatus.CONFIRMED,
    frame_index: int = 42,
    timestamp: float = 1710000000.0,
    decision_score: float = 0.85,
    missing_ratio: float = 0.85,
    observable_frames: int = 10,
    window_size: int = 12,
    is_zone_violation: bool = False,
    worker_bbox: tuple = (100, 100, 200, 300),
    message: str = "Worker #1 confirmed missing helmet",
) -> ViolationEvent:
    """Helper to generate standard ViolationEvent objects for testing."""
    return ViolationEvent(
        event_id=event_id,
        track_id=track_id,
        violation_type=violation_type,
        severity=severity,
        status=status,
        frame_index=frame_index,
        timestamp=timestamp,
        decision_score=decision_score,
        missing_ratio=missing_ratio,
        observable_frames=observable_frames,
        window_size=window_size,
        is_zone_violation=is_zone_violation,
        worker_bbox=worker_bbox,
        message=message,
    )


class TestPhase6(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_violations.db")
        self.evidence_dir = os.path.join(self.test_dir, "evidence")
        init_db(self.db_path)

        # Standard test image: 480x640x3 synthetic frame
        self.frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.rectangle(self.frame, (100, 100), (200, 300), (0, 255, 0), -1)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # ==========================================
    # Group 1: Database Operations
    # ==========================================

    def test_01_init_db_creates_table(self):
        """Test 1: init_db creates ppe_violations table with proper schema."""
        self.assertTrue(os.path.exists(self.db_path))
        count = get_violation_count(self.db_path)
        self.assertEqual(count, 0)

    def test_02_save_violation_and_retrieve(self):
        """Test 2: save_violation stores confirmed violation and get_recent_violations retrieves it."""
        event = create_mock_event(event_id="evt_save_01")
        evidence_path = os.path.join(self.evidence_dir, "event_evt_save_01.jpg")

        saved = save_violation(event, evidence_path=evidence_path, db_path=self.db_path)
        self.assertTrue(saved)

        records = get_recent_violations(limit=10, db_path=self.db_path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["event_id"], "evt_save_01")
        self.assertEqual(records[0]["track_id"], 1)
        self.assertEqual(records[0]["violation_type"], ViolationType.MISSING_HELMET.value)
        self.assertEqual(records[0]["severity"], "HIGH")
        self.assertEqual(records[0]["evidence_path"], evidence_path)

    def test_03_save_violation_idempotency(self):
        """Test 3: Duplicate event_id is safely ignored without throwing error."""
        event = create_mock_event(event_id="evt_dup_01")
        saved1 = save_violation(event, db_path=self.db_path)
        saved2 = save_violation(event, db_path=self.db_path)

        self.assertTrue(saved1)
        self.assertTrue(saved2)  # Idempotent execution returns True
        self.assertEqual(get_violation_count(self.db_path), 1)

    def test_04_get_violation_by_id(self):
        """Test 4: get_violation_by_id returns exact record or None if absent."""
        event = create_mock_event(event_id="evt_lookup_01")
        save_violation(event, db_path=self.db_path)

        record = get_violation_by_id("evt_lookup_01", db_path=self.db_path)
        self.assertIsNotNone(record)
        self.assertEqual(record["event_id"], "evt_lookup_01")

        missing = get_violation_by_id("non_existent", db_path=self.db_path)
        self.assertIsNone(missing)

    def test_05_database_handles_no_evidence_path(self):
        """Test 5: database safely records null/empty evidence_path."""
        event = create_mock_event(event_id="evt_no_evi_01")
        save_violation(event, evidence_path=None, db_path=self.db_path)

        record = get_violation_by_id("evt_no_evi_01", db_path=self.db_path)
        self.assertIsNotNone(record)
        self.assertEqual(record["evidence_path"], "")

    # ==========================================
    # Group 2: Evidence Capture
    # ==========================================

    def test_06_capture_evidence_creates_file(self):
        """Test 6: capture_evidence writes valid JPEG image to disk."""
        event = create_mock_event(event_id="evt_evi_01", worker_bbox=(100, 100, 200, 300))
        img_path = capture_evidence(
            event=event,
            frame=self.frame,
            output_dir=self.evidence_dir,
        )

        self.assertIsNotNone(img_path)
        self.assertTrue(os.path.exists(img_path))
        self.assertTrue(img_path.endswith(".jpg"))

        loaded = cv2.imread(img_path)
        self.assertIsNotNone(loaded)
        self.assertGreater(loaded.shape[0], 0)
        self.assertGreater(loaded.shape[1], 0)

    def test_07_capture_evidence_creates_directory_if_missing(self):
        """Test 7: capture_evidence automatically creates nested output_dir if absent."""
        nested_dir = os.path.join(self.test_dir, "deep", "nested", "evidence")
        self.assertFalse(os.path.exists(nested_dir))

        event = create_mock_event(event_id="evt_evi_nested")
        img_path = capture_evidence(
            event=event,
            frame=self.frame,
            output_dir=nested_dir,
        )
        self.assertTrue(os.path.exists(nested_dir))
        self.assertTrue(os.path.exists(img_path))

    def test_08_capture_evidence_invalid_bbox_fallback(self):
        """Test 8: Degenerate or empty bbox falls back gracefully to full frame crop."""
        event = create_mock_event(event_id="evt_evi_bad_bbox", worker_bbox=(0, 0, 0, 0))
        img_path = capture_evidence(
            event=event,
            frame=self.frame,
            output_dir=self.evidence_dir,
        )
        self.assertIsNotNone(img_path)
        self.assertTrue(os.path.exists(img_path))

    def test_09_capture_evidence_empty_frame(self):
        """Test 9: None or empty frame returns None safely without raising exceptions."""
        event = create_mock_event(event_id="evt_evi_bad_frame")
        self.assertIsNone(capture_evidence(event, None, self.evidence_dir))
        self.assertIsNone(capture_evidence(event, np.array([]), self.evidence_dir))

    def test_10_sanitize_filename(self):
        """Test 10: sanitize_filename removes unsafe path characters."""
        unsafe = "evt:123/45\\67*?\"<>|"
        safe = sanitize_filename(unsafe)
        self.assertNotIn(":", safe)
        self.assertNotIn("/", safe)
        self.assertNotIn("\\", safe)

    # ==========================================
    # Group 3: Telegram Alerting (Mocked)
    # ==========================================

    def test_11_telegram_disabled_by_default(self):
        """Test 11: Telegram disabled configuration skips network request."""
        tg = TelegramAlertManager(
            bot_token="fake_token",
            chat_id="12345",
            enabled=False,
        )
        event = create_mock_event(event_id="evt_tg_dis")
        status = tg.send_alert(event)
        self.assertEqual(status, TelegramAlertStatus.DISABLED)

    def test_12_telegram_missing_token_or_chat_id(self):
        """Test 12: Missing token or chat_id returns CREDENTIALS_MISSING when enabled."""
        tg = TelegramAlertManager(
            bot_token="",
            chat_id="",
            enabled=True,
        )
        event = create_mock_event(event_id="evt_tg_notok")
        status = tg.send_alert(event)
        self.assertEqual(status, TelegramAlertStatus.CREDENTIALS_MISSING)

    @patch("requests.post")
    def test_13_telegram_sends_photo_on_success(self, mock_post):
        """Test 13: Enabled Telegram sends photo alert via sendPhoto API."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": 999}}
        mock_post.return_value = mock_resp

        # Create dummy evidence file
        dummy_evidence = os.path.join(self.evidence_dir, "test_pic.jpg")
        os.makedirs(self.evidence_dir, exist_ok=True)
        cv2.imwrite(dummy_evidence, self.frame)

        tg = TelegramAlertManager(
            bot_token="dummy_token_123",
            chat_id="987654321",
            enabled=True,
            cooldown_seconds=60,
        )
        event = create_mock_event(event_id="evt_tg_ok")
        status = tg.send_alert(event, evidence_path=dummy_evidence)

        self.assertEqual(status, TelegramAlertStatus.SENT)
        self.assertTrue(mock_post.called)
        call_url = mock_post.call_args[0][0]
        self.assertIn("sendPhoto", call_url)

    @patch("requests.post")
    def test_14_telegram_cooldown_suppression(self, mock_post):
        """Test 14: Second alert within cooldown period is suppressed."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        tg = TelegramAlertManager(
            bot_token="dummy_token",
            chat_id="123456",
            enabled=True,
            cooldown_seconds=60,
        )
        event1 = create_mock_event(event_id="evt_cool_1", track_id=5, violation_type=ViolationType.MISSING_HELMET)
        event2 = create_mock_event(event_id="evt_cool_2", track_id=5, violation_type=ViolationType.MISSING_HELMET)

        status1 = tg.send_alert(event1, now=1000.0)
        self.assertEqual(status1, TelegramAlertStatus.SENT)

        status2 = tg.send_alert(event2, now=1020.0)
        self.assertEqual(status2, TelegramAlertStatus.SUPPRESSED_BY_COOLDOWN)
        self.assertEqual(mock_post.call_count, 1)

    @patch("requests.post")
    def test_15_telegram_cooldown_different_workers_or_types(self, mock_post):
        """Test 15: Different workers or different violation types do not block each other."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        tg = TelegramAlertManager(
            bot_token="dummy_token",
            chat_id="123456",
            enabled=True,
            cooldown_seconds=60,
        )
        event_w1 = create_mock_event(track_id=1, violation_type=ViolationType.MISSING_HELMET)
        event_w2 = create_mock_event(track_id=2, violation_type=ViolationType.MISSING_HELMET)
        event_w1_vest = create_mock_event(track_id=1, violation_type=ViolationType.MISSING_VEST)

        status1 = tg.send_alert(event_w1, now=1000.0)
        status2 = tg.send_alert(event_w2, now=1000.0)
        status3 = tg.send_alert(event_w1_vest, now=1000.0)

        self.assertEqual(status1, TelegramAlertStatus.SENT)
        self.assertEqual(status2, TelegramAlertStatus.SENT)
        self.assertEqual(status3, TelegramAlertStatus.SENT)
        self.assertEqual(mock_post.call_count, 3)

    @patch("requests.post")
    def test_16_telegram_photo_failure_falls_back_to_text(self, mock_post):
        """Test 16: If sendPhoto fails, TelegramAlertManager falls back to sendMessage."""
        dummy_evidence = os.path.join(self.evidence_dir, "test_pic.jpg")
        os.makedirs(self.evidence_dir, exist_ok=True)
        cv2.imwrite(dummy_evidence, self.frame)

        # Mock first post (photo) failing, second post (sendMessage) succeeding
        mock_fail = MagicMock()
        mock_fail.status_code = 500

        mock_ok = MagicMock()
        mock_ok.status_code = 200

        mock_post.side_effect = [mock_fail, mock_ok]

        tg = TelegramAlertManager(
            bot_token="dummy_token",
            chat_id="123456",
            enabled=True,
            cooldown_seconds=60,
        )
        event = create_mock_event(event_id="evt_fb_01")
        status = tg.send_alert(event, evidence_path=dummy_evidence)

        self.assertEqual(status, TelegramAlertStatus.SENT)
        self.assertEqual(mock_post.call_count, 2)
        fallback_call_url = mock_post.call_args_list[1][0][0]
        self.assertIn("sendMessage", fallback_call_url)

    # ==========================================
    # Group 4: Central ViolationHandler
    # ==========================================

    def test_17_handler_processes_confirmed_violation(self):
        """Test 17: Handler orchestrates Evidence + DB + Telegram for CONFIRMED events."""
        alert_mgr = TelegramAlertManager(enabled=False)
        handler = ViolationHandler(
            alert_manager=alert_mgr,
            db_path=self.db_path,
            evidence_dir=self.evidence_dir,
        )
        event = create_mock_event(event_id="evt_hdl_01", status=ViolationStatus.CONFIRMED)
        res = handler.handle_violation(event, frame=self.frame)

        self.assertTrue(res["processed"])
        self.assertTrue(res["db_saved"])
        self.assertIsNotNone(res["evidence_path"])
        self.assertTrue(os.path.exists(res["evidence_path"]))
        self.assertEqual(get_violation_count(self.db_path), 1)

    def test_18_handler_ignores_non_confirmed_violations(self):
        """Test 18: Handler ignores SUSPECTED, NORMAL, and RESOLVED status events."""
        alert_mgr = TelegramAlertManager(enabled=False)
        handler = ViolationHandler(
            alert_manager=alert_mgr,
            db_path=self.db_path,
            evidence_dir=self.evidence_dir,
        )
        for non_confirmed in [ViolationStatus.SUSPECTED, ViolationStatus.NORMAL, ViolationStatus.RESOLVED]:
            evt = create_mock_event(event_id=f"evt_{non_confirmed.value}", status=non_confirmed)
            res = handler.handle_violation(evt, frame=self.frame)
            self.assertFalse(res["processed"])
            self.assertFalse(res["db_saved"])
            self.assertIsNone(res["evidence_path"])

        self.assertEqual(get_violation_count(self.db_path), 0)

    def test_19_handler_idempotency_in_memory(self):
        """Test 19: Calling handle_violation twice with same event skips duplicate work."""
        alert_mgr = TelegramAlertManager(enabled=False)
        handler = ViolationHandler(
            alert_manager=alert_mgr,
            db_path=self.db_path,
            evidence_dir=self.evidence_dir,
        )
        event = create_mock_event(event_id="evt_hdl_idem")

        res1 = handler.handle_violation(event, frame=self.frame)
        self.assertTrue(res1["processed"])
        self.assertTrue(res1["db_saved"])

        res2 = handler.handle_violation(event, frame=self.frame)
        self.assertFalse(res2["processed"])
        self.assertEqual(res2["telegram_status"], "SKIPPED_DUPLICATE_EVENT")

    def test_20_handler_resilience_to_telegram_failure(self):
        """Test 20: Even if Telegram fails completely, DB and Evidence succeed."""
        with patch("requests.post", side_effect=Exception("Total network outage")):
            alert_mgr = TelegramAlertManager(
                bot_token="test_tok",
                chat_id="12345",
                enabled=True,
            )
            handler = ViolationHandler(
                alert_manager=alert_mgr,
                db_path=self.db_path,
                evidence_dir=self.evidence_dir,
            )
            event = create_mock_event(event_id="evt_hdl_netfail")
            res = handler.handle_violation(event, frame=self.frame)

            self.assertTrue(res["processed"])
            self.assertTrue(res["db_saved"])
            self.assertIsNotNone(res["evidence_path"])
            self.assertEqual(res["telegram_status"], TelegramAlertStatus.FAILED.value)
            self.assertEqual(get_violation_count(self.db_path), 1)

    def test_21_handler_resilience_to_missing_frame(self):
        """Test 21: Handler without frame still persists DB record (evidence_path is None)."""
        alert_mgr = TelegramAlertManager(enabled=False)
        handler = ViolationHandler(
            alert_manager=alert_mgr,
            db_path=self.db_path,
            evidence_dir=self.evidence_dir,
        )
        event = create_mock_event(event_id="evt_hdl_noframe")
        res = handler.handle_violation(event, frame=None)

        self.assertTrue(res["processed"])
        self.assertTrue(res["db_saved"])
        self.assertIsNone(res["evidence_path"])
        record = get_violation_by_id("evt_hdl_noframe", db_path=self.db_path)
        self.assertIsNotNone(record)
        self.assertEqual(record["evidence_path"], "")

    def test_22_handler_reset_clears_memory(self):
        """Test 22: handler.reset() clears processed events and telegram cooldowns."""
        alert_mgr = TelegramAlertManager(enabled=False)
        handler = ViolationHandler(
            alert_manager=alert_mgr,
            db_path=self.db_path,
            evidence_dir=self.evidence_dir,
        )
        event = create_mock_event(event_id="evt_reset")
        handler.handle_violation(event, frame=self.frame)
        self.assertIn("evt_reset", handler.processed_events)

        handler.reset()
        self.assertEqual(len(handler.processed_events), 0)
        self.assertEqual(len(handler.alert_manager.last_alert_time), 0)


if __name__ == "__main__":
    unittest.main()
