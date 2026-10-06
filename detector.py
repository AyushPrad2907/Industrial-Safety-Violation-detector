import cv2, os, time, numpy as np
from datetime import datetime
from ultralytics import YOLO
from config import EVIDENCE_DIR

os.makedirs(EVIDENCE_DIR, exist_ok=True)

class SafetyDetector:
    """Detects PPE violations (classes like 'NO-Hardhat', 'NO-Safety Vest')
    and restricted-zone intrusion (class 'Person' inside a polygon)."""

    def __init__(self, weights="best.pt", zone=None, conf=0.4, cooldown=10):
        self.model = YOLO(weights)
        self.zone = zone            # list of (x, y) as fractions 0-1, or None
        self.conf, self.cooldown = conf, cooldown
        self.last = {}

    @staticmethod
    def _is_violation(name):
        n = name.lower()
        return n.startswith(("no-", "no_", "no "))

    def process(self, frame):
        h, w = frame.shape[:2]
        poly = None
        if self.zone:
            poly = np.array([(int(x * w), int(y * h)) for x, y in self.zone], np.int32)
            cv2.polylines(frame, [poly], True, (0, 165, 255), 2)
        r = self.model(frame, conf=self.conf, verbose=False)[0]
        found = []
        for b in r.boxes:
            name = r.names[int(b.cls)]
            x1, y1, x2, y2 = map(int, b.xyxy[0])
            c = float(b.conf)
            bad = self._is_violation(name)
            if poly is not None and name.lower() == "person":
                if cv2.pointPolygonTest(poly, ((x1 + x2) // 2, y2), False) >= 0:
                    name, bad = "Zone Intrusion", True
            color = (0, 0, 255) if bad else (0, 200, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, f"{name} {c:.2f}", (x1, max(y1 - 6, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            if bad:
                found.append((name, c))
        # cooldown so one violation doesn't spam alerts
        new, now = [], time.time()
        for name, c in found:
            if now - self.last.get(name, 0) > self.cooldown:
                self.last[name] = now
                filename = f"{name.replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M%S}.jpg"
                path = os.path.join(EVIDENCE_DIR, filename)
                cv2.imwrite(path, frame)
                new.append((name, c, path))
        return frame, new
