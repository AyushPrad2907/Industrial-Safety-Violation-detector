import os
import re
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple
import cv2
import numpy as np

import config
from temporal_engine import ViolationEvent, ViolationStatus

logger = logging.getLogger(__name__)

def sanitize_filename(name: str) -> str:
    """Strips characters that are invalid or unsafe in filesystem paths."""
    return re.sub(r'[^a-zA-Z0-9_\-\.]', '_', name)

def capture_evidence(
    event: ViolationEvent,
    frame: np.ndarray,
    output_dir: Optional[str] = None,
    padding: float = 0.15,
    jpeg_quality: int = 92
) -> Optional[str]:
    """
    Captures a high-resolution cropped evidence image of the violating worker
    with an informative metadata overlay banner.

    Evidence is captured ONLY for CONFIRMED violations.
    
    Returns:
        Optional[str]: Relative or absolute path to the saved JPEG evidence file, or None if save failed.
    """
    if event.status != ViolationStatus.CONFIRMED:
        return None

    if frame is None or frame.size == 0:
        logger.warning(f"Cannot capture evidence for event {event.event_id}: Frame is empty or None.")
        return None

    target_dir = Path(output_dir or config.EVIDENCE_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)

    h, w = frame.shape[:2]
    x1, y1, x2, y2 = event.worker_bbox

    # Check for valid bbox geometry
    is_valid_bbox = (
        x2 > x1 and y2 > y1 and
        (x2 - x1) >= 20 and (y2 - y1) >= 40 and
        x1 < w and y1 < h and x2 > 0 and y2 > 0
    )

    if is_valid_bbox:
        # Add padding around worker bounding box for context
        bw = x2 - x1
        bh = y2 - y1
        pad_x = int(bw * padding)
        pad_y = int(bh * padding)

        crop_x1 = max(0, x1 - pad_x)
        crop_y1 = max(0, y1 - pad_y)
        crop_x2 = min(w, x2 + pad_x)
        crop_y2 = min(h, y2 + pad_y)

        crop = frame[crop_y1:crop_y2, crop_x1:crop_x2].copy()
    else:
        logger.warning(f"Invalid or out-of-frame bbox {event.worker_bbox} for event {event.event_id}. Falling back to full frame.")
        crop = frame.copy()

    # Create visual overlay badge on the evidence image
    crop = _apply_evidence_overlay(crop, event)

    safe_id = sanitize_filename(event.event_id)
    filename = f"event_{safe_id}.jpg"
    out_path = target_dir / filename

    try:
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
        success = cv2.imwrite(str(out_path), crop, encode_params)
        if success:
            return str(out_path).replace('\\', '/')
        else:
            logger.error(f"cv2.imwrite failed to write {out_path}")
            return None
    except Exception as e:
        logger.error(f"Exception saving evidence for event {event.event_id}: {e}")
        return None

def _apply_evidence_overlay(img: np.ndarray, event: ViolationEvent) -> np.ndarray:
    """Draws an informative header banner with worker ID, violation type, severity, and timestamp."""
    annotated = img.copy()
    h, w = annotated.shape[:2]

    # Header banner parameters
    banner_height = min(68, max(44, int(h * 0.18)))
    overlay = annotated.copy()
    cv2.rectangle(overlay, (0, 0), (w, banner_height), (20, 20, 20), -1)
    # Blend semi-transparent banner
    cv2.addWeighted(overlay, 0.85, annotated, 0.15, 0, annotated)

    # Line 1: Worker & Violation Type (Red for CRITICAL/HIGH, Orange for other)
    v_type_str = event.violation_type.value.replace("_", " ")
    line1 = f"WORKER #{event.track_id} - {v_type_str}"
    
    # Line 2: Severity, Score, Zone, and Timestamp
    ts_str = datetime.fromtimestamp(event.timestamp).strftime("%Y-%m-%d %H:%M:%S") if isinstance(event.timestamp, (int, float)) else str(event.timestamp)
    zone_str = " | RESTRICTED ZONE" if event.is_zone_violation else ""
    line2 = f"Severity: {event.severity.value} | Score: {event.decision_score:.2f}{zone_str} | {ts_str}"

    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(annotated, line1, (10, int(banner_height * 0.44)), font, 0.52, (0, 80, 255), 2, cv2.LINE_AA)
    cv2.putText(annotated, line2, (10, int(banner_height * 0.84)), font, 0.38, (230, 230, 230), 1, cv2.LINE_AA)

    # Subtle red border around image to emphasize safety incident
    cv2.rectangle(annotated, (0, 0), (w - 1, h - 1), (0, 0, 230), 3)

    return annotated
