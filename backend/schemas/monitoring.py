from pydantic import BaseModel
from typing import List, Optional, Dict, Any

class PPEItemStatus(BaseModel):
    category: str
    state: str  # PRESENT, NOT_ASSOCIATED, UNKNOWN
    detection_confidence: float = 0.0
    association_confidence: float = 0.0
    temporal_status: str = "NORMAL"  # NORMAL, SUSPECTED, CONFIRMED, RESOLVED
    missing_count: int = 0
    observable_count: int = 0

class WorkerStatusSchema(BaseModel):
    track_id: int
    overall_status: str  # NORMAL, SUSPECTED, CONFIRMED
    bbox: List[int]
    confidence: float
    ppe: Dict[str, PPEItemStatus]

class MonitoringStatsSchema(BaseModel):
    fps: float
    frame_index: int
    resolution: str
    latency_ms: float
    active_workers: int
    total_violations: int
    critical_violations: int
    pipeline_state: str  # RUNNING, IDLE, STOPPED

class SystemStatusSchema(BaseModel):
    ai_pipeline: str  # CONNECTED, STOPPED
    websocket: str    # CONNECTED, DISCONNECTED
    database: str     # AVAILABLE, ERROR
    camera_video: str # RUNNING, STOPPED
    telegram: str     # ENABLED, DISABLED

class StartMonitoringRequest(BaseModel):
    source_type: str = "sample"  # sample, webcam, rtsp, upload
    video_path: Optional[str] = ""
    stream_url: Optional[str] = ""
    webcam_index: int = 0
    camera_name: Optional[str] = "Cam-1"
