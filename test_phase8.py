import os
import shutil
import tempfile
import unittest
import numpy as np
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app
import database
import config
from temporal_engine import (
    ViolationEvent,
    ViolationStatus,
    SeverityLevel,
    ViolationType,
)
from backend.services.monitoring_service import monitoring_service

class TestPhase8(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_violations.db")
        self.evidence_dir = os.path.join(self.test_dir, "evidence")
        os.makedirs(self.evidence_dir, exist_ok=True)
        database.init_db(self.db_path)

        # Patch DATABASE_PATH and EVIDENCE_DIR
        self.db_patch = patch.object(config, "DATABASE_PATH", self.db_path)
        self.evi_patch = patch.object(config, "EVIDENCE_DIR", self.evidence_dir)
        self.db_patch.start()
        self.evi_patch.start()

        self.client = TestClient(app)

    def tearDown(self):
        self.db_patch.stop()
        self.evi_patch.stop()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # 1. FastAPI app imports
    def test_01_fastapi_app_imports(self):
        from backend.main import app as imported_app
        self.assertIsNotNone(imported_app)
        self.assertEqual(imported_app.title, "Industrial Safety Violation Detector API")

    # 2. /api/health
    def test_02_api_health(self):
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("database", data)
        self.assertIn("pipeline_state", data)

    # 3. /api/stats
    def test_03_api_stats(self):
        res = self.client.get("/api/stats")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("fps", data)
        self.assertIn("frame_index", data)
        self.assertIn("active_workers", data)
        self.assertIn("total_violations", data)
        self.assertIn("critical_violations", data)

    # 4. /api/workers
    def test_04_api_workers(self):
        res = self.client.get("/api/workers")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)

    # 5. /api/violations
    def test_05_api_violations(self):
        event = ViolationEvent(
            event_id="evt_test_p8_01",
            track_id=1,
            violation_type=ViolationType.MISSING_HELMET,
            severity=SeverityLevel.CRITICAL,
            status=ViolationStatus.CONFIRMED,
            frame_index=10,
            timestamp=1710000000.0,
            decision_score=0.92,
            missing_ratio=0.85,
            observable_frames=6,
            window_size=10,
            is_zone_violation=False,
            worker_bbox=(10, 10, 50, 100),
            message="Worker #1 missing helmet",
        )
        database.save_violation(event, evidence_path="evidence/dummy.jpg", db_path=self.db_path)

        res = self.client.get("/api/violations")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(len(data["violations"]), 1)
        self.assertEqual(data["violations"][0]["event_id"], "evt_test_p8_01")
        self.assertEqual(data["violations"][0]["severity"], "CRITICAL")

    # 6. violation detail endpoint
    def test_06_violation_detail_endpoint(self):
        event = ViolationEvent(
            event_id="evt_test_p8_02",
            track_id=2,
            violation_type=ViolationType.MISSING_VEST,
            severity=SeverityLevel.HIGH,
            status=ViolationStatus.CONFIRMED,
            frame_index=15,
            timestamp=1710000000.0,
            decision_score=0.88,
            missing_ratio=0.75,
            observable_frames=5,
            window_size=10,
            is_zone_violation=False,
            worker_bbox=(10, 10, 50, 100),
            message="Worker #2 missing vest",
        )
        database.save_violation(event, db_path=self.db_path)

        res = self.client.get("/api/violations/evt_test_p8_02")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["event_id"], "evt_test_p8_02")
        self.assertEqual(data["violation_type"], "Missing Vest")

    # 7. invalid violation ID handling
    def test_07_invalid_violation_id_handling(self):
        res = self.client.get("/api/violations/non_existent_id")
        self.assertEqual(res.status_code, 404)
        self.assertIn("not found", res.json()["detail"].lower())

    # 8. evidence missing-file handling
    def test_08_evidence_missing_file_handling(self):
        event = ViolationEvent(
            event_id="evt_test_p8_03",
            track_id=3,
            violation_type=ViolationType.MISSING_BOOTS,
            severity=SeverityLevel.MEDIUM,
            status=ViolationStatus.CONFIRMED,
            frame_index=20,
            timestamp=1710000000.0,
            decision_score=0.80,
            missing_ratio=0.70,
            observable_frames=5,
            window_size=10,
            is_zone_violation=False,
            worker_bbox=(10, 10, 50, 100),
            message="Worker #3 missing boots",
        )
        # Point to missing file
        database.save_violation(event, evidence_path=os.path.join(self.evidence_dir, "missing.jpg"), db_path=self.db_path)

        res = self.client.get("/api/evidence/evt_test_p8_03")
        self.assertEqual(res.status_code, 404)
        self.assertIn("unavailable", res.json()["detail"].lower())

    # 9. path traversal protection
    def test_09_path_traversal_protection(self):
        event = ViolationEvent(
            event_id="evt_test_p8_traversal",
            track_id=4,
            violation_type=ViolationType.MISSING_GLOVES,
            severity=SeverityLevel.MEDIUM,
            status=ViolationStatus.CONFIRMED,
            frame_index=25,
            timestamp=1710000000.0,
            decision_score=0.80,
            missing_ratio=0.70,
            observable_frames=5,
            window_size=10,
            is_zone_violation=False,
            worker_bbox=(10, 10, 50, 100),
            message="Test traversal",
        )
        # Attempt to target sensitive file outside evidence_dir
        database.save_violation(event, evidence_path=os.path.abspath("config.py"), db_path=self.db_path)

        res = self.client.get("/api/evidence/evt_test_p8_traversal")
        self.assertEqual(res.status_code, 403)
        self.assertIn("forbidden", res.json()["detail"].lower())

    # 10. session reset endpoint
    def test_10_session_reset_endpoint(self):
        # Save historical violation first
        event = ViolationEvent(
            event_id="evt_test_p8_reset",
            track_id=5,
            violation_type=ViolationType.MISSING_HELMET,
            severity=SeverityLevel.CRITICAL,
            status=ViolationStatus.CONFIRMED,
            frame_index=30,
            timestamp=1710000000.0,
            decision_score=0.90,
            missing_ratio=0.80,
            observable_frames=5,
            window_size=10,
            is_zone_violation=False,
            worker_bbox=(10, 10, 50, 100),
            message="Preserved violation",
        )
        database.save_violation(event, db_path=self.db_path)

        res = self.client.post("/api/session/reset")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["preserved_records"], 1)

        # Historical DB record survives reset
        count = database.get_violation_count(self.db_path)
        self.assertEqual(count, 1)

    # 11. WebSocket connection
    def test_11_websocket_connection(self):
        with self.client.websocket_connect("/ws/monitor") as websocket:
            websocket.send_text("ping")
            data = websocket.receive_text()
            self.assertEqual(data, "pong")

    # 12. WebSocket violation event structure
    def test_12_websocket_violation_event_structure(self):
        from backend.services.alert_service import alert_service
        import asyncio

        test_payload = {
            "type": "violation_confirmed",
            "data": {
                "event_id": "evt_ws_test",
                "track_id": 3,
                "violation_type": "Missing Helmet",
                "severity": "CRITICAL",
                "decision_score": 0.95,
                "missing_ratio": 0.85,
                "timestamp": "2026-10-07 10:00:00",
                "evidence_path": "evidence/evt_ws_test.jpg"
            }
        }

        with self.client.websocket_connect("/ws/monitor") as websocket:
            # Broadcast payload via alert_service
            asyncio.run(alert_service.broadcast(test_payload))
            received = websocket.receive_json()
            self.assertEqual(received["type"], "violation_confirmed")
            self.assertEqual(received["data"]["event_id"], "evt_ws_test")
            self.assertEqual(received["data"]["track_id"], 3)
            self.assertEqual(received["data"]["severity"], "CRITICAL")

    # 13. WebSocket disconnect safety
    def test_13_websocket_disconnect_safety(self):
        from backend.services.alert_service import alert_service
        initial_count = len(alert_service.active_connections)

        with self.client.websocket_connect("/ws/monitor") as websocket:
            self.assertEqual(len(alert_service.active_connections), initial_count + 1)

        # After exiting context manager, client is disconnected
        self.assertEqual(len(alert_service.active_connections), initial_count)

    # 14. event_id deduplication
    def test_14_event_id_deduplication(self):
        from violation_handler import ViolationHandler
        vh = ViolationHandler(db_path=self.db_path)
        event = ViolationEvent(
            event_id="evt_dedup_01",
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
            message="Test dedup",
        )
        dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        res1 = vh.handle_violation(event, dummy_frame)
        self.assertTrue(res1["processed"])

        # Second attempt with same event_id must be debounced/deduplicated
        res2 = vh.handle_violation(event, dummy_frame)
        self.assertFalse(res2["processed"])
        self.assertIn("already been processed", res2["reason"].lower())

    # 15. secret protection
    def test_15_secret_protection(self):
        with patch.object(config, "TELEGRAM_BOT_TOKEN", "confidential_token_999"), \
             patch.object(config, "TELEGRAM_CHAT_ID", "secret_chat_123"):
            res = self.client.get("/api/status")
            self.assertEqual(res.status_code, 200)
            text_body = res.text
            self.assertNotIn("confidential_token_999", text_body)
            self.assertNotIn("secret_chat_123", text_body)

    # 16. CSV export endpoint
    def test_16_csv_export_endpoint(self):
        event = ViolationEvent(
            event_id="evt_csv_export",
            track_id=7,
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
            message="CSV Test",
        )
        database.save_violation(event, db_path=self.db_path)

        res = self.client.get("/api/violations/export/csv")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res.headers["content-type"])
        self.assertIn("evt_csv_export", res.text)
        self.assertIn("MISSING_HELMET", res.text)

if __name__ == "__main__":
    import numpy as np
    unittest.main()
