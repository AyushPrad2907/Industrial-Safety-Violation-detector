from pydantic import BaseModel
from typing import Optional, List

class ViolationRecordSchema(BaseModel):
    event_id: str
    track_id: int
    violation_type: str
    severity: str
    decision_score: float
    evidence_path: Optional[str] = ""
    timestamp: str
    status: str
    frame_index: Optional[int] = 0
    missing_ratio: Optional[float] = 0.0
    observable_frames: Optional[int] = 0
    is_zone_violation: Optional[int] = 0
    message: Optional[str] = ""

class ViolationListResponse(BaseModel):
    total: int
    filtered: int
    violations: List[ViolationRecordSchema]

class SessionResetResponse(BaseModel):
    status: str
    message: str
    preserved_records: int
