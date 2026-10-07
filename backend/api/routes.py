import os
import time
import asyncio
from typing import Optional, List
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response, status, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse

import config
import database
from dashboard_utils import (
    load_violation_history,
    filter_violations,
    export_violations_csv,
    check_evidence_file,
    format_violation_type,
    format_severity,
)
from backend.services.monitoring_service import monitoring_service
from backend.schemas.monitoring import (
    MonitoringStatsSchema,
    SystemStatusSchema,
    WorkerStatusSchema,
    StartMonitoringRequest,
    PPEPolicyConfigRequest,
)
from backend.schemas.violation import (
    ViolationRecordSchema,
    ViolationListResponse,
    SessionResetResponse,
)

router = APIRouter()

# -----------------------------------------------------------------------------
# SYSTEM & HEALTH ENDPOINTS
# -----------------------------------------------------------------------------
@router.get("/api/health")
def get_health():
    """Health check endpoint confirming API status and component health."""
    db_ok = True
    try:
        database.init_db()
    except Exception:
        db_ok = False

    return {
        "status": "healthy",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "database": "connected" if db_ok else "error",
        "pipeline_state": monitoring_service.pipeline_state
    }

@router.get("/api/status", response_model=SystemStatusSchema)
def get_system_status():
    """System components status without leaking any secrets or tokens."""
    db_ok = True
    try:
        database.init_db()
    except Exception:
        db_ok = False

    tg_ok = config.has_telegram_credentials()
    tg_status = "ENABLED" if (config.TELEGRAM_ALERTS_ENABLED and tg_ok) else "DISABLED"

    return SystemStatusSchema(
        ai_pipeline="CONNECTED" if monitoring_service.pipeline_state in ("RUNNING", "IDLE") else "STOPPED",
        websocket="CONNECTED",
        database="AVAILABLE" if db_ok else "ERROR",
        camera_video="RUNNING" if monitoring_service.is_running else "STOPPED",
        telegram=tg_status
    )

# -----------------------------------------------------------------------------
# MONITORING & WORKER ENDPOINTS
# -----------------------------------------------------------------------------
@router.get("/api/stats", response_model=MonitoringStatsSchema)
def get_monitoring_stats():
    """Returns live telemetry, FPS, active worker counts, and violation counts."""
    stats = monitoring_service.get_stats()
    return MonitoringStatsSchema(**stats)

@router.get("/api/workers", response_model=List[WorkerStatusSchema])
def get_workers():
    """Returns current active workers and their full PPE status breakdown."""
    workers_raw = monitoring_service.get_workers()
    return [WorkerStatusSchema(**w) for w in workers_raw]

@router.post("/api/monitoring/upload")
async def upload_video(file: UploadFile = File(...)):
    """
    Receives an uploaded video file from the web client,
    stores it in a temporary storage location, and returns the path
    for instant playback in the monitoring pipeline.
    """
    suffix = Path(file.filename or "uploaded.mp4").suffix or ".mp4"
    temp_dir = Path("data/uploads")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"input_{int(time.time())}{suffix}"

    try:
        content = await file.read()
        with open(temp_path, "wb") as f:
            f.write(content)
        return {
            "status": "uploaded",
            "filename": file.filename,
            "video_path": str(temp_path).replace("\\", "/")
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save uploaded video: {str(e)}"
        )

@router.post("/api/monitoring/start")
def start_monitoring(req: StartMonitoringRequest):
    """Starts the single AI monitoring inference loop."""
    started = monitoring_service.start_monitoring(
        source_type=req.source_type,
        video_path=req.video_path or None,
        webcam_index=req.webcam_index,
        stream_url=req.stream_url or ""
    )
    if not started:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initialize AI pipeline models or start capture."
        )
    return {"status": "started", "source": req.source_type}

@router.post("/api/monitoring/stop")
def stop_monitoring():
    """Stops the active monitoring loop."""
    monitoring_service.stop_monitoring()
    return {"status": "stopped"}

@router.get("/api/config/policy")
def get_ppe_policy_config():
    """Returns active PPE requirement policy and sensitivity thresholds."""
    return monitoring_service.get_ppe_policy()

@router.post("/api/config/policy")
def update_ppe_policy_config(req: PPEPolicyConfigRequest):
    """Dynamically updates PPE compliance rules and detector confidence threshold."""
    policy = {
        "helmet": req.helmet,
        "vest": req.vest,
        "gloves": req.gloves,
        "boots": req.boots,
        "goggles": req.goggles
    }
    result = monitoring_service.update_ppe_policy(policy=policy, confidence=req.confidence)
    return {"status": "updated", **result}

