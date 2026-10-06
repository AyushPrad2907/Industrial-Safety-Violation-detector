import uuid
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Tuple, Optional, Set
import cv2
import numpy as np

import config
from ppe_association import PPEState, WorkerPPEStatus, AssociationResult

class ViolationStatus(Enum):
    NORMAL = "NORMAL"
    SUSPECTED = "SUSPECTED"
    CONFIRMED = "CONFIRMED"
    RESOLVED = "RESOLVED"

class SeverityLevel(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"

class ViolationType(Enum):
    MISSING_HELMET = "MISSING_HELMET"
    MISSING_VEST = "MISSING_VEST"
    MISSING_GLOVES = "MISSING_GLOVES"
    MISSING_BOOTS = "MISSING_BOOTS"
    MISSING_GOGGLES = "MISSING_GOGGLES"

CATEGORY_TO_VIOLATION_TYPE = {
    "helmet": ViolationType.MISSING_HELMET,
    "vest": ViolationType.MISSING_VEST,
    "gloves": ViolationType.MISSING_GLOVES,
    "boots": ViolationType.MISSING_BOOTS,
    "goggles": ViolationType.MISSING_GOGGLES,
}

VIOLATION_TYPE_TO_CATEGORY = {v: k for k, v in CATEGORY_TO_VIOLATION_TYPE.items()}

# Default PPE requirements policy
DEFAULT_REQUIRED_PPE = {
    "helmet": True,
    "vest": True,
    "gloves": True,
    "boots": True,
    "goggles": False,  # Optional by default in standard transit/open areas
}

# Default severity policy by violation type
DEFAULT_SEVERITY_POLICY = {
    ViolationType.MISSING_HELMET: SeverityLevel.CRITICAL,
    ViolationType.MISSING_VEST: SeverityLevel.HIGH,
    ViolationType.MISSING_BOOTS: SeverityLevel.MEDIUM,
    ViolationType.MISSING_GLOVES: SeverityLevel.MEDIUM,
    ViolationType.MISSING_GOGGLES: SeverityLevel.MEDIUM,
}

@dataclass
class TemporalObservation:
    """A single frame observation of a specific PPE category for a worker."""
    frame_idx: int
    timestamp: float
    state: PPEState
    detection_confidence: float = 0.0
    association_confidence: float = 0.0
    is_zone_violation: bool = False

@dataclass
class ViolationEvent:
    """
    Structured in-memory event emitted when a violation changes state (e.g. CONFIRMED or RESOLVED).
    Prepared for future consumption by Phase 6 (persistence, database, alerts).
    """
    event_id: str
    track_id: int
    violation_type: ViolationType
    severity: SeverityLevel
    status: ViolationStatus
    frame_index: int
    timestamp: float
    decision_score: float
    missing_ratio: float
    observable_frames: int
    window_size: int
    is_zone_violation: bool
    worker_bbox: Tuple[int, int, int, int]
    message: str

@dataclass
class PPECategoryTemporalTracker:
    """Maintains sliding-window history and lifecycle for one PPE category on one worker."""
    category: str
    violation_type: ViolationType
    history: deque = field(default_factory=deque)  # deque of TemporalObservation
    current_status: ViolationStatus = ViolationStatus.NORMAL
    last_event_status: ViolationStatus = ViolationStatus.NORMAL  # Tracks debouncing state
    last_confirmed_frame: int = -1
    consecutive_present_count: int = 0

    def add_observation(self, obs: TemporalObservation, max_window: int):
        self.history.append(obs)
        while len(self.history) > max_window:
            self.history.popleft()

    def get_metrics(self) -> Tuple[int, int, int, float, float]:
        """
        Returns:
            (missing_count, present_count, observable_count, missing_ratio, present_ratio)
        """
        missing_count = sum(1 for o in self.history if o.state == PPEState.NOT_ASSOCIATED)
        present_count = sum(1 for o in self.history if o.state == PPEState.PRESENT)
        observable_count = missing_count + present_count

        missing_ratio = (missing_count / float(observable_count)) if observable_count > 0 else 0.0
        present_ratio = (present_count / float(observable_count)) if observable_count > 0 else 0.0
        return missing_count, present_count, observable_count, missing_ratio, present_ratio

@dataclass
class WorkerTemporalState:
    """Maintains temporal trackers for all PPE categories for a single worker."""
    track_id: int
    last_seen_frame: int
    last_seen_timestamp: float
    last_bbox: Tuple[int, int, int, int]
    is_zone_violation: bool = False
    trackers: Dict[str, PPECategoryTemporalTracker] = field(default_factory=dict)

    @classmethod
    def create(cls, track_id: int, frame_idx: int, timestamp: float, bbox: Tuple[int, int, int, int], is_zone: bool):
        inst = cls(
            track_id=track_id,
            last_seen_frame=frame_idx,
            last_seen_timestamp=timestamp,
            last_bbox=bbox,
            is_zone_violation=is_zone,
            trackers={}
        )
        for cat, vtype in CATEGORY_TO_VIOLATION_TYPE.items():
            inst.trackers[cat] = PPECategoryTemporalTracker(category=cat, violation_type=vtype)
        return inst

@dataclass
class TemporalEvaluationResult:
    """Outcome of evaluating temporal state for a single frame across all workers."""
    active_confirmed_violations: List[ViolationEvent]
    active_suspected_violations: List[ViolationEvent]
    newly_emitted_events: List[ViolationEvent]  # Debounced transition events (CONFIRMED / RESOLVED)
    worker_summaries: Dict[int, Dict[str, Dict]]  # track_id -> category -> summary dict


class TemporalViolationEngine:
    """
    Temporal Stability & Violation Decision Engine for Phase 5.
    
    Transforms noisy single-frame PPE associations into robust, debounced,
    temporally-confirmed safety violations.
    """

    def __init__(
        self,
        window_size: int = config.DEFAULT_TEMPORAL_WINDOW_SIZE,
        violation_ratio_threshold: float = config.DEFAULT_VIOLATION_RATIO_THRESHOLD,
        min_observable_frames: int = config.DEFAULT_MIN_OBSERVABLE_FRAMES,
        resolution_ratio_threshold: float = config.DEFAULT_RESOLUTION_RATIO_THRESHOLD,
        track_ttl: int = config.DEFAULT_TRACK_HISTORY_TTL,
        required_ppe_policy: Optional[Dict[str, bool]] = None,
        severity_policy: Optional[Dict[ViolationType, SeverityLevel]] = None,
    ):
        self.window_size = window_size
        self.violation_ratio_threshold = violation_ratio_threshold
        self.min_observable_frames = min_observable_frames
        self.resolution_ratio_threshold = resolution_ratio_threshold
        self.track_ttl = track_ttl

        self.required_ppe_policy = required_ppe_policy or dict(DEFAULT_REQUIRED_PPE)
        self.severity_policy = severity_policy or dict(DEFAULT_SEVERITY_POLICY)

        # In-memory worker states: track_id -> WorkerTemporalState
        self.workers: Dict[int, WorkerTemporalState] = {}
        self.current_frame: int = 0

    def reset(self):
        """Resets all temporal states and histories."""
        self.workers.clear()
        self.current_frame = 0

    def get_effective_requirement(self, category: str, is_in_zone: bool) -> bool:
        """
        Determines whether a PPE item is required given zone context.
        Restricted-zone policy override: In restricted zones, goggles and all equipment are mandatory.
        """
        if is_in_zone:
            return True
        return self.required_ppe_policy.get(category.lower(), False)

    def get_effective_severity(self, vtype: ViolationType, is_in_zone: bool) -> SeverityLevel:
        """
        Determines effective severity.
        Restricted-zone policy override: violations inside restricted zones escalate in severity.
        """
        base = self.severity_policy.get(vtype, SeverityLevel.MEDIUM)
        if is_in_zone:
            if base in (SeverityLevel.HIGH, SeverityLevel.MEDIUM):
                return SeverityLevel.CRITICAL
            elif base == SeverityLevel.LOW:
                return SeverityLevel.HIGH
        return base

    def compute_decision_score(
        self,
        missing_ratio: float,
        observable_count: int,
        window_size: int,
        avg_assoc_conf: float
    ) -> float:
        """
        Calculates an explainable decision score [0.0 - 1.0] representing
        confidence in the temporal decision.
        """
        sample_support = min(observable_count / float(max(window_size, 1)), 1.0)
        score = (0.60 * missing_ratio) + (0.30 * sample_support) + (0.10 * (1.0 - avg_assoc_conf))
        return float(np.clip(score, 0.0, 1.0))

    def process(self, association_result: AssociationResult, frame_idx: int, timestamp: Optional[float] = None) -> TemporalEvaluationResult:
        """
        Ingests a Phase 4 AssociationResult for a frame, updates temporal buffers,
        evaluates violation lifecycles, and returns debounced events.
        """
        self.current_frame = frame_idx
        ts = timestamp if timestamp is not None else time.time()

        active_confirmed: List[ViolationEvent] = []
        active_suspected: List[ViolationEvent] = []
        newly_emitted: List[ViolationEvent] = []
        worker_summaries: Dict[int, Dict[str, Dict]] = {}

        seen_track_ids: Set[int] = set()

        for track_id, status in association_result.worker_statuses.items():
            seen_track_ids.add(track_id)

            if track_id not in self.workers:
                self.workers[track_id] = WorkerTemporalState.create(
                    track_id=track_id,
                    frame_idx=frame_idx,
                    timestamp=ts,
                    bbox=status.worker_bbox,
                    is_zone=status.is_zone_violation
                )

            w_state = self.workers[track_id]
            w_state.last_seen_frame = frame_idx
            w_state.last_seen_timestamp = ts
            w_state.last_bbox = status.worker_bbox
            w_state.is_zone_violation = status.is_zone_violation

            worker_summaries[track_id] = {}

            # Evaluate each PPE category
            for cat, vtype in CATEGORY_TO_VIOLATION_TYPE.items():
                cat_state = status.get_category_state(cat)
                tracker = w_state.trackers[cat]

                obs = TemporalObservation(
                    frame_idx=frame_idx,
                    timestamp=ts,
                    state=cat_state.state,
                    detection_confidence=cat_state.detection_confidence,
                    association_confidence=cat_state.association_confidence,
                    is_zone_violation=status.is_zone_violation
                )
                tracker.add_observation(obs, max_window=self.window_size)

                is_required = self.get_effective_requirement(cat, status.is_zone_violation)
                missing_cnt, present_cnt, obs_cnt, missing_ratio, present_ratio = tracker.get_metrics()
                severity = self.get_effective_severity(vtype, status.is_zone_violation)

                dec_score = self.compute_decision_score(
                    missing_ratio=missing_ratio,
                    observable_count=obs_cnt,
                    window_size=self.window_size,
                    avg_assoc_conf=cat_state.association_confidence
                )

                # State Machine Transition Logic
                prev_status = tracker.current_status
                next_status = prev_status

                if not is_required:
                    # Equipment is not mandated in this zone
                    next_status = ViolationStatus.NORMAL
                else:
                    if prev_status in (ViolationStatus.NORMAL, ViolationStatus.SUSPECTED):
                        # Evaluating potential confirmation
                        if obs_cnt >= self.min_observable_frames and missing_ratio >= self.violation_ratio_threshold:
                            next_status = ViolationStatus.CONFIRMED
                        elif obs_cnt >= 2 and missing_ratio >= (self.violation_ratio_threshold * 0.70):
                            next_status = ViolationStatus.SUSPECTED
                        else:
                            next_status = ViolationStatus.NORMAL

                    elif prev_status == ViolationStatus.CONFIRMED:
                        # Evaluating potential resolution
                        # Resolve only if sufficient evidence shows PRESENT
                        if obs_cnt >= self.min_observable_frames and present_ratio >= self.resolution_ratio_threshold:
                            next_status = ViolationStatus.RESOLVED
                        else:
                            next_status = ViolationStatus.CONFIRMED

                    elif prev_status == ViolationStatus.RESOLVED:
                        # Once resolved, evaluate if worker remains clean (NORMAL) or becomes non-compliant again
                        if obs_cnt >= self.min_observable_frames and missing_ratio >= self.violation_ratio_threshold:
                            next_status = ViolationStatus.CONFIRMED
                        elif obs_cnt >= 2 and missing_ratio >= (self.violation_ratio_threshold * 0.70):
                            next_status = ViolationStatus.SUSPECTED
                        elif present_ratio >= self.resolution_ratio_threshold:
                            next_status = ViolationStatus.RESOLVED
                        else:
                            next_status = ViolationStatus.NORMAL

                tracker.current_status = next_status

                # Construct representative violation event if confirmed or suspected
                event = ViolationEvent(
                    event_id=f"EVT_{track_id}_{vtype.value}_{frame_idx}",
                    track_id=track_id,
                    violation_type=vtype,
                    severity=severity,
                    status=next_status,
                    frame_index=frame_idx,
                    timestamp=ts,
                    decision_score=dec_score,
                    missing_ratio=missing_ratio,
                    observable_frames=obs_cnt,
                    window_size=len(tracker.history),
                    is_zone_violation=status.is_zone_violation,
                    worker_bbox=status.worker_bbox,
                    message=f"Worker #{track_id} {vtype.value}: {missing_cnt}/{obs_cnt} observable frames missing"
                )

                if next_status == ViolationStatus.CONFIRMED:
                    active_confirmed.append(event)
                elif next_status == ViolationStatus.SUSPECTED:
                    active_suspected.append(event)

                # Debouncing Check: Emit new event ONLY on state change
                if next_status == ViolationStatus.CONFIRMED and tracker.last_event_status != ViolationStatus.CONFIRMED:
                    newly_emitted.append(event)
                    tracker.last_event_status = ViolationStatus.CONFIRMED
                    tracker.last_confirmed_frame = frame_idx

                elif next_status in (ViolationStatus.NORMAL, ViolationStatus.RESOLVED) and tracker.last_event_status == ViolationStatus.CONFIRMED:
                    resolved_event = ViolationEvent(
                        event_id=f"RES_{track_id}_{vtype.value}_{frame_idx}",
                        track_id=track_id,
                        violation_type=vtype,
                        severity=SeverityLevel.NONE,
                        status=ViolationStatus.RESOLVED,
                        frame_index=frame_idx,
                        timestamp=ts,
                        decision_score=dec_score,
                        missing_ratio=missing_ratio,
                        observable_frames=obs_cnt,
                        window_size=len(tracker.history),
                        is_zone_violation=status.is_zone_violation,
                        worker_bbox=status.worker_bbox,
                        message=f"Worker #{track_id} {vtype.value} violation resolved"
                    )
                    newly_emitted.append(resolved_event)
                    tracker.last_event_status = next_status

                worker_summaries[track_id][cat] = {
                    "status": next_status.value,
                    "severity": severity.value,
                    "is_required": is_required,
                    "missing_count": missing_cnt,
                    "present_count": present_cnt,
                    "observable_count": obs_cnt,
                    "missing_ratio": missing_ratio,
                    "decision_score": dec_score
                }

        # Track history lifecycle cleanup for vanished workers
        self._cleanup_stale_tracks(seen_track_ids, frame_idx)

        return TemporalEvaluationResult(
            active_confirmed_violations=active_confirmed,
            active_suspected_violations=active_suspected,
            newly_emitted_events=newly_emitted,
            worker_summaries=worker_summaries
        )

    def _cleanup_stale_tracks(self, active_track_ids: Set[int], current_frame: int):
        """Removes temporal history for workers not seen for TRACK_HISTORY_TTL frames."""
        stale_ids = [
            tid for tid, w in self.workers.items()
            if tid not in active_track_ids and (current_frame - w.last_seen_frame) > self.track_ttl
        ]
        for tid in stale_ids:
            del self.workers[tid]

    def annotate_frame(self, frame: np.ndarray, result: TemporalEvaluationResult) -> np.ndarray:
        """
        Renders minimal, non-cluttering visual badges for confirmed and suspected violations.
        """
        annotated = frame.copy()

        # Group violations by worker ID
        worker_violations: Dict[int, List[ViolationEvent]] = {}
        for ev in result.active_confirmed_violations:
            worker_violations.setdefault(ev.track_id, []).append(ev)

        worker_suspicions: Dict[int, List[ViolationEvent]] = {}
        for ev in result.active_suspected_violations:
            worker_suspicions.setdefault(ev.track_id, []).append(ev)

        for w_id, w_state in self.workers.items():
            if w_id not in result.worker_summaries:
                continue

            wx1, wy1, wx2, wy2 = w_state.last_bbox
            badges = []

            # 1. Confirmed violations (Red badge)
            if w_id in worker_violations:
                for v in worker_violations[w_id]:
                    cat = VIOLATION_TYPE_TO_CATEGORY.get(v.violation_type, v.violation_type.value)
                    badges.append((f"NO {cat.upper()} [{v.severity.value}]", (0, 0, 255)))

            # 2. Suspected violations (Yellow badge, if not already confirmed)
            elif w_id in worker_suspicions:
                for v in worker_suspicions[w_id]:
                    cat = VIOLATION_TYPE_TO_CATEGORY.get(v.violation_type, v.violation_type.value)
                    badges.append((f"? {cat} ({int(v.missing_ratio*100)}%)", (0, 165, 255)))

            # Draw stacked badges above worker head
            curr_y = wy1 - 10
            for text, color in badges:
                (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
                label_y = max(curr_y, th + 4)
                cv2.rectangle(annotated, (wx1, label_y - th - 3), (wx1 + tw + 6, label_y + 3), color, -1)
                cv2.putText(annotated, text, (wx1 + 3, label_y - 1), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
                curr_y = label_y - th - 6

        return annotated
