import unittest
import numpy as np
from tracker import TrackedWorker
from ppe_detector import DetectedPPE
from ppe_association import (
    WorkerPPEAssociator,
    PPEState,
    ConfidenceLevel,
    DEFAULT_MIN_ASSOCIATION_THRESHOLD
)

class TestPhase4(unittest.TestCase):

    def setUp(self):
        self.associator = WorkerPPEAssociator(min_threshold=0.35)

    def test_single_worker_single_helmet_association(self):
        """Test 1: Single worker + single helmet -> correct association."""
        # Worker at [100, 100, 200, 300] (width: 100, height: 200)
        worker = TrackedWorker(track_id=1, bbox=(100, 100, 200, 300), confidence=0.90)
        # Helmet on head: [130, 95, 170, 140] (center: 150, 117.5 -> rel_x: 0.50, rel_y: 0.0875)
        helmet = DetectedPPE(class_id=0, class_name="helmet", confidence=0.88, bbox=(130, 95, 170, 140))

        result = self.associator.associate([worker], [helmet])

        status = result.worker_statuses[1]
        self.assertEqual(status.helmet.state, PPEState.PRESENT)
        self.assertEqual(status.helmet.matched_item, helmet)
        self.assertGreater(status.helmet.association_confidence, 0.70)
        self.assertEqual(status.helmet.confidence_level, ConfidenceLevel.HIGH)
        self.assertEqual(len(result.unassigned_ppe), 0)

    def test_single_worker_helmet_and_vest(self):
        """Test 2: Single worker + helmet + vest -> both associated."""
        worker = TrackedWorker(track_id=1, bbox=(100, 100, 200, 300), confidence=0.92)
        helmet = DetectedPPE(class_id=0, class_name="helmet", confidence=0.85, bbox=(130, 95, 170, 135))
        vest = DetectedPPE(class_id=2, class_name="vest", confidence=0.90, bbox=(115, 140, 185, 230))

        result = self.associator.associate([worker], [helmet, vest])
        status = result.worker_statuses[1]

        self.assertEqual(status.helmet.state, PPEState.PRESENT)
        self.assertEqual(status.vest.state, PPEState.PRESENT)
        self.assertEqual(len(status.associated_items), 2)
        self.assertEqual(len(result.unassigned_ppe), 0)

    def test_two_workers_two_helmets(self):
        """Test 3: Two workers + two helmets -> each helmet assigned to correct worker."""
        # Worker 1 at [50, 100, 150, 300]
        w1 = TrackedWorker(track_id=1, bbox=(50, 100, 150, 300), confidence=0.90)
        # Worker 2 at [300, 100, 400, 300]
        w2 = TrackedWorker(track_id=2, bbox=(300, 100, 400, 300), confidence=0.90)

        # Helmet 1 on Worker 1 head
        h1 = DetectedPPE(class_id=0, class_name="helmet", confidence=0.88, bbox=(80, 95, 120, 135))
        # Helmet 2 on Worker 2 head
        h2 = DetectedPPE(class_id=0, class_name="helmet", confidence=0.86, bbox=(330, 95, 370, 135))

        result = self.associator.associate([w1, w2], [h1, h2])

        status1 = result.worker_statuses[1]
        status2 = result.worker_statuses[2]

        self.assertEqual(status1.helmet.matched_item, h1)
        self.assertEqual(status2.helmet.matched_item, h2)
        self.assertEqual(len(result.unassigned_ppe), 0)

    def test_two_workers_multiple_ppe(self):
        """Test 4: Two workers + multiple PPE -> correct associations across items."""
        w1 = TrackedWorker(track_id=1, bbox=(50, 100, 150, 300), confidence=0.90)
        w2 = TrackedWorker(track_id=2, bbox=(300, 100, 400, 300), confidence=0.90)

        h1 = DetectedPPE(class_id=0, class_name="helmet", confidence=0.85, bbox=(80, 95, 120, 135))
        v1 = DetectedPPE(class_id=2, class_name="vest", confidence=0.89, bbox=(65, 140, 135, 230))
        b2 = DetectedPPE(class_id=3, class_name="boots", confidence=0.82, bbox=(320, 260, 380, 295))

        result = self.associator.associate([w1, w2], [h1, v1, b2])

        status1 = result.worker_statuses[1]
        status2 = result.worker_statuses[2]

        self.assertEqual(status1.helmet.state, PPEState.PRESENT)
        self.assertEqual(status1.vest.state, PPEState.PRESENT)
        self.assertEqual(status2.boots.state, PPEState.PRESENT)
        self.assertEqual(len(result.unassigned_ppe), 0)

    def test_ppe_outside_all_workers_is_unassigned(self):
        """Test 5: PPE outside all worker regions -> UNASSIGNED."""
        worker = TrackedWorker(track_id=1, bbox=(100, 100, 200, 300), confidence=0.90)
        # Discarded helmet far away in the background
        distant_helmet = DetectedPPE(class_id=0, class_name="helmet", confidence=0.75, bbox=(500, 50, 540, 80))

        result = self.associator.associate([worker], [distant_helmet])

        status = result.worker_statuses[1]
        self.assertNotEqual(status.helmet.state, PPEState.PRESENT)
        self.assertIn(distant_helmet, result.unassigned_ppe)

    def test_ambiguous_ppe_no_forced_assignment(self):
        """Test 6: Ambiguous/distant PPE below minimum score threshold remains unassigned."""
        worker = TrackedWorker(track_id=1, bbox=(100, 100, 200, 300), confidence=0.90)
        # Vest detected somewhere near the feet (wrong body region and low confidence)
        strange_vest = DetectedPPE(class_id=2, class_name="vest", confidence=0.30, bbox=(130, 280, 170, 320))

        result = self.associator.associate([worker], [strange_vest])
        status = result.worker_statuses[1]

        self.assertNotEqual(status.vest.state, PPEState.PRESENT)
        self.assertIn(strange_vest, result.unassigned_ppe)

    def test_same_ppe_type_across_multiple_workers(self):
        """Test 7: Same PPE type across multiple workers supported without collision."""
        w1 = TrackedWorker(track_id=1, bbox=(50, 100, 150, 300), confidence=0.90)
        w2 = TrackedWorker(track_id=2, bbox=(250, 100, 350, 300), confidence=0.90)
        w3 = TrackedWorker(track_id=3, bbox=(450, 100, 550, 300), confidence=0.90)

        h1 = DetectedPPE(class_id=0, class_name="helmet", confidence=0.88, bbox=(80, 95, 120, 135))
        h2 = DetectedPPE(class_id=0, class_name="helmet", confidence=0.85, bbox=(280, 95, 320, 135))
        h3 = DetectedPPE(class_id=0, class_name="helmet", confidence=0.87, bbox=(480, 95, 520, 135))

        result = self.associator.associate([w1, w2, w3], [h1, h2, h3])

        self.assertEqual(result.worker_statuses[1].helmet.matched_item, h1)
        self.assertEqual(result.worker_statuses[2].helmet.matched_item, h2)
        self.assertEqual(result.worker_statuses[3].helmet.matched_item, h3)

    def test_worker_with_no_ppe_not_confirmed_violation(self):
        """Test 8: Worker with no PPE detection is NOT automatically labeled a confirmed violation."""
        worker = TrackedWorker(track_id=1, bbox=(100, 100, 200, 300), confidence=0.90)
        result = self.associator.associate([worker], [])

        status = result.worker_statuses[1]
        for cat in ["helmet", "vest", "gloves", "boots", "goggles"]:
            state_val = status.get_category_state(cat).state
            self.assertIn(state_val, [PPEState.NOT_ASSOCIATED, PPEState.UNKNOWN])
            # Explicit architectural check: no violation flag exists
            self.assertFalse(hasattr(status, "is_violation"))

    def test_different_bounding_box_sizes_normalized_geometry(self):
        """Test 9: Normalized geometry works reliably across small and large worker scales."""
        # Scale A: Large foreground worker (width 300, height 600)
        large_w = TrackedWorker(track_id=1, bbox=(100, 100, 400, 700), confidence=0.95)
        large_h = DetectedPPE(class_id=0, class_name="helmet", confidence=0.92, bbox=(200, 80, 300, 200))

        # Scale B: Small distant worker (width 60, height 120)
        small_w = TrackedWorker(track_id=2, bbox=(500, 200, 560, 320), confidence=0.85)
        small_h = DetectedPPE(class_id=0, class_name="helmet", confidence=0.88, bbox=(520, 195, 545, 225))

        res_large = self.associator.associate([large_w], [large_h])
        res_small = self.associator.associate([small_w], [small_h])

        self.assertEqual(res_large.worker_statuses[1].helmet.state, PPEState.PRESENT)
        self.assertEqual(res_small.worker_statuses[2].helmet.state, PPEState.PRESENT)

    def test_empty_workers_list(self):
        """Test 10: Empty workers list produces no crashes."""
        helmet = DetectedPPE(class_id=0, class_name="helmet", confidence=0.85, bbox=(100, 100, 150, 140))
        result = self.associator.associate([], [helmet])

        self.assertEqual(len(result.worker_statuses), 0)
        self.assertEqual(len(result.unassigned_ppe), 1)

    def test_empty_ppe_list(self):
        """Test 11: Empty PPE list produces no crashes."""
        worker = TrackedWorker(track_id=1, bbox=(100, 100, 200, 300), confidence=0.90)
        result = self.associator.associate([worker], [])

        self.assertEqual(len(result.worker_statuses), 1)
        self.assertEqual(len(result.unassigned_ppe), 0)

    def test_one_ppe_cannot_be_assigned_to_multiple_workers(self):
        """Conflict resolution: two overlapping workers competing for one helmet."""
        w1 = TrackedWorker(track_id=1, bbox=(100, 100, 200, 300), confidence=0.90)
        w2 = TrackedWorker(track_id=2, bbox=(120, 100, 220, 300), confidence=0.90)

        # Helmet centered exactly on Worker 1's head
        h = DetectedPPE(class_id=0, class_name="helmet", confidence=0.90, bbox=(135, 95, 165, 135))

        result = self.associator.associate([w1, w2], [h])

        # Exactly one worker receives the helmet
        w1_has = result.worker_statuses[1].helmet.state == PPEState.PRESENT
        w2_has = result.worker_statuses[2].helmet.state == PPEState.PRESENT
        self.assertTrue(w1_has ^ w2_has)  # XOR: exactly one is true
        self.assertEqual(len(result.unassigned_ppe), 0)

    def test_annotation_rendering(self):
        """Verify visual annotation runs without errors on dummy frame."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        w = TrackedWorker(track_id=1, bbox=(100, 100, 200, 300), confidence=0.90)
        h = DetectedPPE(class_id=0, class_name="helmet", confidence=0.88, bbox=(130, 95, 170, 140))
        result = self.associator.associate([w], [h])

        annotated = self.associator.annotate_frame(frame, result)
        self.assertEqual(annotated.shape, frame.shape)

if __name__ == "__main__":
    unittest.main()
