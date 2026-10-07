import os
import cv2
import numpy as np
from dataclasses import dataclass
from typing import Tuple, List, Optional
from ultralytics import YOLO

@dataclass
class DetectedPPE:
    """
    Represents an independently detected Personal Protective Equipment (PPE) item
    or related object in a video frame.
    
    NOTE: As per Phase 3 architectural boundary, this detection is decoupled
    from worker identities. Worker <-> PPE association is explicitly deferred to Phase 4.
    """
    class_id: int
    class_name: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2)

    @property
    def center(self) -> Tuple[int, int]:
        """Returns the center coordinate of the bounding box."""
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) // 2, (y1 + y2) // 2)

# Color mapping for PPE classes (BGR format for OpenCV)
PPE_CLASS_COLORS = {
    "helmet": (0, 255, 255),       # Yellow
    "gloves": (255, 191, 0),       # Deep sky blue / Cyan
    "vest": (0, 165, 255),         # Orange
    "boots": (147, 20, 255),       # Deep Pink
    "goggles": (255, 0, 255),      # Magenta
    "person": (0, 200, 0),         # Green
    "none": (128, 128, 128),       # Grey
    "no_helmet": (0, 0, 255),      # Red
    "no_goggle": (0, 0, 220),      # Red
    "no_gloves": (0, 0, 180),      # Dark Red
    "no_boots": (0, 0, 140),       # Maroon
}

class PPEDetector:
    """
    Handles independent PPE object detection on video frames using a trained YOLO model.
    Produces raw PPE detections (bbox, class, confidence) without performing worker association.
    """

    def __init__(self, weights: str = "models/ppe_yolov8n_best.pt", conf: float = 0.35, imgsz: int = 320, device: str = "cpu"):
        self.weights = weights
        self.conf = conf
        self.imgsz = imgsz
        self.device = device

        if not os.path.exists(weights):
            raise FileNotFoundError(f"PPE Model file '{weights}' does not exist.")

        self.model = YOLO(weights)
        self.names = {int(k): v for k, v in self.model.names.items()}

    def detect(self, frame: np.ndarray, imgsz: Optional[int] = None) -> List[DetectedPPE]:
        """
        Runs PPE detection on a single frame.

        Returns:
            List[DetectedPPE]: List of detected PPE items with bounding boxes and confidences.
        """
        eval_imgsz = imgsz if imgsz is not None else self.imgsz
        h, w = frame.shape[:2]
        # For high-definition / 4K frames (width >= 1920), ensure imgsz is at least 960 to prevent
        # small gear (helmets, goggles) from falling below the network receptive field.
        if imgsz is None and w >= 1920 and eval_imgsz < 960:
            eval_imgsz = 960

        results = self.model.predict(
            source=frame,
            conf=self.conf,
            imgsz=eval_imgsz,
            device=self.device,
            verbose=False
        )

        detections: List[DetectedPPE] = []
        if results and len(results) > 0 and results[0].boxes is not None:
            boxes = results[0].boxes
            for b in boxes:
                x1, y1, x2, y2 = map(int, b.xyxy[0])
                conf = float(b.conf[0])
                cls_id = int(b.cls[0])
                cls_name = self.names.get(cls_id, f"cls_{cls_id}")

                detections.append(
                    DetectedPPE(
                        class_id=cls_id,
                        class_name=cls_name,
                        confidence=conf,
                        bbox=(x1, y1, x2, y2)
                    )
                )

        return detections

    def annotate(self, frame: np.ndarray, detections: List[DetectedPPE]) -> np.ndarray:
        """
        Renders PPE bounding boxes and label tags onto the provided frame.
        Uses visually distinct colors from the person tracker to maintain readability.
        """
        annotated = frame.copy()
        for det in detections:
            x1, y1, x2, y2 = det.bbox
            color = PPE_CLASS_COLORS.get(det.class_name.lower(), (255, 255, 0))

            # Draw bounding box (dashed appearance or thinner stroke than worker box)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

            label = f"{det.class_name} {det.confidence:.2f}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)

            # Draw badge above or inside box
            label_y = max(y1 - 4, th + 4)
            cv2.rectangle(annotated, (x1, label_y - th - 3), (x1 + tw + 4, label_y + 2), color, -1)
            cv2.putText(annotated, label, (x1 + 2, label_y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)

        return annotated
