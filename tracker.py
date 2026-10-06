from dataclasses import dataclass
from typing import Tuple

@dataclass
class TrackedWorker:
    """
    Represents a detected and tracked worker in a single video frame.
    """
    track_id: int
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    confidence: float
    is_zone_violation: bool = False

    @property
    def foot_point(self) -> Tuple[int, int]:
        """Returns the bottom-center coordinate of the bounding box."""
        x1, _, x2, y2 = self.bbox
        return ((x1 + x2) // 2, y2)
