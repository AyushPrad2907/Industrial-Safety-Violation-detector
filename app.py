import os
import time
import cv2
import pandas as pd
import streamlit as st
from datetime import datetime

import config
import db
import database
import alerts
from detector import SafetyDetector
from ppe_detector import PPEDetector
from ppe_association import WorkerPPEAssociator, PPEState
from temporal_engine import TemporalViolationEngine, ViolationStatus
from telegram_alert import TelegramAlertManager
from violation_handler import ViolationHandler
from zone_utils import parse_zone_polygon
from video_source import VideoSourceHandler
from dashboard_utils import (
    format_violation_type,
    format_severity,
    format_ppe_status,
    load_violation_history,
    filter_violations,
    export_violations_csv,
    check_evidence_file,
    SEVERITY_BADGES,
)

# Page configuration
st.set_page_config(
    page_title="Industrial Safety Violation Detector",
    page_icon="🦺",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Header
st.markdown("""
<div style="padding: 0.5rem 0 1rem 0;">
    <h2 style="margin: 0;">🦺 INDUSTRIAL SAFETY MONITORING SYSTEM</h2>
    <p style="color: #6c757d; margin: 0; font-size: 1.05rem;">Real-Time PPE Compliance & Violation Detection</p>
</div>
""", unsafe_allow_html=True)

# Session state initialization
if "is_running" not in st.session_state:
    st.session_state.is_running = False
if "reset_trigger" not in st.session_state:
    st.session_state.reset_trigger = False
if "last_db_refresh" not in st.session_state:
    st.session_state.last_db_refresh = 0.0
if "cached_violations" not in st.session_state:
    st.session_state.cached_violations = []

# ==============================================================================
# SIDEBAR / DEMO SETTINGS & SYSTEM STATUS
# ==============================================================================
with st.sidebar:
    st.header("🎛️ Demo Controls")
    
    src_type = st.radio("Video Source", ["Upload video", "Webcam", "RTSP / URL"])
    camera = st.text_input("Camera Name", value=config.DEFAULT_CAMERA_NAME)
    
    st.markdown("---")
    st.subheader("🖥️ System Status")
    
    # Model existence checks for simple status indicators
    person_model_ok = os.path.exists(config.DEFAULT_MODEL_WEIGHTS)
    ppe_model_ok = os.path.exists(config.DEFAULT_PPE_MODEL_WEIGHTS)
    db_ok = True
    try:
        database.init_db()
    except Exception:
        db_ok = False
        
    status_person = "🟢 Enabled" if person_model_ok else "🔴 Missing"
    status_ppe = "🟢 Enabled" if ppe_model_ok else "🔴 Missing"
    status_tracking = "🟢 Enabled (ByteTrack)"
    status_temporal = "🟢 Enabled (Temporal Engine)"
    status_db = "🟢 Enabled (SQLite)" if db_ok else "🔴 Error"
    
    # Telegram status without exposing credentials
    tg_configured = config.has_telegram_credentials()
    tg_enabled = config.TELEGRAM_ALERTS_ENABLED
    if tg_enabled and tg_configured:
        status_tg = "🟢 Enabled"
    elif tg_enabled and not tg_configured:
        status_tg = "🟡 Credentials Missing"
    else:
        status_tg = "🟡 Disabled"
        
    st.markdown(f"""
- **Person Detector:** {status_person}
- **PPE Detector:** {status_ppe}
- **Tracking:** {status_tracking}
- **Temporal Engine:** {status_temporal}
- **Database:** {status_db}
- **Telegram Alerts:** {status_tg}
    """)
    
    # Alert toggle for demo
    send_alerts = st.checkbox("Send Telegram alerts during demo", value=False)
    if send_alerts and not tg_configured:
        st.caption("⚠️ Telegram credentials not configured in .env. Alerts will be safely skipped.")

    st.markdown("---")
    st.subheader("⚠️ Restricted Zone")
    use_zone = st.checkbox("Enable restricted zone", value=False)
    zone_txt = st.text_input("Zone points (fractions x,y;...)", value="0.6,0.2;0.95,0.2;0.95,0.9;0.6,0.9")

    st.markdown("---")
    st.subheader("🔄 Session Control")
    if st.button("Reset Session", use_container_width=True):
        st.session_state.is_running = False
        st.session_state.reset_trigger = True
        st.success("Session reset. Live tracking state cleared. Historical violations are preserved.")
        st.rerun()
    st.caption("ℹ️ Reset Session clears live tracking state. Historical violations are preserved.")


# ==============================================================================
# TOP SUMMARY METRICS
# ==============================================================================
# Helper to fetch violations with lightweight caching (refresh at most once per 2 seconds)
def get_cached_violations_list(force_refresh: bool = False):
    now = time.time()
    if force_refresh or (now - st.session_state.last_db_refresh > 2.0) or not st.session_state.cached_violations:
        st.session_state.cached_violations = load_violation_history(limit=500)
        st.session_state.last_db_refresh = now
    return st.session_state.cached_violations

all_cached_violations = get_cached_violations_list()
total_violations_count = len(all_cached_violations)
critical_violations_count = sum(1 for v in all_cached_violations if str(v.get("severity", "")).upper() == "CRITICAL")

top_col1, top_col2, top_col3, top_col4, top_col5, top_col6 = st.columns(6)
top_active_workers = top_col1.empty()
top_total_violations = top_col2.empty()
top_critical_violations = top_col3.empty()
top_fps = top_col4.empty()
top_frame = top_col5.empty()
top_latency = top_col6.empty()

# Initialize top metrics with default values
top_active_workers.metric("Active Workers", "0")
top_total_violations.metric("Violations", f"{total_violations_count}")
top_critical_violations.metric("Critical Violations", f"{critical_violations_count}")
top_fps.metric("System FPS", "0.0")
top_frame.metric("Current Frame", "—")
top_latency.metric("Latency", "—")

st.markdown("---")

# Main Navigation Tabs
tab_live, tab_compliance, tab_history = st.tabs(["📺 Live Monitoring", "🛡️ PPE Compliance", "📋 Violation History"])

# ==============================================================================
# TAB 1: LIVE MONITORING
# ==============================================================================
with tab_live:
    uploaded_file = None
    webcam_idx = 0
    stream_url = ""

    src_col, ctrl_col = st.columns([3, 2])
    with src_col:
        if src_type == "Upload video":
            uploaded_file = st.file_uploader("Select video file", type=["mp4", "avi", "mov", "mkv"])
        elif src_type == "Webcam":
            webcam_idx = st.number_input("Webcam Device Index", min_value=0, max_value=10, value=0, step=1)
        else:
            stream_url = st.text_input("Stream URL (RTSP / HTTP / Video URL)", value="")
            
    with ctrl_col:
        st.write("") # spacing
        st.write("")
        c_btn1, c_btn2 = st.columns(2)
        with c_btn1:
            start_btn = st.button("▶ Start Monitoring", disabled=st.session_state.is_running, use_container_width=True)
        with c_btn2:
            stop_btn = st.button("⏹ Stop Monitoring", disabled=not st.session_state.is_running, use_container_width=True)

    if start_btn:
        st.session_state.is_running = True
        st.rerun()

    if stop_btn:
        st.session_state.is_running = False
        st.rerun()

    # Zone parsing
    parsed_zone = None
    if use_zone:
        points, err = parse_zone_polygon(zone_txt)
        if err:
            st.warning(f"Restricted zone disabled: {err}")
        else:
            parsed_zone = points

    # Live monitoring display columns: Video on Left, Worker Safety Status on Right
    live_video_col, worker_safety_col = st.columns([3, 2])
    with live_video_col:
        st.subheader("📹 Live Video Feed")
        video_view = st.empty()
    with worker_safety_col:
        st.subheader("👷 Worker Safety Status")
        worker_safety_panel = st.empty()
        
    recent_events_box = st.empty()

    # Live Execution Loop
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
            weights = config.DEFAULT_MODEL_WEIGHTS
            ppe_weights = config.DEFAULT_PPE_MODEL_WEIGHTS

            if not os.path.exists(weights):
                st.error(f"Person model file '{weights}' was not found.")
                st.session_state.is_running = False
                handler.cleanup()
            elif not os.path.exists(ppe_weights):
                st.error(f"PPE model file '{ppe_weights}' was not found.")
                st.session_state.is_running = False
                handler.cleanup()
            else:
                try:
                    det = SafetyDetector(
                        weights=weights,
                        zone=parsed_zone,
                        conf=config.DEFAULT_CONFIDENCE,
                        cooldown=config.DEFAULT_COOLDOWN
                    )
                    det.reset_tracking()
                    ppe_det = PPEDetector(
                        weights=ppe_weights,
                        conf=config.DEFAULT_PPE_CONFIDENCE,
                        device="cpu"
                    )
                    associator = WorkerPPEAssociator(min_threshold=config.DEFAULT_ASSOCIATION_THRESHOLD)
                    temporal_engine = TemporalViolationEngine(
                        window_size=config.DEFAULT_TEMPORAL_WINDOW_SIZE,
                        violation_ratio_threshold=config.DEFAULT_VIOLATION_RATIO_THRESHOLD,
                        min_observable_frames=config.DEFAULT_MIN_OBSERVABLE_FRAMES
                    )
                    alert_mgr = TelegramAlertManager(enabled=send_alerts)
                    violation_handler = ViolationHandler(alert_manager=alert_mgr)
                except Exception as init_err:
                    st.error(f"Initialization error: {init_err}")
                    st.session_state.is_running = False
                    handler.cleanup()
                    det = None

                if det is not None:
                    events = []
                    frame_count = 0
                    prev_time = time.time()

                    try:
                        while st.session_state.is_running and cap.isOpened():
                            ok, frame = cap.read()
                            if not ok:
                                st.info("Video stream completed or reached end of file.")
                                break

                            frame_count += 1
                            h, w = frame.shape[:2]

                            # 1. Person Detection & ByteTrack
                            det_start = time.time()
                            frame, new_zone_violations, tracked_workers = det.process(frame)
                            person_det_latency_ms = (time.time() - det_start) * 1000

                            # 2. PPE Detection
                            ppe_start = time.time()
                            ppe_detections = ppe_det.detect(frame)
                            frame = ppe_det.annotate(frame, ppe_detections)
                            ppe_det_latency_ms = (time.time() - ppe_start) * 1000

                            # 3. PPE Association
                            assoc_start = time.time()
                            assoc_res = associator.associate(
                                workers=tracked_workers,
                                ppe_detections=ppe_detections,
                                frame_idx=frame_count,
                                timestamp=time.time()
                            )
                            frame = associator.annotate_frame(frame, assoc_res, show_connection_lines=True)
                            assoc_latency_ms = (time.time() - assoc_start) * 1000

                            # 4. Temporal Violation Engine
                            temp_start = time.time()
                            temp_res = temporal_engine.process(
                                association_result=assoc_res,
                                frame_idx=frame_count,
                                timestamp=time.time()
                            )
                            frame = temporal_engine.annotate_frame(frame, temp_res)
                            temp_latency_ms = (time.time() - temp_start) * 1000

                            # 5. Confirmed Violation Handling
                            for newly_confirmed_event in temp_res.newly_emitted_events:
                                if newly_confirmed_event.status == ViolationStatus.CONFIRMED:
                                    violation_handler.handle_violation(
                                        event=newly_confirmed_event,
                                        frame=frame
                                    )
                                    ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    readable_vtype = format_violation_type(newly_confirmed_event.violation_type)
                                    events.insert(0, f"{ts_str} — {readable_vtype} (Worker #{newly_confirmed_event.track_id})")

                            # Legacy zone violations
                            for name, c, path in new_zone_violations:
                                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                db.log(ts, camera, name, c, path)
                                events.insert(0, f"{ts} — {name} ({c:.0%})")
                                if send_alerts:
                                    alerts.send_telegram(f"⚠️ {name} at {camera} ({ts})", path)

                            # Latency & Instantaneous FPS
                            total_latency_ms = person_det_latency_ms + ppe_det_latency_ms + assoc_latency_ms + temp_latency_ms
                            now = time.time()
                            fps = 1.0 / (now - prev_time) if (now - prev_time) > 0 else 0.0
                            prev_time = now

                            # Update Top Metrics
                            active_workers_count = len(tracked_workers)
                            top_active_workers.metric("Active Workers", f"{active_workers_count}")
                            top_fps.metric("System FPS", f"{fps:.1f}")
                            top_frame.metric("Current Frame", f"#{frame_count}")
                            top_latency.metric("Latency", f"{total_latency_ms:.1f} ms")

                            # Render annotated video frame
                            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                            video_view.image(rgb_frame, use_container_width=True)

                            # PART D: Worker Safety Panel (Compliant with Phase 5 & 7 states)
                            status_lines = []
                            if tracked_workers:
                                for wkr in tracked_workers:
                                    w_id = wkr.track_id
                                    w_summary = temp_res.worker_summaries.get(w_id, {})

                                    # Worker temporal violation state
                                    worker_confirmed = [v for v in temp_res.active_confirmed_violations if v.track_id == w_id]
                                    worker_suspected = [v for v in temp_res.active_suspected_violations if v.track_id == w_id]

                                    if worker_confirmed:
                                        badge = "🔴 **CONFIRMED VIOLATION**"
                                    elif worker_suspected:
                                        badge = "🟡 **SUSPECTED**"
                                    else:
                                        badge = "🟢 **NORMAL / COMPLIANT**"

                                    w_header = f"Worker #{w_id}" if w_id != -1 else "Worker (untracked)"
                                    status_lines.append(f"#### {w_header} — {badge}")

                                    # PPE Status Table
                                    status_lines.append("| PPE Item | Association State | Temporal Status |")
                                    status_lines.append("| :--- | :--- | :--- |")

                                    for cat_label, cat_name in [("Helmet", "helmet"), ("Vest", "vest"), ("Gloves", "gloves"), ("Boots", "boots"), ("Goggles", "goggles")]:
                                        cat_data = w_summary.get(cat_name, {})
                                        st_val = cat_data.get("status", "NORMAL")
                                        obs_cnt = cat_data.get("observable_count", 0)
                                        miss_cnt = cat_data.get("missing_count", 0)

                                        # PPE Association State
                                        assoc_st = assoc_res.worker_statuses.get(w_id)
                                        if assoc_st:
                                            raw_state = assoc_st.get_category_state(cat_name).state
                                            assoc_display = format_ppe_status(raw_state)
                                        else:
                                            assoc_display = "❓ UNKNOWN"

                                        # Temporal Decision
                                        if st_val == ViolationStatus.CONFIRMED.value:
                                            temp_display = f"🔴 Confirmed Missing ({miss_cnt}/{obs_cnt})"
                                        elif st_val == ViolationStatus.SUSPECTED.value:
                                            temp_display = f"🟡 Suspected Missing ({miss_cnt}/{obs_cnt})"
                                        elif st_val == ViolationStatus.RESOLVED.value:
                                            temp_display = "🟢 Resolved"
                                        else:
                                            temp_display = "Normal"

                                        status_lines.append(f"| **{cat_label}** | {assoc_display} | {temp_display} |")

                                    status_lines.append("")
                            else:
                                status_lines.append("ℹ️ *No active workers detected.*")

                            worker_safety_panel.markdown("\n".join(status_lines))

                            if events:
                                recent_events_box.markdown("**Recent Confirmed Events:**\n" + "\n".join([f"- {ev}" for ev in events[:5]]))

                    except Exception as loop_err:
                        st.error(f"Stream processing error: {str(loop_err)}")
                    finally:
                        handler.cleanup()
                        st.session_state.is_running = False

# ==============================================================================
# TAB 2: PPE COMPLIANCE SUMMARY
# ==============================================================================
with tab_compliance:
    st.subheader("🛡️ PPE Compliance Overview")
    st.caption("Aggregated compliance breakdown across all recorded confirmed violations and requirements.")

    comp_violations = get_cached_violations_list(force_refresh=True)
    if not comp_violations:
        st.info("No confirmed safety violations recorded. Safe operational status maintained.")
    else:
        # Category compliance summary
        cat_counts = {
            "Helmet": sum(1 for v in comp_violations if "HELMET" in str(v.get("violation_type", ""))),
            "Vest": sum(1 for v in comp_violations if "VEST" in str(v.get("violation_type", ""))),
            "Gloves": sum(1 for v in comp_violations if "GLOVES" in str(v.get("violation_type", ""))),
            "Boots": sum(1 for v in comp_violations if "BOOTS" in str(v.get("violation_type", ""))),
            "Goggles": sum(1 for v in comp_violations if "GOGGLES" in str(v.get("violation_type", ""))),
        }

        col_c1, col_c2, col_c3, col_c4, col_c5 = st.columns(5)
        cols_list = [col_c1, col_c2, col_c3, col_c4, col_c5]
        for idx, (cat_name, count) in enumerate(cat_counts.items()):
            cols_list[idx].metric(f"{cat_name} Violations", f"{count}")

        st.markdown("---")
        st.subheader("📊 Violation Breakdown by Equipment")
        df_summary = pd.DataFrame(list(cat_counts.items()), columns=["PPE Category", "Violation Count"])
        st.bar_chart(df_summary.set_index("PPE Category"))

# ==============================================================================
# TAB 3: VIOLATION HISTORY, FILTERS, EVIDENCE & CSV EXPORT
# ==============================================================================
with tab_history:
    st.subheader("📋 Confirmed Violation History")
    st.caption("SQLite-persisted records from Phase 6 with evidence snapshot links.")

    # Refresh button
    col_ref, col_exp = st.columns([1, 4])
    with col_ref:
        if st.button("🔄 Refresh History", use_container_width=True):
            get_cached_violations_list(force_refresh=True)
            st.rerun()

    raw_history = get_cached_violations_list()

    if not raw_history:
        st.info("No confirmed PPE violations recorded yet in SQLite database.")
    else:
        # Unique values for filters
        available_severities = ["All", "Critical", "High", "Medium", "Low"]
        available_types = ["All", "Missing Helmet", "Missing Vest", "Missing Gloves", "Missing Boots", "Missing Goggles"]
        available_workers = ["All"] + sorted(list({str(v.get("track_id")) for v in raw_history if v.get("track_id") is not None}))

        # PART G: Filter controls
        st.markdown("#### 🔍 Filter Violations")
        f_col1, f_col2, f_col3 = st.columns(3)
        with f_col1:
            sel_severity = st.selectbox("Severity", available_severities)
        with f_col2:
            sel_vtype = st.selectbox("Violation Type", available_types)
        with f_col3:
            sel_worker = st.selectbox("Worker ID", available_workers)

        # Apply in-memory filtering
        filtered_records = filter_violations(
            violations=raw_history,
            severity_filter=sel_severity,
            violation_type_filter=sel_vtype,
            worker_id_filter=sel_worker
        )

        st.markdown(f"**Showing {len(filtered_records)} of {len(raw_history)} violations**")

        # PART I: CSV Export Button
        csv_data = export_violations_csv(filtered_records)
        st.download_button(
            label="📥 Download Violation History CSV",
            data=csv_data,
            file_name=f"violation_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=False
        )

        st.markdown("---")

        # PART F: Violation Table
        table_rows = []
        for v in filtered_records:
            table_rows.append({
                "Timestamp": v.get("timestamp"),
                "Worker ID": f"#{v.get('track_id')}",
                "Violation": format_violation_type(v.get("violation_type")),
                "Severity": format_severity(v.get("severity")),
                "Decision Score": f"{float(v.get('decision_score', 0.0)):.2f}",
                "Zone": "Yes" if v.get("is_zone_violation") else "No",
                "Evidence": "Available" if check_evidence_file(v.get("evidence_path")) else "Unavailable",
                "Event ID": v.get("event_id"),
            })

        if table_rows:
            df_table = pd.DataFrame(table_rows)
            st.dataframe(df_table, use_container_width=True)

        # PART H: Evidence Preview Accordion
        st.markdown("---")
        st.subheader("🖼️ Evidence Snapshot Preview")
        st.caption("Select a violation below to inspect captured worker evidence.")

        for v in filtered_records[:20]:  # Limit preview list to top 20 for optimal responsiveness
            event_id = v.get("event_id")
            w_id = v.get("track_id")
            v_type = format_violation_type(v.get("violation_type"))
            sev = format_severity(v.get("severity"))
            ts = v.get("timestamp")
            evi_path = v.get("evidence_path")

            badge = SEVERITY_BADGES.get(sev, sev)
            exp_title = f"{ts} | Worker #{w_id} | {v_type} | {badge}"

            with st.expander(exp_title):
                e_col1, e_col2 = st.columns([2, 1])
                with e_col1:
                    if check_evidence_file(evi_path):
                        st.image(evi_path, caption=f"Evidence for {event_id} (Worker #{w_id})", use_container_width=True)
                    else:
                        st.warning("Evidence file unavailable.")
                with e_col2:
                    st.markdown(f"""
- **Event ID:** `{event_id}`
- **Worker ID:** `#{w_id}`
- **Violation:** {v_type}
- **Severity:** {sev}
- **Decision Score:** `{float(v.get('decision_score', 0.0)):.2f}`
- **Missing Ratio:** `{float(v.get('missing_ratio', 0.0)):.1%}`
- **Observed Frames:** `{v.get('observable_frames')}`
- **Restricted Zone:** {'Yes' if v.get('is_zone_violation') else 'No'}
- **Message:** {v.get('message', 'N/A')}
                    """)

    # Legacy Restricted Zone Violations
    st.markdown("---")
    st.subheader("⚠️ Legacy Restricted Zone Violations")
    df_legacy = db.history()
    if df_legacy.empty:
        st.info("No legacy restricted zone violations recorded.")
    else:
        st.dataframe(df_legacy, use_container_width=True)
