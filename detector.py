import os
import cv2
import time
import numpy as np
from datetime import datetime
from typing import List, Tuple, Optional, Set
from ultralytics import YOLO

from config import EVIDENCE_DIR
from tracker import TrackedWorker

os.makedirs(EVIDENCE_DIR, exist_ok=True)

class SafetyDetector:
    """
    Handles person detection and persistent worker tracking using ByteTrack,
    with restricted-zone intrusion checking and cooldown evidence logging.
    """

    def __init__(self, weights: str = "yolov8n.pt", zone: Optional[List[Tuple[float, float]]] = None, conf: float = 0.4, cooldown: int = 10):
        self.weights = weights
        self.zone = zone            # list of (x, y) normalized vertices (0.0 - 1.0)
        self.conf = conf
        self.cooldown = cooldown
        self.last_alert_time = {}

        # Tracking state
        self.unique_track_ids: Set[int] = set()

        # Load YOLO model
        if not os.path.exists(weights):
            raise FileNotFoundError(f"Model file '{weights}' does not exist.")
        self.model = YOLO(weights)

        # Detect class ID for 'person' (defaults to 0 for standard COCO models)
        self.person_class_id = 0
        for cls_id, cls_name in self.model.names.items():
            if cls_name.lower() == "person":
                self.person_class_id = int(cls_id)
                break

    def reset_tracking(self):
        """Resets session-level tracking state and ByteTrack internal buffers."""
        self.unique_track_ids.clear()
        self.last_alert_time.clear()
        if hasattr(self.model, "predictor") and self.model.predictor is not None:
            if hasattr(self.model.predictor, "trackers"):
                self.model.predictor.trackers = None

    def process(self, frame: np.ndarray) -> Tuple[np.ndarray, List[Tuple[str, float, str]], List[TrackedWorker]]:
        """
        Processes a single frame:
        1. Tracks persons using ByteTrack.
        2. Evaluates restricted-zone intrusion.
        3. Annotates bounding boxes, Worker IDs, and confidence scores.
        4. Logs cooldown evidence snapshots.

        Returns:
            annotated_frame: np.ndarray
            new_violations: List[Tuple[violation_name, confidence, evidence_image_path]]
            tracked_workers: List[TrackedWorker]
        """
        h, w = frame.shape[:2]
        poly = None
        if self.zone:
            poly = np.array([(int(x * w), int(y * h)) for x, y in self.zone], np.int32)
            cv2.polylines(frame, [poly], isClosed=True, color=(0, 165, 255), thickness=2)

        # Run ByteTrack tracking with person class filtering
        results = self.model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=[self.person_class_id],
            conf=self.conf,
            verbose=False
        )

        tracked_workers: List[TrackedWorker] = []
        violations_in_frame: List[Tuple[str, float]] = []

        if results and len(results) > 0 and results[0].boxes is not None:
            boxes = results[0].boxes
            for b in boxes:
                # Extract coordinates and confidence
                x1, y1, x2, y2 = map(int, b.xyxy[0])
                c = float(b.conf[0])

                # Extract track ID if assigned by ByteTrack
                track_id = int(b.id[0]) if (b.id is not None and len(b.id) > 0) else -1
                if track_id != -1:
                    self.unique_track_ids.add(track_id)

                # Check restricted zone intrusion
                is_zone_intruded = False
                if poly is not None:
                    foot_point = ((x1 + x2) // 2, y2)
                    if cv2.pointPolygonTest(poly, foot_point, False) >= 0:
                        is_zone_intruded = True
                        violations_in_frame.append(("Zone Intrusion", c))

                worker = TrackedWorker(
                    track_id=track_id,
                    bbox=(x1, y1, x2, y2),
                    confidence=c,
                    is_zone_violation=is_zone_intruded
                )
                tracked_workers.append(worker)

                # Color: Red if zone violation, else Green
                color = (0, 0, 255) if is_zone_intruded else (0, 200, 0)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

                # Worker ID and Confidence Label
                if track_id != -1:
                    label = f"Worker #{track_id} ({c:.2f})"
                else:
                    label = f"Person ({c:.2f})"

                if is_zone_intruded:
                    label += " [Zone Intrusion]"

                # Text banner background for clarity
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
                label_y = max(y1 - 6, 15)
                cv2.rectangle(frame, (x1, label_y - th - 4), (x1 + tw + 4, label_y + 2), color, -1)
                cv2.putText(frame, label, (x1 + 2, label_y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

        # Handle cooldown and evidence persistence for violations
        new_violations = []
        now = time.time()
        for vname, c in violations_in_frame:
            if now - self.last_alert_time.get(vname, 0) > self.cooldown:
                self.last_alert_time[vname] = now
                filename = f"{vname.replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M%S}.jpg"
                path = os.path.join(EVIDENCE_DIR, filename)
                cv2.imwrite(path, frame)
                new_violations.append((vname, c, path))

        return frame, new_violations, tracked_workers
