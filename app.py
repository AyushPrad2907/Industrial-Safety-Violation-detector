import streamlit as st, cv2, tempfile
from datetime import datetime
from detector import SafetyDetector
import db, alerts

st.set_page_config(page_title="Industrial Safety Violation Detector", layout="wide")
st.title("🦺 Industrial Safety Violation Detector")
live, hist = st.tabs(["Live Detection", "Violation History"])

with st.sidebar:
    st.header("Settings")
    weights = st.text_input("Model weights", "best.pt")
    src_type = st.radio("Source", ["Upload video", "Webcam", "RTSP / URL"])
    camera = st.text_input("Camera name", "Cam-1")
    conf = st.slider("Confidence", 0.1, 0.9, 0.4)
    use_zone = st.checkbox("Restricted zone")
    zone_txt = st.text_input("Zone points (fractions x,y;...)", "0.6,0.2;0.95,0.2;0.95,0.9;0.6,0.9")
    send = st.checkbox("Send Telegram alerts")

with live:
    cap_src = None
    if src_type == "Upload video":
        f = st.file_uploader("Video", type=["mp4", "avi", "mov"])
        if f:
            t = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4"); t.write(f.read()); cap_src = t.name
    elif src_type == "Webcam":
        cap_src = 0
    else:
        u = st.text_input("Stream URL"); cap_src = u or None

    if st.button("▶ Start", disabled=cap_src is None):
        zone = [tuple(map(float, p.split(","))) for p in zone_txt.split(";")] if use_zone else None
        det = SafetyDetector(weights, zone, conf)
        cap, view, log_box = cv2.VideoCapture(cap_src), st.empty(), st.empty()
        events = []
        while cap.isOpened():
            ok, frame = cap.read()
            if not ok:
                break
            frame, new = det.process(frame)
            for name, c, path in new:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                db.log(ts, camera, name, c, path)
                events.insert(0, f"{ts} — {name} ({c:.0%})")
                if send:
                    alerts.send_telegram(f"⚠️ {name} at {camera} ({ts})", path)
            view.image(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), use_container_width=True)
            log_box.write("\n\n".join(events[:5]))
        cap.release()
        st.success("Stream ended")

with hist:
    df = db.history()
    if df.empty:
        st.info("No violations recorded yet.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Total violations", len(df))
        c2.bar_chart(df["type"].value_counts())
        st.dataframe(df, use_container_width=True)
        st.download_button("Export CSV", df.to_csv(index=False), "violations.csv")
