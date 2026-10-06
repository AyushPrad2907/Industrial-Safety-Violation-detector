import os
import cv2
import tempfile
from typing import Tuple, Optional, Any

class VideoSourceHandler:
    """
    Encapsulates video source creation, validation, and lifecycle management.
    Handles uploaded files (with cleanup), webcams, and RTSP streams.
    """
    def __init__(self, src_type: str, uploaded_file=None, webcam_index: int = 0, stream_url: str = ""):
        self.src_type = src_type
        self.uploaded_file = uploaded_file
        self.webcam_index = webcam_index
        self.stream_url = stream_url.strip() if stream_url else ""
        self.temp_file_path: Optional[str] = None
        self.cap: Optional[cv2.VideoCapture] = None

    def open(self) -> Tuple[Optional[cv2.VideoCapture], Optional[str]]:
        """
        Attempts to open the requested video source.
        Returns:
            (cv2.VideoCapture, None) on success
            (None, error_message) on failure
        """
        
        if self.src_type == "Upload video":
            if self.uploaded_file is None:
                return None, "No video file uploaded."
            try:
                # Create a temporary file and write uploaded buffer to disk
                suffix = os.path.splitext(self.uploaded_file.name)[-1]
                if not suffix:
                    suffix = ".mp4"
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                tmp.write(self.uploaded_file.getbuffer())
                tmp.close()
                self.temp_file_path = tmp.name

                cap = cv2.VideoCapture(self.temp_file_path)
                if not cap.isOpened():
                    self.cleanup()
                    return None, f"Failed to open uploaded video file '{self.uploaded_file.name}'. Ensure it is a valid video format."
                self.cap = cap
                return cap, None
            except Exception as e:
                self.cleanup()
                return None, f"Error processing uploaded video: {str(e)}"

        elif self.src_type == "Webcam":
            try:
                idx = int(self.webcam_index)
            except ValueError:
                return None, f"Invalid webcam index: {self.webcam_index}"
            
            cap = cv2.VideoCapture(idx)
            if not cap.isOpened():
                return None, f"Unable to access Webcam at index {idx}. Check if the camera is connected or in use by another application."
            self.cap = cap
            return cap, None

        elif self.src_type == "RTSP / URL":
            if not self.stream_url:
                return None, "Stream URL cannot be empty."
            
            cap = cv2.VideoCapture(self.stream_url)
            if not cap.isOpened():
                return None, f"Unable to connect to stream URL: '{self.stream_url}'. Please check stream reachability and network credentials."
            self.cap = cap
            return cap, None

        return None, f"Unknown source type: {self.src_type}"

    def cleanup(self):
        """Releases the capture object and unlinks any temporary files created."""
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

        if self.temp_file_path and os.path.exists(self.temp_file_path):
            try:
                os.remove(self.temp_file_path)
            except Exception:
                pass
            self.temp_file_path = None
