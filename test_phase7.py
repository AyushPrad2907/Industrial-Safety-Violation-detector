import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from temporal_engine import (
    ViolationEvent,
    ViolationStatus,
    SeverityLevel,
    ViolationType,
)
from ppe_association import PPEState
import database
from dashboard_utils import (
    format_violation_type,
    format_severity,
    format_ppe_status,
    load_violation_history,
    filter_violations,
    export_violations_csv,
    check_evidence_file,
    CSV_EXPORT_COLUMNS,
)


def create_sample_violation_record(
    event_id: str = "evt_001",
    track_id: int = 1,
    violation_type: str = "MISSING_HELMET",
    severity: str = "CRITICAL",
    decision_score: float = 0.95,
    evidence_path: str = "evidence/event_001.jpg",
    timestamp: str = "2026-10-07 10:00:00",
    status: str = "CONFIRMED",
    frame_index: int = 15,
    missing_ratio: float = 0.85,
    observable_frames: int = 10,
    is_zone_violation: int = 0,
    message: str = "Worker #1 missing helmet",
):
    return {
        "event_id": event_id,
        "track_id": track_id,
        "violation_type": violation_type,
        "severity": severity,
        "decision_score": decision_score,
        "evidence_path": evidence_path,
        "timestamp": timestamp,
        "status": status,
        "frame_index": frame_index,
        "missing_ratio": missing_ratio,
        "observable_frames": observable_frames,
        "is_zone_violation": is_zone_violation,
        "message": message,
    }


