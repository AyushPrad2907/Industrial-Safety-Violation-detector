import os
import time
import cv2
import streamlit as st
from datetime import datetime

import config
import db
import alerts
from detector import SafetyDetector
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
    weights = st.text_input("Model weights", value=config.DEFAULT_MODEL_WEIGHTS)
    src_type = st.radio("Source", ["Upload video", "Webcam", "RTSP / URL"])
    camera = st.text_input("Camera name", value=config.DEFAULT_CAMERA_NAME)
    conf = st.slider("Confidence", min_value=0.1, max_value=0.9, value=config.DEFAULT_CONFIDENCE, step=0.05)
    
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

    # Layout placeholders for telemetry, video view, and events
    metric_cols = st.columns(4)
    metric_fps = metric_cols[0].empty()
    metric_frame = metric_cols[1].empty()
    metric_res = metric_cols[2].empty()
    metric_latency = metric_cols[3].empty()

    view = st.empty()
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
                st.error(f"Model file '{weights}' was not found. Please provide valid weights in the sidebar (e.g., 'yolov8n.pt' or custom model).")
                st.session_state.is_running = False
                handler.cleanup()
            else:
                try:
                    det = SafetyDetector(weights=weights, zone=parsed_zone, conf=conf, cooldown=config.DEFAULT_COOLDOWN)
                except Exception as e:
                    st.error(f"Error loading model '{weights}': {str(e)}")
                    st.session_state.is_running = False
                    handler.cleanup()
                    det = None

                if det is not None:
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

                            # Inference and rule processing hook (preserving existing detector logic)
                            det_start = time.time()
                            frame, new = det.process(frame)
                            latency_ms = (time.time() - det_start) * 1000

                            # Record new violations
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

                            # Update Telemetry Metrics
                            metric_fps.metric("FPS", f"{fps:.1f}")
                            metric_frame.metric("Frame", f"#{frame_count}")
                            metric_res.metric("Resolution", f"{w}x{h}")
                            metric_latency.metric("Proc Latency", f"{latency_ms:.1f} ms")

                            # Render annotated frame
                            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                            view.image(rgb_frame, use_container_width=True)

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
