import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Tuple, Optional, Set
import numpy as np
import cv2

from tracker import TrackedWorker
from ppe_detector import DetectedPPE

class PPEState(Enum):
    PRESENT = "PRESENT"
    NOT_ASSOCIATED = "NOT_ASSOCIATED"
    UNKNOWN = "UNKNOWN"

class ConfidenceLevel(Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"

# Minimum association score required to consider a candidate valid
DEFAULT_MIN_ASSOCIATION_THRESHOLD = 0.35

# Confidence level categorization thresholds
HIGH_CONFIDENCE_THRESHOLD = 0.70
MEDIUM_CONFIDENCE_THRESHOLD = 0.45

# Worker resolution priors for reliable visibility:
# If worker box height or width is below these limits, non-detections are classified as UNKNOWN.
MIN_WORKER_HEIGHT_FOR_CONFIDENCE = 80
MIN_WORKER_WIDTH_FOR_CONFIDENCE = 30

@dataclass
class AssociatedItem:
    """Detailed record of an associated PPE item for a specific worker."""
    item: DetectedPPE
    association_score: float
    confidence_level: ConfidenceLevel
    normalized_rel_pos: Tuple[float, float]  # (rel_x, rel_y) inside worker bbox

@dataclass
class WorkerPPEItemState:
    """State of a specific PPE category (e.g. helmet, vest) for a tracked worker."""
    state: PPEState = PPEState.UNKNOWN
    detection_confidence: float = 0.0
    association_confidence: float = 0.0
    confidence_level: ConfidenceLevel = ConfidenceLevel.NONE
    matched_item: Optional[DetectedPPE] = None
    reason: str = "Initial state"

@dataclass
class WorkerPPEStatus:
    """
    Comprehensive PPE association snapshot for a tracked worker in a given frame.
    Prepares complete state for Phase 5 temporal stability without enforcing final violations.
    """
    worker_id: int
    worker_bbox: Tuple[int, int, int, int]
    worker_confidence: float
    frame_idx: int = 0
    timestamp: float = 0.0
    is_zone_violation: bool = False
    
    # Per-category equipment states
    helmet: WorkerPPEItemState = field(default_factory=WorkerPPEItemState)
    vest: WorkerPPEItemState = field(default_factory=WorkerPPEItemState)
    gloves: WorkerPPEItemState = field(default_factory=WorkerPPEItemState)
    boots: WorkerPPEItemState = field(default_factory=WorkerPPEItemState)
    goggles: WorkerPPEItemState = field(default_factory=WorkerPPEItemState)

    # List of all raw items mapped to this worker
    associated_items: List[AssociatedItem] = field(default_factory=list)

    def get_category_state(self, category: str) -> WorkerPPEItemState:
        cat = category.lower()
        if cat == "helmet":
            return self.helmet
        elif cat == "vest":
            return self.vest
        elif cat == "gloves":
            return self.gloves
        elif cat == "boots":
            return self.boots
        elif cat == "goggles":
            return self.goggles
        else:
            return WorkerPPEItemState(state=PPEState.UNKNOWN, reason=f"Unknown category {category}")

@dataclass
class AssociationResult:
    """Full outcome of an association step across all workers and PPE detections in a frame."""
    worker_statuses: Dict[int, WorkerPPEStatus]  # worker_id -> WorkerPPEStatus
    unassigned_ppe: List[DetectedPPE]
    association_matrix: Dict[int, List[AssociatedItem]]  # worker_id -> items


class WorkerPPEAssociator:
    """
    Geometric reasoning engine that maps detected PPE items to tracked workers.
    
    Uses:
    1. Normalized relative coordinates inside the worker bbox.
    2. Anatomical body-region priors (head, torso, hands, feet, face).
    3. Distance from anatomical anchor centroids.
    4. Bounding box containment & IoU.
    5. Conflict resolution (one PPE detection assigned to at most one worker with the highest valid score).
    """

    # Anatomical Region Priors:
    # (ny_min, ny_max): expected vertical range in normalized worker height [0.0 = top, 1.0 = bottom]
    # (anchor_x, anchor_y): expected normalized centroid of the body part
    # sigma_x, sigma_y: standard deviations for Gaussian distance weighting
    BODY_REGION_PRIORS = {
        "helmet": {
            "ny_range": (-0.15, 0.35),
            "anchor": (0.50, 0.10),
            "sigma_x": 0.30,
            "sigma_y": 0.20,
        },
        "goggles": {
            "ny_range": (0.05, 0.35),
            "anchor": (0.50, 0.18),
            "sigma_x": 0.25,
            "sigma_y": 0.15,
        },
        "vest": {
            "ny_range": (0.15, 0.70),
            "anchor": (0.50, 0.40),
            "sigma_x": 0.35,
            "sigma_y": 0.25,
        },
        "gloves": {
            "ny_range": (0.30, 0.85),
            "anchor": (0.50, 0.58),
            "sigma_x": 0.45,
            "sigma_y": 0.30,
        },
        "boots": {
            "ny_range": (0.65, 1.15),
            "anchor": (0.50, 0.92),
            "sigma_x": 0.35,
            "sigma_y": 0.20,
        },
    }

    def __init__(self, min_threshold: float = DEFAULT_MIN_ASSOCIATION_THRESHOLD):
        self.min_threshold = min_threshold

    def calculate_association_score(
        self,
        worker_bbox: Tuple[int, int, int, int],
        ppe_bbox: Tuple[int, int, int, int],
        ppe_class: str,
        ppe_conf: float
    ) -> Tuple[float, float, float]:
        """
        Computes the geometric association score between a worker bbox and a PPE bbox.
        
        Returns:
            (total_score, rel_x, rel_y)
        """
        wx1, wy1, wx2, wy2 = worker_bbox
        w_width = max(wx2 - wx1, 1)
        w_height = max(wy2 - wy1, 1)

        px1, py1, px2, py2 = ppe_bbox
        p_cx = (px1 + px2) / 2.0
        p_cy = (py1 + py2) / 2.0

        # Normalized coordinates relative to worker bounding box
        rel_x = (p_cx - wx1) / float(w_width)
        rel_y = (p_cy - wy1) / float(w_height)

        cls_key = ppe_class.lower()
        prior = self.BODY_REGION_PRIORS.get(cls_key)

        # Fallback if class not in explicit dictionary
        if prior is None:
            # Generic containment scoring
            if 0.0 <= rel_x <= 1.0 and 0.0 <= rel_y <= 1.0:
                return 0.5 * ppe_conf, rel_x, rel_y
            return 0.0, rel_x, rel_y

        ny_min, ny_max = prior["ny_range"]
        anc_x, anc_y = prior["anchor"]
        sig_x = prior["sigma_x"]
        sig_y = prior["sigma_y"]

        # 1. Hard/Soft vertical bounds check
        if rel_y < ny_min - 0.10 or rel_y > ny_max + 0.15:
            return 0.0, rel_x, rel_y

        # Horizontal penalty if PPE is excessively far left or right of worker body
        if rel_x < -0.25 or rel_x > 1.25:
            return 0.0, rel_x, rel_y

        # 2. Gaussian anatomical proximity to expected anchor
        dx = (rel_x - anc_x) / sig_x
        dy = (rel_y - anc_y) / sig_y
        dist_sq = dx * dx + dy * dy
        geom_score = math.exp(-0.5 * dist_sq)

        # 3. Containment / Overlap score
        inter_x1 = max(wx1, px1)
        inter_y1 = max(wy1, py1)
        inter_x2 = min(wx2, px2)
        inter_y2 = min(wy2, py2)

        p_area = max(0, px2 - px1) * max(0, py2 - py1)
        if p_area > 0 and inter_x2 > inter_x1 and inter_y2 > inter_y1:
            inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
            containment = inter_area / float(p_area)
        else:
            containment = 0.0

        # Composite association score:
        # 55% anatomical Gaussian positioning + 25% bbox containment + 20% detection confidence
        total_score = (0.55 * geom_score) + (0.25 * containment) + (0.20 * min(ppe_conf, 1.0))
        return float(np.clip(total_score, 0.0, 1.0)), rel_x, rel_y

    def associate(
        self,
        workers: List[TrackedWorker],
        ppe_detections: List[DetectedPPE],
        frame_idx: int = 0,
        timestamp: float = 0.0
    ) -> AssociationResult:
        """
        Executes Conflict-Resolved Worker <-> PPE Association for a single frame.
        """
        worker_statuses: Dict[int, WorkerPPEStatus] = {}
        for w in workers:
            worker_statuses[w.track_id] = WorkerPPEStatus(
                worker_id=w.track_id,
                worker_bbox=w.bbox,
                worker_confidence=w.confidence,
                frame_idx=frame_idx,
                timestamp=timestamp,
                is_zone_violation=w.is_zone_violation
            )

        if not workers or not ppe_detections:
            return AssociationResult(
                worker_statuses=self._finalize_worker_states(worker_statuses),
                unassigned_ppe=list(ppe_detections),
                association_matrix={w.track_id: [] for w in workers}
            )

        # Filter relevant PPE classes (skip raw 'person' or 'none' classes if present)
        relevant_ppe = [
            (idx, ppe) for idx, ppe in enumerate(ppe_detections)
            if ppe.class_name.lower() in self.BODY_REGION_PRIORS
        ]

        # Calculate all candidate pairs (score, ppe_index, worker_id, rel_pos)
        candidates = []
        for ppe_idx, ppe in relevant_ppe:
            for w in workers:
                score, rx, ry = self.calculate_association_score(
                    worker_bbox=w.bbox,
                    ppe_bbox=ppe.bbox,
                    ppe_class=ppe.class_name,
                    ppe_conf=ppe.confidence
                )
                if score >= self.min_threshold:
                    candidates.append((score, ppe_idx, w.track_id, (rx, ry)))

        # Sort candidates descending by score (Greedy optimal matching)
        candidates.sort(key=lambda x: x[0], reverse=True)

        assigned_ppe_indices: Set[int] = set()
        worker_assignments: Dict[int, List[AssociatedItem]] = {w.track_id: [] for w in workers}

        for score, ppe_idx, worker_id, rel_pos in candidates:
            if ppe_idx in assigned_ppe_indices:
                # This PPE detection has already been assigned to a better-matching worker
                continue

            ppe_item = ppe_detections[ppe_idx]
            conf_level = ConfidenceLevel.HIGH if score >= HIGH_CONFIDENCE_THRESHOLD else (
                ConfidenceLevel.MEDIUM if score >= MEDIUM_CONFIDENCE_THRESHOLD else ConfidenceLevel.LOW
            )

            assoc_item = AssociatedItem(
                item=ppe_item,
                association_score=score,
                confidence_level=conf_level,
                normalized_rel_pos=rel_pos
            )
            worker_assignments[worker_id].append(assoc_item)
            assigned_ppe_indices.add(ppe_idx)

        # Unassigned PPE
        unassigned_ppe = [
            ppe for idx, ppe in enumerate(ppe_detections)
            if idx not in assigned_ppe_indices
        ]

        # Populate per-category states on each worker
        for w in workers:
            w_status = worker_statuses[w.track_id]
            items = worker_assignments[w.track_id]
            w_status.associated_items = items

            # Group items by class category and pick best match per category
            cat_groups: Dict[str, List[AssociatedItem]] = {}
            for item in items:
                cat_key = item.item.class_name.lower()
                cat_groups.setdefault(cat_key, []).append(item)

            for category in ["helmet", "vest", "gloves", "boots", "goggles"]:
                item_state = getattr(w_status, category)
                if category in cat_groups and cat_groups[category]:
                    # Select the item with the highest association score for this category
                    best = max(cat_groups[category], key=lambda x: x.association_score)
                    item_state.state = PPEState.PRESENT
                    item_state.detection_confidence = best.item.confidence
                    item_state.association_confidence = best.association_score
                    item_state.confidence_level = best.confidence_level
                    item_state.matched_item = best.item
                    item_state.reason = f"Associated with score {best.association_score:.2f} ({best.confidence_level.value})"
                else:
                    # Item not detected or not associated
                    wx1, wy1, wx2, wy2 = w.bbox
                    w_w = wx2 - wx1
                    w_h = wy2 - wy1

                    # Inspect worker bounding box resolution / occlusion factors
                    if w_h < MIN_WORKER_HEIGHT_FOR_CONFIDENCE or w_w < MIN_WORKER_WIDTH_FOR_CONFIDENCE or w.confidence < 0.45:
                        item_state.state = PPEState.UNKNOWN
                        item_state.reason = "Worker too small or distant for confident inspection"
                    elif category in ["goggles", "gloves"]:
                        # Hands and eyes are prone to orientation/angle occlusion even on full-size workers
                        item_state.state = PPEState.UNKNOWN
                        item_state.reason = "Small equipment class: absence requires multi-frame verification"
                    else:
                        # Helmet / Vest on a clear worker
                        item_state.state = PPEState.NOT_ASSOCIATED
                        item_state.reason = "No matching detection associated in frame"

        return AssociationResult(
            worker_statuses=worker_statuses,
            unassigned_ppe=unassigned_ppe,
            association_matrix=worker_assignments
        )

    def _finalize_worker_states(self, statuses: Dict[int, WorkerPPEStatus]) -> Dict[int, WorkerPPEStatus]:
        """Fills default states when either workers or detections list is empty."""
        for w_id, status in statuses.items():
            for cat in ["helmet", "vest", "gloves", "boots", "goggles"]:
                st_obj = getattr(status, cat)
                st_obj.state = PPEState.UNKNOWN
                st_obj.reason = "No detections in frame"
        return statuses

    def annotate_frame(
        self,
        frame: np.ndarray,
        result: AssociationResult,
        show_connection_lines: bool = True
    ) -> np.ndarray:
        """
        Visually annotates worker boxes with their associated PPE summary badge,
        and optionally draws subtle association connector lines.
        """
        annotated = frame.copy()

        for w_id, status in result.worker_statuses.items():
            wx1, wy1, wx2, wy2 = status.worker_bbox
            w_cx = (wx1 + wx2) // 2
            w_cy = (wy1 + wy2) // 2

            # Draw subtle connection lines between worker center and associated PPE items
            if show_connection_lines:
                for assoc in status.associated_items:
                    px1, py1, px2, py2 = assoc.item.bbox
                    p_cx = (px1 + px2) // 2
                    p_cy = (py1 + py2) // 2
                    # Thin dashed line or subtle dotted cyan line
                    cv2.line(annotated, (w_cx, w_cy), (p_cx, p_cy), (255, 255, 0), 1, cv2.LINE_AA)

            # Build compact PPE indicator string for worker card:
            # H: helmet, V: vest, G: gloves, B: boots, E: eye/goggles
            symbols = []
            for short_name, cat in [("H", "helmet"), ("V", "vest"), ("G", "gloves"), ("B", "boots"), ("E", "goggles")]:
                cat_state = status.get_category_state(cat)
                if cat_state.state == PPEState.PRESENT:
                    symbols.append(f"{short_name}:+")
                elif cat_state.state == PPEState.NOT_ASSOCIATED:
                    symbols.append(f"{short_name}:-")
                else:
                    symbols.append(f"{short_name}:?")

            badge_text = " ".join(symbols)
            (bw, bh), _ = cv2.getTextSize(badge_text, cv2.FONT_HERSHEY_SIMPLEX, 0.40, 1)

            # Position badge immediately below worker bounding box
            badge_y = min(wy2 + bh + 4, annotated.shape[0] - 4)
            cv2.rectangle(annotated, (wx1, badge_y - bh - 2), (wx1 + bw + 6, badge_y + 3), (40, 40, 40), -1)
            cv2.putText(annotated, badge_text, (wx1 + 3, badge_y - 1), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 255, 255), 1, cv2.LINE_AA)

        return annotated