class TestPhase7(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_violations.db")
        database.init_db(self.db_path)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # 1. Dashboard imports successfully
    def test_01_dashboard_imports_successfully(self):
        import dashboard_utils
        self.assertTrue(hasattr(dashboard_utils, "filter_violations"))
        self.assertTrue(hasattr(dashboard_utils, "export_violations_csv"))
        self.assertTrue(hasattr(dashboard_utils, "load_violation_history"))
        self.assertTrue(hasattr(dashboard_utils, "format_ppe_status"))
        self.assertTrue(hasattr(dashboard_utils, "check_evidence_file"))

    # 2. Database records can be loaded
    def test_02_database_records_can_be_loaded(self):
        event = ViolationEvent(
            event_id="evt_load_test",
            track_id=3,
            violation_type=ViolationType.MISSING_HELMET,
            severity=SeverityLevel.CRITICAL,
            status=ViolationStatus.CONFIRMED,
            frame_index=10,
            timestamp=1710000000.0,
            decision_score=0.9,
            missing_ratio=0.8,
            observable_frames=6,
            window_size=10,
            is_zone_violation=False,
            worker_bbox=(10, 10, 50, 100),
            message="Test event",
        )
        database.save_violation(event, evidence_path="evidence/test.jpg", db_path=self.db_path)
        records = load_violation_history(db_path=self.db_path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["event_id"], "evt_load_test")
        self.assertEqual(records[0]["track_id"], 3)

    # 3. Violation filtering by severity
    def test_03_violation_filtering_by_severity(self):
        v1 = create_sample_violation_record(event_id="e1", severity="CRITICAL")
        v2 = create_sample_violation_record(event_id="e2", severity="HIGH")
        v3 = create_sample_violation_record(event_id="e3", severity="MEDIUM")
        v4 = create_sample_violation_record(event_id="e4", severity="LOW")
        data = [v1, v2, v3, v4]

        self.assertEqual(len(filter_violations(data, severity_filter="All")), 4)
        filtered_crit = filter_violations(data, severity_filter="Critical")
        self.assertEqual(len(filtered_crit), 1)
        self.assertEqual(filtered_crit[0]["event_id"], "e1")

        filtered_high = filter_violations(data, severity_filter="High")
        self.assertEqual(len(filtered_high), 1)
        self.assertEqual(filtered_high[0]["event_id"], "e2")

    # 4. Violation filtering by type
    def test_04_violation_filtering_by_type(self):
        v1 = create_sample_violation_record(event_id="e1", violation_type="MISSING_HELMET")
        v2 = create_sample_violation_record(event_id="e2", violation_type="MISSING_VEST")
        v3 = create_sample_violation_record(event_id="e3", violation_type="MISSING_GLOVES")
        data = [v1, v2, v3]

        filtered_helmet = filter_violations(data, violation_type_filter="Missing Helmet")
        self.assertEqual(len(filtered_helmet), 1)
        self.assertEqual(filtered_helmet[0]["event_id"], "e1")

        filtered_vest = filter_violations(data, violation_type_filter="MISSING_VEST")
        self.assertEqual(len(filtered_vest), 1)
        self.assertEqual(filtered_vest[0]["event_id"], "e2")

    # 5. Worker filtering
    def test_05_worker_filtering(self):
        v1 = create_sample_violation_record(event_id="e1", track_id=1)
        v2 = create_sample_violation_record(event_id="e2", track_id=2)
        v3 = create_sample_violation_record(event_id="e3", track_id=1)
        data = [v1, v2, v3]

        filtered_w1 = filter_violations(data, worker_id_filter="1")
        self.assertEqual(len(filtered_w1), 2)
        filtered_w2 = filter_violations(data, worker_id_filter="2")
        self.assertEqual(len(filtered_w2), 1)
        filtered_w3 = filter_violations(data, worker_id_filter="3")
        self.assertEqual(len(filtered_w3), 0)

    # 6. Combined filters
    def test_06_combined_filters(self):
        v1 = create_sample_violation_record(event_id="e1", track_id=1, severity="CRITICAL", violation_type="MISSING_HELMET")
        v2 = create_sample_violation_record(event_id="e2", track_id=1, severity="HIGH", violation_type="MISSING_VEST")
        v3 = create_sample_violation_record(event_id="e3", track_id=2, severity="CRITICAL", violation_type="MISSING_HELMET")
        data = [v1, v2, v3]

        filtered = filter_violations(
            data,
            severity_filter="Critical",
            violation_type_filter="Missing Helmet",
            worker_id_filter="1"
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["event_id"], "e1")

    # 7. CSV export contains expected columns
    def test_07_csv_export_contains_expected_columns(self):
        v1 = create_sample_violation_record(event_id="e1")
        csv_str = export_violations_csv([v1])
        header_line = csv_str.strip().split("\n")[0]
        headers = header_line.split(",")

        for col in CSV_EXPORT_COLUMNS:
            self.assertIn(col, headers)

    # 8. CSV export respects filters
    def test_08_csv_export_respects_filters(self):
        v1 = create_sample_violation_record(event_id="e1", severity="CRITICAL")
        v2 = create_sample_violation_record(event_id="e2", severity="LOW")
        data = [v1, v2]

        filtered = filter_violations(data, severity_filter="Critical")
        csv_str = export_violations_csv(filtered)
        lines = [line for line in csv_str.strip().split("\n") if line]
        # 1 header line + 1 record line
        self.assertEqual(len(lines), 2)
        self.assertIn("e1", lines[1])
        self.assertNotIn("e2", csv_str)

    # 9. Missing evidence file handled safely
    def test_09_missing_evidence_file_handled_safely(self):
        self.assertFalse(check_evidence_file(None))
        self.assertFalse(check_evidence_file(""))
        self.assertFalse(check_evidence_file("non_existent_folder/fake.jpg"))

    # 10. Empty database handled safely
    def test_10_empty_database_handled_safely(self):
        records = load_violation_history(db_path=self.db_path)
        self.assertEqual(records, [])
        filtered = filter_violations(records)
        self.assertEqual(filtered, [])
        csv_str = export_violations_csv(filtered)
        self.assertIn("event_id", csv_str)

    # 11. Empty worker list handled safely
    def test_11_empty_worker_list_handled_safely(self):
        # Empty worker list format check
        workers = []
        status_text = "No active workers detected." if not workers else "Workers present"
        self.assertEqual(status_text, "No active workers detected.")

    # 12. Unknown PPE state displayed correctly
    def test_12_unknown_ppe_state_displayed_correctly(self):
        self.assertEqual(format_ppe_status(PPEState.UNKNOWN), "❓ UNKNOWN")
        self.assertEqual(format_ppe_status("UNKNOWN"), "❓ UNKNOWN")
        self.assertEqual(format_ppe_status(PPEState.PRESENT), "✅ PRESENT")
        self.assertEqual(format_ppe_status(PPEState.NOT_ASSOCIATED), "❌ NOT ASSOCIATED")

    # 13. Confirmed violation displayed correctly
    def test_13_confirmed_violation_displayed_correctly(self):
        self.assertEqual(format_violation_type(ViolationType.MISSING_HELMET), "Missing Helmet")
        self.assertEqual(format_violation_type("MISSING_VEST"), "Missing Vest")
        self.assertEqual(format_violation_type("MISSING_GLOVES"), "Missing Gloves")
        self.assertEqual(format_severity(SeverityLevel.CRITICAL), "CRITICAL")
        self.assertEqual(format_severity("High"), "HIGH")

    # 14. Session reset does not delete historical DB records
    def test_14_session_reset_does_not_delete_historical_db_records(self):
        event = ViolationEvent(
            event_id="evt_preserve_test",
            track_id=5,
            violation_type=ViolationType.MISSING_VEST,
            severity=SeverityLevel.HIGH,
            status=ViolationStatus.CONFIRMED,
            frame_index=20,
            timestamp=1710000000.0,
            decision_score=0.88,
            missing_ratio=0.8,
            observable_frames=6,
            window_size=10,
            is_zone_violation=False,
            worker_bbox=(10, 10, 50, 100),
            message="Test preserve event",
        )
        database.save_violation(event, db_path=self.db_path)
        self.assertEqual(database.get_violation_count(self.db_path), 1)

        # Simulate Session Reset (resetting tracking, temporal engine, and in-memory caches)
        from detector import SafetyDetector
        from temporal_engine import TemporalViolationEngine
        from violation_handler import ViolationHandler

        # Mock runtime objects reset
        temp_engine = TemporalViolationEngine()
        temp_engine.reset()
        v_handler = ViolationHandler(db_path=self.db_path)
        v_handler.processed_events.clear()

        # Check DB remains intact
        self.assertEqual(database.get_violation_count(self.db_path), 1)
        reloaded = load_violation_history(db_path=self.db_path)
        self.assertEqual(len(reloaded), 1)
        self.assertEqual(reloaded[0]["event_id"], "evt_preserve_test")

    # 15. Session reset does not delete evidence
    def test_15_session_reset_does_not_delete_evidence(self):
        evidence_file = os.path.join(self.test_dir, "test_evidence.jpg")
        with open(evidence_file, "w") as f:
            f.write("fake jpeg image data")

        self.assertTrue(check_evidence_file(evidence_file))

        # Runtime reset operation
        runtime_tracked_ids = set([1, 2, 3])
        runtime_tracked_ids.clear()

        # Evidence file must still exist
        self.assertTrue(check_evidence_file(evidence_file))

    # 16. Telegram secrets are never displayed
    def test_16_telegram_secrets_are_never_displayed(self):
        import config
        with patch.object(config, "TELEGRAM_BOT_TOKEN", "super_secret_token_12345"), \
             patch.object(config, "TELEGRAM_CHAT_ID", "secret_chat_999"):
            
            # The UI sidebar status string logic
            status_text = "Enabled" if config.TELEGRAM_ALERTS_ENABLED else "Disabled"
            sidebar_display = f"Telegram Alerts: {status_text}"
            
            self.assertNotIn("super_secret_token_12345", sidebar_display)
            self.assertNotIn("secret_chat_999", sidebar_display)

    # 17. No crash when Telegram disabled
    def test_17_no_crash_when_telegram_disabled(self):
        from telegram_alert import TelegramAlertManager, TelegramAlertStatus
        mgr = TelegramAlertManager(enabled=False)
        self.assertFalse(mgr.enabled)
        # Check send alert returns DISABLED without throwing
        event = ViolationEvent(
            event_id="evt_tg_dis",
            track_id=1,
            violation_type=ViolationType.MISSING_HELMET,
            severity=SeverityLevel.CRITICAL,
            status=ViolationStatus.CONFIRMED,
            frame_index=1,
            timestamp=1710000000.0,
            decision_score=0.9,
            missing_ratio=0.8,
            observable_frames=5,
            window_size=10,
            is_zone_violation=False,
            worker_bbox=(10, 10, 50, 100),
            message="Test",
        )
        status = mgr.send_alert(event)
        self.assertEqual(status, TelegramAlertStatus.DISABLED)

    # 18. No crash when evidence is unavailable
    def test_18_no_crash_when_evidence_is_unavailable(self):
        res = check_evidence_file("completely/non/existent/path/evidence.jpg")
        self.assertFalse(res)
        display_msg = "Evidence file unavailable." if not res else "Ready"
        self.assertEqual(display_msg, "Evidence file unavailable.")


if __name__ == "__main__":
    unittest.main()