# -----------------------------------------------------------------------------
# VIDEO STREAMING (MJPEG)
# -----------------------------------------------------------------------------
@router.get("/api/video/stream")
def video_stream():
    """
    Serves live annotated MJPEG stream from the single inference loop.
    Multiple connected frontend clients subscribe without duplicating inference.
    """
    def iter_frames():
        while True:
            frame_bytes = monitoring_service.latest_jpeg_frame
            if frame_bytes:
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n")
            time.sleep(0.04)  # ~25 FPS delivery cap

    return StreamingResponse(
        iter_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

# -----------------------------------------------------------------------------
# VIOLATION HISTORY & DETAIL ENDPOINTS
# -----------------------------------------------------------------------------
@router.get("/api/violations", response_model=ViolationListResponse)
def get_violations(
    severity: Optional[str] = Query("All", description="Severity filter: All, Critical, High, Medium, Low"),
    violation_type: Optional[str] = Query("All", description="Violation filter: All, Missing Helmet, etc."),
    worker_id: Optional[str] = Query("All", description="Worker track ID filter"),
    limit: int = Query(500, ge=1, le=2000)
):
    """Retrieves filtered violation history from existing SQLite database."""
    all_records = load_violation_history(limit=limit)
    filtered = filter_violations(
        violations=all_records,
        severity_filter=severity,
        violation_type_filter=violation_type,
        worker_id_filter=worker_id
    )

    pydantic_violations = []
    for r in filtered:
        pydantic_violations.append(ViolationRecordSchema(
            event_id=r.get("event_id", ""),
            track_id=int(r.get("track_id", 0)),
            violation_type=format_violation_type(r.get("violation_type", "")),
            severity=format_severity(r.get("severity", "")),
            decision_score=round(float(r.get("decision_score", 0.0)), 2),
            evidence_path=r.get("evidence_path", "") or "",
            timestamp=str(r.get("timestamp", "")),
            status=str(r.get("status", "")),
            frame_index=int(r.get("frame_index", 0)) if r.get("frame_index") is not None else 0,
            missing_ratio=round(float(r.get("missing_ratio", 0.0)), 2) if r.get("missing_ratio") is not None else 0.0,
            observable_frames=int(r.get("observable_frames", 0)) if r.get("observable_frames") is not None else 0,
            is_zone_violation=int(r.get("is_zone_violation", 0)) if r.get("is_zone_violation") is not None else 0,
            message=r.get("message", "") or ""
        ))

    return ViolationListResponse(
        total=len(all_records),
        filtered=len(pydantic_violations),
        violations=pydantic_violations
    )

@router.get("/api/violations/{event_id}", response_model=ViolationRecordSchema)
def get_violation_by_id(event_id: str):
    """Retrieves a single violation record by event_id."""
    record = database.get_violation_by_id(event_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Violation with event_id '{event_id}' not found."
        )

    return ViolationRecordSchema(
        event_id=record.get("event_id", ""),
        track_id=int(record.get("track_id", 0)),
        violation_type=format_violation_type(record.get("violation_type", "")),
        severity=format_severity(record.get("severity", "")),
        decision_score=round(float(record.get("decision_score", 0.0)), 2),
        evidence_path=record.get("evidence_path", "") or "",
        timestamp=str(record.get("timestamp", "")),
        status=str(record.get("status", "")),
        frame_index=int(record.get("frame_index", 0)) if record.get("frame_index") is not None else 0,
        missing_ratio=round(float(record.get("missing_ratio", 0.0)), 2) if record.get("missing_ratio") is not None else 0.0,
        observable_frames=int(record.get("observable_frames", 0)) if record.get("observable_frames") is not None else 0,
        is_zone_violation=int(record.get("is_zone_violation", 0)) if record.get("is_zone_violation") is not None else 0,
        message=record.get("message", "") or ""
    )

@router.get("/api/violations/export/csv")
def export_violations_csv_endpoint(
    severity: Optional[str] = Query("All"),
    violation_type: Optional[str] = Query("All"),
    worker_id: Optional[str] = Query("All")
):
    """Exports filtered violation records as a downloadable CSV file."""
    all_records = load_violation_history(limit=1000)
    filtered = filter_violations(
        violations=all_records,
        severity_filter=severity,
        violation_type_filter=violation_type,
        worker_id_filter=worker_id
    )
    csv_text = export_violations_csv(filtered)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=violation_history.csv"}
    )

# -----------------------------------------------------------------------------
# EVIDENCE SERVING WITH STRICT PATH TRAVERSAL PROTECTION
# -----------------------------------------------------------------------------
@router.get("/api/evidence/{event_id}")
def get_evidence(event_id: str):
    """
    Safely serves the JPEG evidence crop associated with a violation event.
    Guarantees path traversal prevention by strictly resolving within EVIDENCE_DIR.
    """
    record = database.get_violation_by_id(event_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Violation with event_id '{event_id}' not found."
        )

    evidence_path_str = record.get("evidence_path", "")
    if not evidence_path_str:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence file unavailable."
        )

    # Path traversal protection: resolve against base evidence directory
    evidence_base = Path(config.EVIDENCE_DIR).resolve()
    target_path = Path(evidence_path_str).resolve()

    try:
        # Enforce target_path must be within evidence_base
        target_path.relative_to(evidence_base)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Path outside evidence directory."
        )

    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence file unavailable."
        )

    return FileResponse(path=str(target_path), media_type="image/jpeg")

# -----------------------------------------------------------------------------
# SESSION CONTROL
# -----------------------------------------------------------------------------
@router.post("/api/session/reset", response_model=SessionResetResponse)
def reset_session():
    """
    Resets live tracking state, temporal engine, and worker caches.
    Historical SQLite violations and evidence image files are preserved.
    """
    preserved_records = monitoring_service.reset_session()
    return SessionResetResponse(
        status="success",
        message="Live session reset. Historical violations are preserved.",
        preserved_records=preserved_records
    )
