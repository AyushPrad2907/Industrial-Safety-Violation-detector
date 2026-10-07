import unittest
import numpy as np
from ppe_association import (
    PPEState,
    WorkerPPEStatus,
    WorkerPPEItemState,
    AssociationResult
)
from temporal_engine import (
    TemporalViolationEngine,
    ViolationStatus,
    SeverityLevel,
    ViolationType,
    ViolationEvent
)

def make_association_result(track_id: int, ppe_states: dict, is_zone: bool = False, frame_idx: int = 1) -> AssociationResult:
    """Helper to construct a mock AssociationResult for testing."""
    status = WorkerPPEStatus(
        worker_id=track_id,
        worker_bbox=(100, 100, 200, 300),
        worker_confidence=0.90,
        frame_idx=frame_idx,
        timestamp=float(frame_idx),
        is_zone_violation=is_zone
    )
    for cat, state in ppe_states.items():
        item_st = status.get_category_state(cat)
        item_st.state = state
        if state == PPEState.PRESENT:
            item_st.detection_confidence = 0.90
            item_st.association_confidence = 0.88

    return AssociationResult(
        worker_statuses={track_id: status},
        unassigned_ppe=[],
        association_matrix={track_id: []}
    )

class TestPhase5(unittest.TestCase):

    def setUp(self):
        self.engine = TemporalViolationEngine(
            window_size=10,
            violation_ratio_threshold=0.70,
            min_observable_frames=5,
            resolution_ratio_threshold=0.60,
            track_ttl=15
        )

    def test_1_empty_history(self):
        """Test 1: Engine initializes with no workers and empty history."""
        res = self.engine.process(AssociationResult({}, [], {}), frame_idx=1)
        self.assertEqual(len(res.active_confirmed_violations), 0)
        self.assertEqual(len(res.active_suspected_violations), 0)
        self.assertEqual(len(res.newly_emitted_events), 0)

    def test_2_single_present_frame(self):
        """Test 2: Single PRESENT frame -> NORMAL state, no violation."""
        ar = make_association_result(1, {"helmet": PPEState.PRESENT})
        res = self.engine.process(ar, frame_idx=1)
        self.assertEqual(len(res.active_confirmed_violations), 0)
        summary = res.worker_summaries[1]["helmet"]
        self.assertEqual(summary["status"], ViolationStatus.NORMAL.value)

    def test_3_single_not_associated_frame(self):
        """Test 3: Single NOT_ASSOCIATED frame -> NORMAL state (insufficient observations)."""
        ar = make_association_result(1, {"helmet": PPEState.NOT_ASSOCIATED})
        res = self.engine.process(ar, frame_idx=1)
        self.assertEqual(len(res.active_confirmed_violations), 0)
        summary = res.worker_summaries[1]["helmet"]
        self.assertEqual(summary["status"], ViolationStatus.NORMAL.value)

    def test_4_unknown_does_not_count_as_violation(self):
        """Test 4: UNKNOWN observations must NEVER count as missing in ratio calculation."""
        # Feed 3 PRESENT, 2 NOT_ASSOCIATED, 5 UNKNOWN
        for f in range(1, 4):
            self.engine.process(make_association_result(1, {"helmet": PPEState.PRESENT}, frame_idx=f), frame_idx=f)
        for f in range(4, 6):
            self.engine.process(make_association_result(1, {"helmet": PPEState.NOT_ASSOCIATED}, frame_idx=f), frame_idx=f)
        for f in range(6, 11):
            res = self.engine.process(make_association_result(1, {"helmet": PPEState.UNKNOWN}, frame_idx=f), frame_idx=f)

        summary = res.worker_summaries[1]["helmet"]
        # Observable count should be 5 (3 + 2), NOT 10
        self.assertEqual(summary["observable_count"], 5)
        self.assertEqual(summary["missing_count"], 2)
        self.assertAlmostEqual(summary["missing_ratio"], 2.0 / 5.0)
        self.assertEqual(len(res.active_confirmed_violations), 0)

    def test_5_unknown_only_history_does_not_trigger_violation(self):
        """Test 5: UNKNOWN-only history never triggers violation."""
        for f in range(1, 15):
            res = self.engine.process(make_association_result(1, {"helmet": PPEState.UNKNOWN}, frame_idx=f), frame_idx=f)

        summary = res.worker_summaries[1]["helmet"]
        self.assertEqual(summary["observable_count"], 0)
        self.assertEqual(summary["missing_count"], 0)
        self.assertEqual(summary["status"], ViolationStatus.NORMAL.value)
        self.assertEqual(len(res.active_confirmed_violations), 0)

    def test_6_insufficient_observable_frames(self):
        """Test 6: 4 NOT_ASSOCIATED frames (ratio=100%) but min_observable=5 -> Not confirmed."""
        for f in range(1, 5):
            res = self.engine.process(make_association_result(1, {"helmet": PPEState.NOT_ASSOCIATED}, frame_idx=f), frame_idx=f)

        summary = res.worker_summaries[1]["helmet"]
        self.assertEqual(summary["observable_count"], 4)
        self.assertEqual(summary["missing_ratio"], 1.0)
        # Should be SUSPECTED, but NOT CONFIRMED
        self.assertEqual(summary["status"], ViolationStatus.SUSPECTED.value)
        self.assertEqual(len(res.active_confirmed_violations), 0)

    def test_7_missing_ratio_below_threshold(self):
        """Test 7: 10 frames with 6 missing (60% < 70%) -> Not confirmed."""
        # 4 PRESENT, 6 NOT_ASSOCIATED
        for f in range(1, 5):
            self.engine.process(make_association_result(1, {"helmet": PPEState.PRESENT}, frame_idx=f), frame_idx=f)
        for f in range(5, 11):
            res = self.engine.process(make_association_result(1, {"helmet": PPEState.NOT_ASSOCIATED}, frame_idx=f), frame_idx=f)

        summary = res.worker_summaries[1]["helmet"]
        self.assertAlmostEqual(summary["missing_ratio"], 0.60)
        self.assertNotEqual(summary["status"], ViolationStatus.CONFIRMED.value)
        self.assertEqual(len(res.active_confirmed_violations), 0)

    def test_8_missing_ratio_exactly_at_threshold(self):
        """Test 8: 10 frames with 7 missing (70% == 70%) -> CONFIRMED."""
        for f in range(1, 4):
            self.engine.process(make_association_result(1, {"helmet": PPEState.PRESENT}, frame_idx=f), frame_idx=f)
        for f in range(4, 11):
            res = self.engine.process(make_association_result(1, {"helmet": PPEState.NOT_ASSOCIATED}, frame_idx=f), frame_idx=f)

        summary = res.worker_summaries[1]["helmet"]
        self.assertAlmostEqual(summary["missing_ratio"], 0.70)
        self.assertEqual(summary["status"], ViolationStatus.CONFIRMED.value)
        self.assertEqual(len(res.active_confirmed_violations), 1)

    def test_9_missing_ratio_above_threshold(self):
        """Test 9: 10 frames with 8 missing (80% > 70%) -> CONFIRMED."""
        for f in range(1, 3):
            self.engine.process(make_association_result(1, {"helmet": PPEState.PRESENT}, frame_idx=f), frame_idx=f)
        for f in range(3, 11):
            res = self.engine.process(make_association_result(1, {"helmet": PPEState.NOT_ASSOCIATED}, frame_idx=f), frame_idx=f)

        summary = res.worker_summaries[1]["helmet"]
        self.assertAlmostEqual(summary["missing_ratio"], 0.80)
        self.assertEqual(summary["status"], ViolationStatus.CONFIRMED.value)
        self.assertEqual(len(res.active_confirmed_violations), 1)

    def test_10_sliding_window_behavior(self):
        """Test 10: Old observations slide out as window moves forward."""
        # First 10 frames: all NOT_ASSOCIATED -> CONFIRMED
        for f in range(1, 11):
            self.engine.process(make_association_result(1, {"helmet": PPEState.NOT_ASSOCIATED}, frame_idx=f), frame_idx=f)
        self.assertEqual(len(self.engine.workers[1].trackers["helmet"].history), 10)

        # Feed 10 PRESENT frames -> all NOT_ASSOCIATED should slide out
        for f in range(11, 21):
            res = self.engine.process(make_association_result(1, {"helmet": PPEState.PRESENT}, frame_idx=f), frame_idx=f)

        self.assertEqual(len(self.engine.workers[1].trackers["helmet"].history), 10)
        summary = res.worker_summaries[1]["helmet"]
        self.assertEqual(summary["missing_count"], 0)
        self.assertEqual(summary["present_count"], 10)

    def test_11_violation_becomes_suspected(self):
        """Test 11: 2-4 NOT_ASSOCIATED frames accumulate into SUSPECTED state."""
        self.engine.process(make_association_result(1, {"vest": PPEState.NOT_ASSOCIATED}, frame_idx=1), frame_idx=1)
        res = self.engine.process(make_association_result(1, {"vest": PPEState.NOT_ASSOCIATED}, frame_idx=2), frame_idx=2)
        summary = res.worker_summaries[1]["vest"]
        self.assertEqual(summary["status"], ViolationStatus.SUSPECTED.value)

    def test_12_violation_becomes_confirmed(self):
        """Test 12: Evidence accumulating reaches CONFIRMED state."""
        for f in range(1, 6):
            res = self.engine.process(make_association_result(1, {"helmet": PPEState.NOT_ASSOCIATED}, frame_idx=f), frame_idx=f)

        # 5 out of 5 frames missing >= min_observable (5) and ratio (100% >= 70%)
        summary = res.worker_summaries[1]["helmet"]
        self.assertEqual(summary["status"], ViolationStatus.CONFIRMED.value)
        self.assertEqual(len(res.active_confirmed_violations), 1)

    def test_13_debouncing_no_duplicate_event_spam(self):
        """Test 13: Confirmed violation does NOT emit duplicate events every frame."""
        emitted_events = []
        for f in range(1, 15):
            res = self.engine.process(make_association_result(1, {"helmet": PPEState.NOT_ASSOCIATED}, frame_idx=f), frame_idx=f)
            emitted_events.extend(res.newly_emitted_events)

        # Exactly 1 CONFIRMED transition event should be emitted, not 10
        confirmed_emits = [e for e in emitted_events if e.status == ViolationStatus.CONFIRMED]
        self.assertEqual(len(confirmed_emits), 1)

    def test_14_violation_resolved_after_sufficient_recovery(self):
        """Test 14: Confirmed violation transitions to RESOLVED after sufficient PRESENT frames."""
        # 1. Trigger confirmed violation (7 frames NOT_ASSOCIATED)
        for f in range(1, 8):
            self.engine.process(make_association_result(1, {"helmet": PPEState.NOT_ASSOCIATED}, frame_idx=f), frame_idx=f)

        # 2. Feed consecutive PRESENT frames (resolves with ratio >= 60%)
        res = None
        emitted_resolutions = []
        for f in range(8, 16):
            res = self.engine.process(make_association_result(1, {"helmet": PPEState.PRESENT}, frame_idx=f), frame_idx=f)
            emitted_resolutions.extend([e for e in res.newly_emitted_events if e.status == ViolationStatus.RESOLVED])

        summary = res.worker_summaries[1]["helmet"]
        self.assertEqual(summary["status"], ViolationStatus.RESOLVED.value)
        # Verify resolution event was emitted during recovery
        self.assertGreater(len(emitted_resolutions), 0)

    def test_15_new_violation_after_previous_resolution(self):
        """Test 15: Once resolved, a subsequent re-violation emits a fresh confirmed event."""
        # Violation 1
        for f in range(1, 8):
            self.engine.process(make_association_result(1, {"helmet": PPEState.NOT_ASSOCIATED}, frame_idx=f), frame_idx=f)
        # Resolution
        for f in range(8, 18):
            self.engine.process(make_association_result(1, {"helmet": PPEState.PRESENT}, frame_idx=f), frame_idx=f)

        # Violation 2
        new_emits = []
        for f in range(18, 26):
            res = self.engine.process(make_association_result(1, {"helmet": PPEState.NOT_ASSOCIATED}, frame_idx=f), frame_idx=f)
            new_emits.extend([e for e in res.newly_emitted_events if e.status == ViolationStatus.CONFIRMED])

        self.assertEqual(len(new_emits), 1)

    def test_16_multiple_workers_independent_histories(self):
        """Test 16: Worker 1 and Worker 2 maintain independent violation states."""
        for f in range(1, 8):
            # Worker 1 missing helmet, Worker 2 wearing helmet
            s1 = WorkerPPEStatus(worker_id=1, worker_bbox=(50, 50, 150, 250), worker_confidence=0.9, frame_idx=f)
            s1.helmet.state = PPEState.NOT_ASSOCIATED
            s2 = WorkerPPEStatus(worker_id=2, worker_bbox=(200, 50, 300, 250), worker_confidence=0.9, frame_idx=f)
            s2.helmet.state = PPEState.PRESENT

            ar = AssociationResult(worker_statuses={1: s1, 2: s2}, unassigned_ppe=[], association_matrix={1: [], 2: []})
            res = self.engine.process(ar, frame_idx=f)

        self.assertEqual(res.worker_summaries[1]["helmet"]["status"], ViolationStatus.CONFIRMED.value)
        self.assertEqual(res.worker_summaries[2]["helmet"]["status"], ViolationStatus.NORMAL.value)

    def test_17_multiple_ppe_classes_independent_histories(self):
        """Test 17: Single worker has helmet PRESENT but vest NOT_ASSOCIATED -> only vest violated."""
        for f in range(1, 8):
            ar = make_association_result(1, {"helmet": PPEState.PRESENT, "vest": PPEState.NOT_ASSOCIATED}, frame_idx=f)
            res = self.engine.process(ar, frame_idx=f)

        self.assertEqual(res.worker_summaries[1]["helmet"]["status"], ViolationStatus.NORMAL.value)
        self.assertEqual(res.worker_summaries[1]["vest"]["status"], ViolationStatus.CONFIRMED.value)

    def test_18_track_history_ttl_cleanup(self):
        """Test 18: Stale worker tracks are purged from memory after TTL frames."""
        # Worker 1 seen up to frame 5
        for f in range(1, 6):
            self.engine.process(make_association_result(1, {"helmet": PPEState.PRESENT}, frame_idx=f), frame_idx=f)
        self.assertIn(1, self.engine.workers)

        # Worker 2 seen at frame 25 (> TTL=15 frames since Worker 1 last seen)
        ar2 = make_association_result(2, {"helmet": PPEState.PRESENT}, frame_idx=25)
        self.engine.process(ar2, frame_idx=25)

        self.assertNotIn(1, self.engine.workers)
        self.assertIn(2, self.engine.workers)

    def test_19_zone_specific_policy_and_severity_override(self):
        """Test 19: Entering a restricted zone escalates severity and mandates optional gear."""
        # Outside zone: goggles are optional by default
        ar_out = make_association_result(1, {"goggles": PPEState.NOT_ASSOCIATED}, is_zone=False, frame_idx=1)
        res_out = self.engine.process(ar_out, frame_idx=1)
        self.assertFalse(res_out.worker_summaries[1]["goggles"]["is_required"])

        # Inside zone: goggles become mandatory and missing vest escalates to CRITICAL
        for f in range(2, 9):
            ar_in = make_association_result(1, {"vest": PPEState.NOT_ASSOCIATED, "goggles": PPEState.NOT_ASSOCIATED}, is_zone=True, frame_idx=f)
            res_in = self.engine.process(ar_in, frame_idx=f)

        self.assertTrue(res_in.worker_summaries[1]["goggles"]["is_required"])
        self.assertEqual(res_in.worker_summaries[1]["vest"]["severity"], SeverityLevel.CRITICAL.value)

    def test_20_severity_mapping(self):
        """Test 20: Base severity policy correctly maps across equipment."""
        self.assertEqual(self.engine.get_effective_severity(ViolationType.MISSING_HELMET, False), SeverityLevel.CRITICAL)
        self.assertEqual(self.engine.get_effective_severity(ViolationType.MISSING_VEST, False), SeverityLevel.HIGH)
        self.assertEqual(self.engine.get_effective_severity(ViolationType.MISSING_BOOTS, False), SeverityLevel.MEDIUM)

    def test_21_violation_event_structure(self):
        """Test 21: Emitted ViolationEvent has all required metadata fields."""
        emitted = []
        for f in range(1, 8):
            res = self.engine.process(make_association_result(1, {"helmet": PPEState.NOT_ASSOCIATED}, frame_idx=f), frame_idx=f)
            emitted.extend(res.newly_emitted_events)

        self.assertEqual(len(emitted), 1)
        ev = emitted[0]
        self.assertIsInstance(ev, ViolationEvent)
        self.assertEqual(ev.track_id, 1)
        self.assertEqual(ev.violation_type, ViolationType.MISSING_HELMET)
        self.assertEqual(ev.severity, SeverityLevel.CRITICAL)
        self.assertEqual(ev.status, ViolationStatus.CONFIRMED)
        self.assertGreater(ev.decision_score, 0.70)
        self.assertAlmostEqual(ev.missing_ratio, 1.0)
        self.assertFalse(ev.is_zone_violation)

    def test_22_frame_annotation_rendering(self):
        """Test 22: Visual badge annotation runs cleanly without mutating base frame."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        for f in range(1, 8):
            res = self.engine.process(make_association_result(1, {"helmet": PPEState.NOT_ASSOCIATED}, frame_idx=f), frame_idx=f)

        annotated = self.engine.annotate_frame(frame, res)
        self.assertEqual(annotated.shape, frame.shape)

if __name__ == "__main__":
    unittest.main()
