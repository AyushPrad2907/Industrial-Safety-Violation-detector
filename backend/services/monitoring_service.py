import os
import time
import threading
import asyncio
import logging
from typing import Dict, List, Optional, Any
import cv2
import numpy as np

import config
import database
from detector import SafetyDetector
from ppe_detector import PPEDetector
from ppe_association import WorkerPPEAssociator, PPEState
from temporal_engine import TemporalViolationEngine, ViolationStatus
from violation_handler import ViolationHandler
from telegram_alert import TelegramAlertManager
from video_source import VideoSourceHandler
from dashboard_utils import format_violation_type, format_severity
from backend.services.alert_service import alert_service

logger = logging.getLogger(__name__)

class MonitoringService:
    """
    Central AI Pipeline Service:
    Maintains a SINGLE source of truth for the entire detection, tracking,
    PPE association, temporal engine, and violation handler pipeline.
    Runs a dedicated background worker thread that pushes frames to an MJPEG buffer
    and broadcasts state updates and confirmed violations over WebSockets.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self.is_running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Telemetry & pipeline state
        self.fps: float = 0.0
        self.frame_index: int = 0
        self.resolution: str = "0x0"
        self.latency_ms: float = 0.0
        self.active_workers_count: int = 0
        self.current_workers: List[Dict[str, Any]] = []
        self.pipeline_state: str = "IDLE"  # IDLE, RUNNING, STOPPED, ERROR

        # Latest annotated JPEG frame buffer for MJPEG streaming
        self.latest_jpeg_frame: Optional[bytes] = None

        # Existing AI Pipeline instances (reused directly)
        self.detector: Optional[SafetyDetector] = None
        self.ppe_detector: Optional[PPEDetector] = None
        self.associator: Optional[WorkerPPEAssociator] = None
        self.temporal_engine: Optional[TemporalViolationEngine] = None
        self.violation_handler: Optional[ViolationHandler] = None

        # Async loop reference for broadcasting from synchronous background thread
        self.async_loop: Optional[asyncio.AbstractEventLoop] = None

        # Video source configuration
        self.source_type: str = "Upload video"
        self.sample_video_path: str = ""
        self.webcam_index: int = 0
        self.stream_url: str = ""

        # Find any available sample video in dataset or local folder
        self._detect_sample_video()

    def _detect_sample_video(self):
        """Finds a candidate sample video for default demonstration if available."""
        candidates = [
            "sample.mp4",
            "test.mp4",
            "demo.mp4",
            "datasets/sample.mp4",
            "datasets/demo.mp4"
        ]
        for c in candidates:
            if os.path.exists(c):
                self.sample_video_path = c
                break

    def set_async_loop(self, loop: asyncio.AbstractEventLoop):
        self.async_loop = loop

    def initialize_models(self) -> bool:
        """Initializes the existing AI components safely."""
        with self._lock:
            try:
                weights = config.DEFAULT_MODEL_WEIGHTS
                ppe_weights = config.DEFAULT_PPE_MODEL_WEIGHTS

                if not os.path.exists(weights):
                    logger.warning(f"Person weights {weights} not found on disk.")
                    self.pipeline_state = "ERROR"
                    return False

                if not os.path.exists(ppe_weights):
                    logger.warning(f"PPE weights {ppe_weights} not found on disk.")
                    self.pipeline_state = "ERROR"
                    return False

                self.detector = SafetyDetector(
                    weights=weights,
                    conf=config.DEFAULT_CONFIDENCE,
                    cooldown=config.DEFAULT_COOLDOWN
                )
                self.ppe_detector = PPEDetector(
                    weights=ppe_weights,
                    conf=config.DEFAULT_PPE_CONFIDENCE,
                    device="cpu"
                )
                self.associator = WorkerPPEAssociator(min_threshold=config.DEFAULT_ASSOCIATION_THRESHOLD)
                self.temporal_engine = TemporalViolationEngine(
                    window_size=config.DEFAULT_TEMPORAL_WINDOW_SIZE,
                    violation_ratio_threshold=config.DEFAULT_VIOLATION_RATIO_THRESHOLD,
                    min_observable_frames=config.DEFAULT_MIN_OBSERVABLE_FRAMES
                )
                alert_mgr = TelegramAlertManager(enabled=config.TELEGRAM_ALERTS_ENABLED)
                self.violation_handler = ViolationHandler(alert_manager=alert_mgr)

                logger.info("AI pipeline modules initialized successfully.")
                self.pipeline_state = "IDLE"
                return True
            except Exception as e:
                logger.error(f"Failed to initialize AI pipeline: {e}")
                self.pipeline_state = "ERROR"
                return False

    def start_monitoring(
        self,
        source_type: str = "Upload video",
        video_path: Optional[str] = None,
        webcam_index: int = 0,
        stream_url: str = ""
    ) -> bool:
        """Starts the single background inference loop."""
        if self.is_running:
            return True

        if self.detector is None:
            if not self.initialize_models():
                return False

        self.source_type = source_type
        if video_path:
            self.sample_video_path = video_path
        self.webcam_index = webcam_index
        self.stream_url = stream_url

        self._stop_event.clear()
        self.is_running = True
        self.pipeline_state = "RUNNING"
        self._thread = threading.Thread(target=self._run_inference_loop, daemon=True)
        self._thread.start()
        logger.info("Monitoring background thread started.")
        return True

    def stop_monitoring(self):
        """Stops the inference loop gracefully."""
        if not self.is_running:
            return

        self.is_running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.pipeline_state = "STOPPED"
        logger.info("Monitoring background thread stopped.")

    def reset_session(self) -> int:
        """
        Clears live tracking state, temporal engine, and current worker memory.
        Preserves SQLite historical records and evidence files.
        """
        with self._lock:
            if self.detector:
                self.detector.reset_tracking()
            if self.temporal_engine:
                self.temporal_engine.reset()
            if self.violation_handler:
                self.violation_handler.processed_events.clear()

            self.current_workers = []
            self.active_workers_count = 0
            self.frame_index = 0
            self.fps = 0.0

        preserved_count = database.get_violation_count()
        logger.info(f"Live session state reset. Preserved {preserved_count} historical database records.")
        return preserved_count

    def get_stats(self) -> Dict[str, Any]:
        """Returns snapshot statistics for REST endpoint."""
        total_violations = database.get_violation_count()
        # Count critical violations safely from DB
        recent = database.get_recent_violations(limit=500)
        critical_count = sum(1 for r in recent if str(r.get("severity", "")).upper() == "CRITICAL")

        return {
            "fps": round(self.fps, 1),
            "frame_index": self.frame_index,
            "resolution": self.resolution,
            "latency_ms": round(self.latency_ms, 1),
            "active_workers": self.active_workers_count,
            "total_violations": total_violations,
            "critical_violations": critical_count,
            "pipeline_state": self.pipeline_state
        }

    def get_workers(self) -> List[Dict[str, Any]]:
        """Returns current tracked worker states."""
        with self._lock:
            return list(self.current_workers)

    def _dispatch_async(self, coro):
        """Helper to run coroutines on the application async event loop from worker thread."""
        if self.async_loop and not self.async_loop.is_closed():
            asyncio.run_coroutine_threadsafe(coro, self.async_loop)

    def _run_inference_loop(self):
        """
        Primary worker loop executing the existing AI components.
        Produces MJPEG frames and broadcasts updates.
        """
        # Determine Video Capture
        cap = None
        if self.source_type == "Webcam":
            cap = cv2.VideoCapture(self.webcam_index)
        elif self.source_type == "RTSP / URL" and self.stream_url:
            cap = cv2.VideoCapture(self.stream_url)
        elif self.sample_video_path and os.path.exists(self.sample_video_path):
            cap = cv2.VideoCapture(self.sample_video_path)

        # Fallback synthetic frame generator if no video file or camera exists
        use_synthetic = cap is None or not cap.isOpened()
        if use_synthetic:
            logger.info("No active video feed found; running synthetic stream simulation for monitoring demo.")

        prev_time = time.time()
        frame_idx = 0

        while not self._stop_event.is_set():
            start_loop_t = time.time()
            if not use_synthetic:
                ret, frame = cap.read()
                if not ret:
                    # Loop video for continuous demonstration
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = cap.read()
                    if not ret:
                        time.sleep(0.05)
                        continue
            else:
                # Create clean synthetic industrial test frame (480x640)
                frame = np.full((480, 640, 3), 40, dtype=np.uint8)
                cv2.putText(frame, "STANDBY / DEMO STREAM", (160, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)
                time.sleep(0.06)  # simulate ~16 FPS

            frame_idx += 1
            h, w = frame.shape[:2]
            self.resolution = f"{w}x{h}"

            # Step 1: SafetyDetector & ByteTrack
            t0 = time.time()
            annotated_frame, zone_viols, tracked_workers = self.detector.process(frame)
            det_lat = (time.time() - t0) * 1000

            # Step 2: PPE Detection
            t1 = time.time()
            ppe_dets = self.ppe_detector.detect(frame)
            annotated_frame = self.ppe_detector.annotate(annotated_frame, ppe_dets)
            ppe_lat = (time.time() - t1) * 1000

            # Step 3: PPE Association
            t2 = time.time()
            assoc_res = self.associator.associate(
                workers=tracked_workers,
                ppe_detections=ppe_dets,
                frame_idx=frame_idx,
                timestamp=time.time()
            )
            annotated_frame = self.associator.annotate_frame(annotated_frame, assoc_res, show_connection_lines=True)
            assoc_lat = (time.time() - t2) * 1000

            # Step 4: Temporal Decision Engine
            t3 = time.time()
            temp_res = self.temporal_engine.process(
                association_result=assoc_res,
                frame_idx=frame_idx,
                timestamp=time.time()
            )
            annotated_frame = self.temporal_engine.annotate_frame(annotated_frame, temp_res)
            temp_lat = (time.time() - t3) * 1000

            total_lat = det_lat + ppe_lat + assoc_lat + temp_lat

            # Step 5: Confirmed Violations & Broadcast
            for newly_confirmed in temp_res.newly_emitted_events:
                if newly_confirmed.status == ViolationStatus.CONFIRMED:
                    vh_res = self.violation_handler.handle_violation(
                        event=newly_confirmed,
                        frame=frame
                    )
                    evidence_path = vh_res.get("evidence_path", "")

                    # Broadcast confirmed violation to all connected WebSockets
                    violation_payload = {
                        "type": "violation_confirmed",
                        "data": {
                            "event_id": newly_confirmed.event_id,
                            "track_id": newly_confirmed.track_id,
                            "violation_type": format_violation_type(newly_confirmed.violation_type),
                            "severity": format_severity(newly_confirmed.severity),
                            "decision_score": round(float(newly_confirmed.decision_score), 2),
                            "missing_ratio": round(float(newly_confirmed.missing_ratio), 2),
                            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "evidence_path": evidence_path,
                            "is_zone_violation": bool(newly_confirmed.is_zone_violation),
                            "message": newly_confirmed.message
                        }
                    }
                    self._dispatch_async(alert_service.broadcast(violation_payload))

            # Calculate FPS
            now = time.time()
            dt = now - prev_time
            self.fps = 1.0 / dt if dt > 0 else 0.0
            prev_time = now
            self.frame_index = frame_idx
            self.latency_ms = total_lat
            self.active_workers_count = len(tracked_workers)

            # Build structured worker list for UI
            workers_summary = []
            for wkr in tracked_workers:
                w_id = wkr.track_id
                w_temp = temp_res.worker_summaries.get(w_id, {})
                w_confirmed = [v for v in temp_res.active_confirmed_violations if v.track_id == w_id]
                w_suspected = [v for v in temp_res.active_suspected_violations if v.track_id == w_id]

                if w_confirmed:
                    overall = "CONFIRMED"
                elif w_suspected:
                    overall = "SUSPECTED"
                else:
                    overall = "NORMAL"

                ppe_dict = {}
                for cat in ["helmet", "vest", "gloves", "boots", "goggles"]:
                    cat_data = w_temp.get(cat, {})
                    st_val = cat_data.get("status", "NORMAL")
                    obs_cnt = cat_data.get("observable_count", 0)
                    miss_cnt = cat_data.get("missing_count", 0)

                    assoc_st = assoc_res.worker_statuses.get(w_id)
                    raw_ppe_state = "UNKNOWN"
                    det_conf = 0.0
                    assoc_conf = 0.0
                    if assoc_st:
                        item_obj = assoc_st.get_category_state(cat)
                        raw_ppe_state = item_obj.state.value if hasattr(item_obj.state, "value") else str(item_obj.state)
                        det_conf = round(float(item_obj.detection_confidence), 2)
                        assoc_conf = round(float(item_obj.association_confidence), 2)

                    ppe_dict[cat] = {
                        "category": cat,
                        "state": raw_ppe_state,
                        "detection_confidence": det_conf,
                        "association_confidence": assoc_conf,
                        "temporal_status": st_val,
                        "missing_count": miss_cnt,
                        "observable_count": obs_cnt
                    }

                workers_summary.append({
                    "track_id": w_id,
                    "overall_status": overall,
                    "bbox": list(wkr.bbox),
                    "confidence": round(float(wkr.confidence), 2),
                    "ppe": ppe_dict
                })

            with self._lock:
                self.current_workers = workers_summary

            # Encode frame to JPEG for MJPEG stream
            success, enc = cv2.imencode(".jpg", annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
            if success:
                self.latest_jpeg_frame = enc.tobytes()

            # Broadcast monitoring update event (throttled to ~3 times per second to save bandwidth)
            if frame_idx % 4 == 0:
                stats_payload = {
                    "type": "monitoring_update",
                    "data": {
                        "fps": round(self.fps, 1),
                        "frame_index": self.frame_index,
                        "latency_ms": round(self.latency_ms, 1),
                        "active_workers": self.active_workers_count,
                        "workers": workers_summary
                    }
                }
                self._dispatch_async(alert_service.broadcast(stats_payload))

        if cap and not use_synthetic:
            cap.release()

# Global monitoring service singleton
monitoring_service = MonitoringService()
