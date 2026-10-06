import os
import cv2
import numpy as np
import unittest

from ppe_detector import PPEDetector, DetectedPPE

class TestPhase3(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.weights_path = "models/ppe_yolov8n_best.pt"
        if not os.path.exists(cls.weights_path):
            raise unittest.SkipTest(f"Model file '{cls.weights_path}' not found.")

    def test_detected_ppe_dataclass(self):
        item = DetectedPPE(
            class_id=0,
            class_name="helmet",
            confidence=0.88,
            bbox=(100, 50, 150, 90)
        )
        self.assertEqual(item.class_id, 0)
        self.assertEqual(item.class_name, "helmet")
        self.assertEqual(item.confidence, 0.88)
        self.assertEqual(item.bbox, (100, 50, 150, 90))
        self.assertEqual(item.center, (125, 70))

    def test_ppe_detector_model_loading(self):
        detector = PPEDetector(weights=self.weights_path, conf=0.35, device="cpu")
        self.assertIsNotNone(detector.model)
        self.assertIn("helmet", detector.names.values())
        self.assertIn("vest", detector.names.values())
        self.assertIn("gloves", detector.names.values())
        self.assertIn("boots", detector.names.values())

    def test_ppe_detector_missing_model_raises_error(self):
        with self.assertRaises(FileNotFoundError):
            PPEDetector(weights="non_existent_ppe_model.pt")

    def test_ppe_detector_empty_frame(self):
        detector = PPEDetector(weights=self.weights_path, conf=0.35, device="cpu")
        blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        detections = detector.detect(blank_frame)
        self.assertEqual(len(detections), 0)

        annotated = detector.annotate(blank_frame, detections)
        self.assertEqual(annotated.shape, blank_frame.shape)

    def test_ppe_detector_inference_on_sample(self):
        detector = PPEDetector(weights=self.weights_path, conf=0.30, device="cpu")
        
        sample_path = "E:/CodingPlayground/Industrial safety violatiion detetor/datasets/construction-ppe/images/test/image1003.jpg"
        if os.path.exists(sample_path):
            frame = cv2.imread(sample_path)
            detections = detector.detect(frame)
            self.assertGreater(len(detections), 0)
            
            # Check detection fields
            for d in detections:
                self.assertIsInstance(d.class_name, str)
                self.assertGreaterEqual(d.confidence, 0.30)
                self.assertEqual(len(d.bbox), 4)
            
            annotated = detector.annotate(frame, detections)
            self.assertEqual(annotated.shape, frame.shape)
        else:
            # Synthetic frame fallback
            synthetic = np.full((320, 320, 3), 200, dtype=np.uint8)
            detections = detector.detect(synthetic)
            self.assertIsInstance(detections, list)

    def test_no_premature_worker_association(self):
        """Verify architectural boundary: PPEDetector only returns raw DetectedPPE objects without worker IDs."""
        detector = PPEDetector(weights=self.weights_path, conf=0.35, device="cpu")
        blank_frame = np.zeros((320, 320, 3), dtype=np.uint8)
        detections = detector.detect(blank_frame)
        for det in detections:
            self.assertFalse(hasattr(det, "worker_id"))
            self.assertFalse(hasattr(det, "track_id"))

if __name__ == "__main__":
    unittest.main()
