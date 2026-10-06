import os
import time
import cv2
import streamlit as st
from datetime import datetime

import config
import db
import alerts
from detector import SafetyDetector
from ppe_detector import PPEDetector
from ppe_association import WorkerPPEAssociator, PPEState
from temporal_engine import TemporalViolationEngine, ViolationStatus
from zone_utils import parse_zone_polygon
from video_source import VideoSourceHandler

st.set_page_config(page_title="Industrial Safety Violation Detector", layout="wide")
st.title("🦺 Industrial Safety Violation Detector")

# Session state initialization for streaming control
if "is_running" not in st.session_state:
    st.session_state.is_running = False

live, hist = st.tabs(["Live Detection", "Violation History"])

with st.sidebar:
    st.header("⚙️ Configuration")
    weights = st.text_input("Person model weights", value=config.DEFAULT_MODEL_WEIGHTS)
    ppe_weights = st.text_input("PPE model weights", value=config.DEFAULT_PPE_MODEL_WEIGHTS)
    src_type = st.radio("Source", ["Upload video", "Webcam", "RTSP / URL"])
    camera = st.text_input("Camera name", value=config.DEFAULT_CAMERA_NAME)
    conf = st.slider("Person confidence", min_value=0.1, max_value=0.9, value=config.DEFAULT_CONFIDENCE, step=0.05)
    ppe_conf = st.slider("PPE confidence", min_value=0.1, max_value=0.9, value=config.DEFAULT_PPE_CONFIDENCE, step=0.05)
    assoc_threshold = st.slider("Association threshold", min_value=0.15, max_value=0.85, value=config.DEFAULT_ASSOCIATION_THRESHOLD, step=0.05)

    st.markdown("---")
    st.subheader("Temporal Decision Engine")
    window_size = st.slider("Window size (frames)", min_value=5, max_value=30, value=config.DEFAULT_TEMPORAL_WINDOW_SIZE, step=1)
    violation_ratio = st.slider("Violation ratio threshold", min_value=0.50, max_value=0.95, value=config.DEFAULT_VIOLATION_RATIO_THRESHOLD, step=0.05)
    min_obs_frames = st.slider("Min observable frames", min_value=2, max_value=15, value=config.DEFAULT_MIN_OBSERVABLE_FRAMES, step=1)
    
    st.markdown("---")
    st.subheader("Restricted Zone")
    use_zone = st.checkbox("Enable restricted zone", value=False)
    zone_txt = st.text_input("Zone points (fractions x,y;...)", value="0.6,0.2;0.95,0.2;0.95,0.9;0.6,0.9")
    
    st.markdown("---")
    st.subheader("Alerts")
    send = st.checkbox("Send Telegram alerts", value=False)
    if send and not config.has_telegram_credentials():
        st.caption("⚠️ Telegram credentials missing in .env. Alerts will be skipped.")

