import os
import cv2
import numpy as np
import unittest

from tracker import TrackedWorker
from detector import SafetyDetector

class TestPhase2(unittest.TestCase):

    def test_tracked_worker_dataclass(self):
        worker = TrackedWorker(
            track_id=1,
            bbox=(50, 100, 150, 300),
            confidence=0.88,
            is_zone_violation=False
        )
        self.assertEqual(worker.track_id, 1)
        self.assertEqual(worker.bbox, (50, 100, 150, 300))
        self.assertEqual(worker.foot_point, (100, 300))
        self.assertFalse(worker.is_zone_violation)

    def test_detector_initialization_and_person_class(self):
        detector = SafetyDetector(weights="yolov8n.pt", conf=0.3)
        self.assertEqual(detector.person_class_id, 0)
        self.assertIn("person", detector.model.names.values())

    def test_detector_missing_model_raises_error(self):
        with self.assertRaises(FileNotFoundError):
            SafetyDetector(weights="non_existent_model.pt")

    def test_detector_process_empty_frame(self):
        detector = SafetyDetector(weights="yolov8n.pt", conf=0.4)
        blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        
        annotated_frame, violations, workers = detector.process(blank_frame)
        self.assertEqual(annotated_frame.shape, (480, 640, 3))
        self.assertEqual(len(violations), 0)
        self.assertEqual(len(workers), 0)
        self.assertEqual(len(detector.unique_track_ids), 0)

    def test_detector_reset_tracking(self):
        detector = SafetyDetector(weights="yolov8n.pt", conf=0.4)
        detector.unique_track_ids.add(1)
        detector.unique_track_ids.add(2)
        detector.last_alert_time["Zone Intrusion"] = 12345.0

        detector.reset_tracking()
        self.assertEqual(len(detector.unique_track_ids), 0)
        self.assertEqual(len(detector.last_alert_time), 0)

    def test_zone_polygon_intrusion_detection(self):
        # Configure a zone that covers the center
        zone = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]
        detector = SafetyDetector(weights="yolov8n.pt", zone=zone, conf=0.4)
        self.assertIsNotNone(detector.zone)

if __name__ == "__main__":
    unittest.main()
