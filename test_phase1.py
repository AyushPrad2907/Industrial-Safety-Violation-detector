import os
import cv2
import numpy as np
import tempfile
import unittest
from unittest.mock import patch

from zone_utils import parse_zone_polygon
from video_source import VideoSourceHandler
import config
import db
import alerts

class MockUploadedFile:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getbuffer(self):
        return self._data

class TestPhase1(unittest.TestCase):

    def test_zone_parsing_valid(self):
        zone_str = "0.6,0.2;0.95,0.2;0.95,0.9;0.6,0.9"
        points, err = parse_zone_polygon(zone_str)
        self.assertIsNone(err)
        self.assertEqual(len(points), 4)
        self.assertEqual(points[0], (0.6, 0.2))

    def test_zone_parsing_invalid(self):
        # Empty
        points, err = parse_zone_polygon("")
        self.assertIsNotNone(err)

        # Insufficient vertices
        points, err = parse_zone_polygon("0.1,0.2;0.3,0.4")
        self.assertIn("at least 3 vertices", err)

        # Non-numeric
        points, err = parse_zone_polygon("0.1,abc;0.3,0.4;0.5,0.6")
        self.assertIn("non-numeric", err)

        # Out of bounds
        points, err = parse_zone_polygon("1.5,0.2;0.3,0.4;0.5,0.6")
        self.assertIn("between 0.0 and 1.0", err)

    def test_video_source_webcam_invalid_index(self):
        handler = VideoSourceHandler(src_type="Webcam", webcam_index=999)
        cap, err = handler.open()
        self.assertIsNone(cap)
        self.assertIn("Unable to access Webcam", err)
        handler.cleanup()

    def test_video_source_rtsp_empty(self):
        handler = VideoSourceHandler(src_type="RTSP / URL", stream_url="")
        cap, err = handler.open()
        self.assertIsNone(cap)
        self.assertEqual(err, "Stream URL cannot be empty.")
        handler.cleanup()

    def test_video_source_upload_and_cleanup(self):
        # Create a tiny dummy video in memory
        temp_raw = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        temp_raw_path = temp_raw.name
        temp_raw.close()

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_raw_path, fourcc, 10.0, (160, 120))
        for _ in range(5):
            frame = np.zeros((120, 160, 3), dtype=np.uint8)
            out.write(frame)
        out.release()

        with open(temp_raw_path, "rb") as f:
            data = f.read()
        os.remove(temp_raw_path)

        mock_file = MockUploadedFile("test_sample.mp4", data)
        handler = VideoSourceHandler(src_type="Upload video", uploaded_file=mock_file)
        cap, err = handler.open()
        
        self.assertIsNone(err)
        self.assertIsNotNone(cap)
        self.assertTrue(cap.isOpened())
        ret, frame = cap.read()
        self.assertTrue(ret)
        self.assertEqual(frame.shape, (120, 160, 3))

        created_temp = handler.temp_file_path
        self.assertTrue(os.path.exists(created_temp))

        # Cleanup test
        handler.cleanup()
        self.assertFalse(os.path.exists(created_temp))

    def test_database_logging_and_history(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            temp_db = tmp.name
        try:
            with patch.object(config, "DATABASE_PATH", temp_db), \
                 patch.object(config, "DB_PATH", temp_db), \
                 patch.object(db, "DB_PATH", temp_db):
                db.log("2026-10-06 12:00:00", "Cam-Test", "TestViolation", 0.95, "evidence/test.jpg")
                df = db.history()
                self.assertFalse(df.empty)
                row = df.iloc[0]
                self.assertEqual(row["camera"], "Cam-Test")
                self.assertEqual(row["type"], "TestViolation")
        finally:
            if os.path.exists(temp_db):
                try:
                    os.remove(temp_db)
                except OSError:
                    pass

    def test_alerts_without_token(self):
        # Should gracefully return False if credentials are blank or unset
        res = alerts.send_telegram("Test alert")
        self.assertFalse(res)

if __name__ == "__main__":
    unittest.main()