with live:
    uploaded_file = None
    webcam_idx = 0
    stream_url = ""

    if src_type == "Upload video":
        uploaded_file = st.file_uploader("Select video file", type=["mp4", "avi", "mov", "mkv"])
    elif src_type == "Webcam":
        webcam_idx = st.number_input("Webcam Device Index", min_value=0, max_value=10, value=0, step=1)
    else:
        stream_url = st.text_input("Stream URL (RTSP / HTTP / Video URL)", value="")

    # Zone validation
    parsed_zone = None
    if use_zone:
        points, err = parse_zone_polygon(zone_txt)
        if err:
            st.warning(f"Restricted zone disabled: {err}")
        else:
            parsed_zone = points

    col_btn1, col_btn2, col_spacer = st.columns([1, 1, 4])
    with col_btn1:
        start_btn = st.button("▶ Start", disabled=st.session_state.is_running, use_container_width=True)
    with col_btn2:
        stop_btn = st.button("⏹ Stop", disabled=not st.session_state.is_running, use_container_width=True)

    if start_btn:
        st.session_state.is_running = True
        st.rerun()

    if stop_btn:
        st.session_state.is_running = False
        st.rerun()

    # Layout placeholders for telemetry, worker metrics, PPE metrics, video view, and events
    metric_cols = st.columns(7)
    metric_active_workers = metric_cols[0].empty()
    metric_unique_workers = metric_cols[1].empty()
    metric_ppe_count = metric_cols[2].empty()
    metric_fps = metric_cols[3].empty()
    metric_frame = metric_cols[4].empty()
    metric_res = metric_cols[5].empty()
    metric_latency = metric_cols[6].empty()

    col_view, col_status = st.columns([3, 1])
    with col_view:
        view = st.empty()
    with col_status:
        worker_ppe_panel = st.empty()
    log_box = st.empty()

    # Active Stream Processing Loop
    if st.session_state.is_running:
        handler = VideoSourceHandler(
            src_type=src_type,
            uploaded_file=uploaded_file,
            webcam_index=webcam_idx,
            stream_url=stream_url
        )

        cap, open_err = handler.open()
        if open_err:
            st.error(f"Cannot start stream: {open_err}")
            st.session_state.is_running = False
            handler.cleanup()
        else:
            # Model existence check before initializing detector
            if not os.path.exists(weights):
                st.error(f"Person model file '{weights}' was not found. Please provide valid weights in the sidebar (e.g., 'yolov8n.pt').")
                st.session_state.is_running = False
                handler.cleanup()
            elif not os.path.exists(ppe_weights):
                st.error(f"PPE model file '{ppe_weights}' was not found. Please provide valid PPE weights in the sidebar (e.g., 'models/ppe_yolov8n_best.pt').")
                st.session_state.is_running = False
                handler.cleanup()
            else:
                try:
                    det = SafetyDetector(weights=weights, zone=parsed_zone, conf=conf, cooldown=config.DEFAULT_COOLDOWN)
                    det.reset_tracking()
                except Exception as e:
                    st.error(f"Error loading Person model '{weights}': {str(e)}")
                    st.session_state.is_running = False
                    handler.cleanup()
                    det = None

                ppe_det = None
                associator = None
                temporal_engine = None
                if det is not None:
                    try:
                        ppe_det = PPEDetector(weights=ppe_weights, conf=ppe_conf, device="cpu")
                        associator = WorkerPPEAssociator(min_threshold=assoc_threshold)
                        temporal_engine = TemporalViolationEngine(
                            window_size=window_size,
                            violation_ratio_threshold=violation_ratio,
                            min_observable_frames=min_obs_frames
                        )
                    except Exception as e:
                        st.error(f"Error initializing PPE & Temporal pipeline: {str(e)}")
                        st.session_state.is_running = False
                        handler.cleanup()

                if det is not None and ppe_det is not None and associator is not None and temporal_engine is not None:
                    events = []
                    frame_count = 0
                    prev_time = time.time()

                    try:
                        while st.session_state.is_running and cap.isOpened():
                            start_iter = time.time()
                            ok, frame = cap.read()
                            if not ok:
                                st.info("Video stream completed or reached end of file.")
                                break

                            frame_count += 1
                            h, w = frame.shape[:2]

                            # 1. Detection & ByteTrack tracking hook for workers
                            det_start = time.time()
                            frame, new, tracked_workers = det.process(frame)
                            person_det_latency_ms = (time.time() - det_start) * 1000

                            # 2. PPE Detection hook
                            ppe_start = time.time()
                            ppe_detections = ppe_det.detect(frame)
                            frame = ppe_det.annotate(frame, ppe_detections)
                            ppe_det_latency_ms = (time.time() - ppe_start) * 1000

                            # 3. Worker <-> PPE Association hook
                            assoc_start = time.time()
                            assoc_res = associator.associate(
                                workers=tracked_workers,
                                ppe_detections=ppe_detections,
                                frame_idx=frame_count,
                                timestamp=time.time()
                            )
                            frame = associator.annotate_frame(frame, assoc_res, show_connection_lines=True)
                            assoc_latency_ms = (time.time() - assoc_start) * 1000

                            # 4. Phase 5: Temporal Violation Decision Engine
                            temp_start = time.time()
                            temp_res = temporal_engine.process(
                                association_result=assoc_res,
                                frame_idx=frame_count,
                                timestamp=time.time()
                            )
                            frame = temporal_engine.annotate_frame(frame, temp_res)
                            temp_latency_ms = (time.time() - temp_start) * 1000

                            total_latency_ms = person_det_latency_ms + ppe_det_latency_ms + assoc_latency_ms + temp_latency_ms

                            # Record new violations (Phase 2 zone violations preserved)
                            for name, c, path in new:
                                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                db.log(ts, camera, name, c, path)
                                events.insert(0, f"{ts} — {name} ({c:.0%})")
                                if send:
                                    alerts.send_telegram(f"⚠️ {name} at {camera} ({ts})", path)

                            # Calculate instantaneous FPS
                            now = time.time()
                            fps = 1.0 / (now - prev_time) if (now - prev_time) > 0 else 0.0
                            prev_time = now

                            # Update Worker, PPE, & Telemetry Metrics
                            active_workers_count = len(tracked_workers)
                            unique_workers_count = len(det.unique_track_ids)
                            ppe_items_count = len(ppe_detections)

                            metric_active_workers.metric("Active Workers", f"{active_workers_count}")
                            metric_unique_workers.metric("Unique Workers", f"{unique_workers_count}")
                            metric_ppe_count.metric("PPE Detections", f"{ppe_items_count}")
                            metric_fps.metric("FPS", f"{fps:.1f}")
                            metric_frame.metric("Frame", f"#{frame_count}")
                            metric_res.metric("Resolution", f"{w}x{h}")
                            metric_latency.metric("Latency", f"{total_latency_ms:.1f} ms")

                            # Render annotated frame
                            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                            view.image(rgb_frame, use_container_width=True)

                            # Render Compact Worker PPE & Violation Status Panel
                            status_lines = ["### 👷 Worker Safety Status"]
                            if tracked_workers:
                                for wkr in tracked_workers:
                                    w_id = wkr.track_id
                                    w_summary = temp_res.worker_summaries.get(w_id, {})
                                    
                                    # Check confirmed or suspected violations for worker
                                    worker_confirmed = [v for v in temp_res.active_confirmed_violations if v.track_id == w_id]
                                    worker_suspected = [v for v in temp_res.active_suspected_violations if v.track_id == w_id]

                                    if worker_confirmed:
                                        badge = "🔴 **VIOLATION CONFIRMED**"
                                    elif worker_suspected:
                                        badge = "🟡 **SUSPECTED**"
                                    else:
                                        badge = "🟢 **COMPLIANT**"

                                    w_header = f"Worker #{w_id}" if w_id != -1 else "Worker (untracked)"
                                    status_lines.append(f"**{w_header}** — {badge}")

                                    for cat_label, cat_name in [("Helmet", "helmet"), ("Vest", "vest"), ("Gloves", "gloves"), ("Boots", "boots"), ("Goggles", "goggles")]:
                                        cat_data = w_summary.get(cat_name, {})
                                        st_val = cat_data.get("status", "NORMAL")
                                        ratio = cat_data.get("missing_ratio", 0.0)
                                        obs_cnt = cat_data.get("observable_count", 0)
                                        miss_cnt = cat_data.get("missing_count", 0)
                                        
                                        if st_val == ViolationStatus.CONFIRMED.value:
                                            icon = f"🔴 MISSING ({miss_cnt}/{obs_cnt})"
                                        elif st_val == ViolationStatus.SUSPECTED.value:
                                            icon = f"🟡 SUSPECTED ({miss_cnt}/{obs_cnt})"
                                        else:
                                            assoc_st = assoc_res.worker_statuses.get(w_id)
                                            if assoc_st and assoc_st.get_category_state(cat_name).state == PPEState.PRESENT:
                                                icon = "✓ PRESENT"
                                            else:
                                                icon = "— OK / UNKNOWN"

                                        status_lines.append(f"- {cat_label}: `{icon}`")
                                    status_lines.append("")
                            else:
                                status_lines.append("*No active workers in frame.*")
                            worker_ppe_panel.markdown("\n".join(status_lines))

                            if events:
                                log_box.markdown("**Recent Violations:**\n" + "\n".join([f"- {ev}" for ev in events[:5]]))

                    except Exception as loop_err:
                        st.error(f"Stream processing error: {str(loop_err)}")
                    finally:
                        handler.cleanup()
                        st.session_state.is_running = False

with hist:
    df = db.history()
    if df.empty:
        st.info("No violations recorded yet.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Total violations", len(df))
        c2.bar_chart(df["type"].value_counts())
        st.dataframe(df, use_container_width=True)
        st.download_button("Export CSV", df.to_csv(index=False), "violations.csv", mime="text/csv")
