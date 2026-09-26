"""
Desktop Screen Capture for Multimodal Vision perception.
"""

from io import BytesIO
from typing import Optional
from vision.logger import logger

try:
    from PIL import ImageGrab, Image
except ImportError:
    ImageGrab = None
    Image = None

try:
    import mss as _mss
except ImportError:
    _mss = None


class ScreenCapture:
    @staticmethod
    def _grab_raw():
        """Grab a full-screen PIL image, trying PIL then mss (Linux/Wayland-friendly)."""
        # PIL.ImageGrab works on Windows/macOS but needs X11 on Linux and fails
        # on many headless/Wayland setups; fall back to mss there.
        if ImageGrab is not None:
            try:
                return ImageGrab.grab()
            except Exception as e:
                logger.debug(f"[ScreenCapture] ImageGrab.grab() failed ({e}); trying mss fallback.")
        if _mss is not None and Image is not None:
            with _mss.mss() as sct:
                monitor = sct.monitors[0]  # full virtual screen
                shot = sct.grab(monitor)
                return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        return None

    @staticmethod
    def capture_screen(quality: int = 85, resize_max_dim: int = 1280) -> Optional[bytes]:
        """Capture screenshot and return JPEG bytes."""
        if Image is None or (ImageGrab is None and _mss is None):
            logger.warning("[ScreenCapture] No screen-capture backend available (install Pillow, or mss on Linux).")
            return None
        try:
            img = ScreenCapture._grab_raw()
            if img is None:
                logger.error("[ScreenCapture] All screen-capture backends failed.")
                return None
            if max(img.size) > resize_max_dim:
                scale = resize_max_dim / max(img.size)
                new_size = (int(img.width * scale), int(img.height * scale))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            buffer = BytesIO()
            img.convert("RGB").save(buffer, format="JPEG", quality=quality)
            logger.debug(f"[ScreenCapture] Screen snapshot taken ({len(buffer.getvalue())} bytes).")
            return buffer.getvalue()
        except Exception as e:
            logger.error(f"[ScreenCapture] Failed to grab screen: {e}")
            return None


screen_capture = ScreenCapture()
