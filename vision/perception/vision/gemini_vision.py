"""
Gemini Multimodal Vision Processor for Screen and Camera image analysis.
Uses the latest supported Gemini models (gemini-flash-latest / gemini-2.5-flash).
"""

from typing import Optional, Dict, Any
from io import BytesIO
from vision.config import config
from vision.logger import logger

# Split optional deps: PIL and google-generativeai are independent packages, so a
# missing one must not null the other (otherwise vision breaks even when the
# present dependency would have worked).
try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None


class GeminiVisionAnalyzer:
    def __init__(self, api_key: Optional[str] = None):
        # Accept an explicit key, the single GEMINI_API_KEY, or the first entry
        # of the GEMINI_API_KEYS pool — otherwise the pool went unused.
        pool = getattr(config, "GEMINI_API_KEYS", None) or []
        self.api_key = api_key or config.GEMINI_API_KEY or (pool[0] if pool else None)
        if self.api_key and genai:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(model_name="gemini-flash-latest")
        else:
            self.model = None

    async def analyze_image(self, image_bytes: bytes, prompt: str = "Describe what you see on this screen or camera feed concisely.") -> str:
        """Send image bytes to Gemini Multimodal Vision API."""
        if not self.model or not Image:
            raise RuntimeError("Gemini API key or PIL not configured for Vision analysis.")

        try:
            pil_img = Image.open(BytesIO(image_bytes))
            # Always cap the network call: without a timeout a stalled Gemini
            # request hangs the vision coroutine indefinitely with no recovery.
            response = await self.model.generate_content_async(
                [prompt, pil_img], request_options={"timeout": 20}
            )
            # response.text raises ValueError when the model returns no usable
            # part (e.g. blocked by a safety filter). Handle that gracefully.
            text = self._extract_text(response)
            if not text:
                reason = self._blocked_reason(response)
                return f"Gemini returned no describable content{f' ({reason})' if reason else ''}."
            return text
        except Exception as e:
            logger.error(f"[GeminiVision] Analysis failed: {e}")
            raise e

    @staticmethod
    def _extract_text(response) -> str:
        """Safely pull text out of a Gemini response without tripping ValueError."""
        try:
            candidates = getattr(response, "candidates", None) or []
            parts = []
            for cand in candidates:
                content = getattr(cand, "content", None)
                for part in (getattr(content, "parts", None) or []):
                    t = getattr(part, "text", None)
                    if t:
                        parts.append(t)
            return "".join(parts).strip()
        except Exception:
            return ""

    @staticmethod
    def _blocked_reason(response) -> str:
        try:
            fb = getattr(response, "prompt_feedback", None)
            block = getattr(fb, "block_reason", None)
            return f"blocked: {block}" if block else ""
        except Exception:
            return ""


gemini_vision = GeminiVisionAnalyzer()
