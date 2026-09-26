"""
Webcam and RTSP camera frame capture manager.
"""

from typing import Optional
from vision.logger import logger
from vision.platform import IS_WINDOWS

try:
    import cv2
except ImportError:
    cv2 = None


class CameraCapture:
    def __init__(self, camera_index: int = 0):
        self.camera_index = camera_index
        self._cap = None

    def capture_frame(self) -> Optional[bytes]:
        """Capture single frame from local webcam."""
        if cv2 is None:
            logger.warning("[CameraCapture] OpenCV (cv2) is not installed.")
            return None
        cap = None
        try:
            # On Windows the default MSMF backend is slow to open and can fail on
            # some webcams; DirectShow (CAP_DSHOW) is far more reliable.
            if IS_WINDOWS:
                cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            else:
                cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                logger.warning(f"[CameraCapture] Could not open camera index {self.camera_index} (in use or no device).")
                return None
            ret, frame = cap.read()
            if not ret:
                return None
            ok, jpeg = cv2.imencode('.jpg', frame)
            if ok:
                return jpeg.tobytes()
            return None
        except Exception as e:
            logger.error(f"[CameraCapture] Failed to grab frame: {e}")
            return None
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass


camera_capture = CameraCapture()
