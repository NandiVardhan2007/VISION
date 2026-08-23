"""
Cartesia Neural TTS Provider with Microsoft Neural TTS Fallback.
Ultra-low latency hyper-realistic voice synthesis with zero-downtime multi-tier failover:
- Tier 1: Cartesia Sonic-2 Neural Voice (sub-150ms TTFT, expressive prosody)
- Tier 2: Microsoft Edge Neural TTS (unlimited credits, 100% uptime fallback)
"""

import asyncio
from typing import AsyncGenerator, List, Optional
import httpx
from vision.synthesis.base import BaseTTS
from vision.config import config
from vision.logger import logger

try:
    import edge_tts
except ImportError:
    edge_tts = None


class CartesiaTTS(BaseTTS):
    """
    Direct ultra-low latency Cartesia Neural TTS Engine with automatic Edge-TTS fallback.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None
    ):
        super().__init__(name="Cartesia-Sonic")
        self.api_keys: List[str] = list(config.CARTESIA_API_KEYS)
        if api_key and api_key not in self.api_keys:
            self.api_keys.insert(0, api_key)
        self.current_key_index: int = 0
        self.voice_id: str = voice_id or config.CARTESIA_VOICE_ID
        self.model_id: str = model_id or getattr(config, "CARTESIA_MODEL_ID", "sonic-2")
        self.base_url: str = "https://api.cartesia.ai/tts/bytes"
        self._client: Optional[httpx.AsyncClient] = None

    def _get_active_api_key(self) -> Optional[str]:
        if not self.api_keys:
            return config.CARTESIA_API_KEY
        return self.api_keys[self.current_key_index % len(self.api_keys)]

    def _rotate_api_key(self, permanent_failure: bool = False):
        if not self.api_keys:
            return
        if permanent_failure and len(self.api_keys) > 1:
            idx = self.current_key_index % len(self.api_keys)
            bad_key = self.api_keys.pop(idx)
            logger.warning(f"[CartesiaTTS] Permanently removed exhausted API key ...{bad_key[-6:]} ({len(self.api_keys)} key(s) remaining)")
            if self.current_key_index >= len(self.api_keys):
                self.current_key_index = 0
        elif len(self.api_keys) > 1:
            self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
            logger.info(f"[CartesiaTTS] Rotated to API Key index {self.current_key_index + 1}/{len(self.api_keys)}")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=3.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10, keepalive_expiry=60.0)
            )
        return self._client

    async def _synthesize_edge_fallback(self, text: str) -> bytes:
        """Fallback synthesis using Microsoft Edge Neural TTS."""
        if not edge_tts:
            logger.error("[CartesiaTTS] edge_tts package not available for fallback.")
            return b""
        try:
            voice = getattr(config, "EDGE_TTS_VOICE", "en-US-GuyNeural")
            communicate = edge_tts.Communicate(text, voice)
            audio_chunks = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_chunks.append(chunk["data"])
            audio_bytes = b"".join(audio_chunks)
            logger.info(f"[CartesiaTTS] Fallback to EdgeTTS synthesized {len(audio_bytes)} bytes audio.")
            return audio_bytes
        except Exception as e:
            logger.error(f"[CartesiaTTS] EdgeTTS fallback synthesis failed: {e}")
            return b""

    async def synthesize(self, text: str, voice_id: Optional[str] = None) -> bytes:
        """Synthesize text to audio bytes using Cartesia Sonic-2 with Edge-TTS failover."""
        if not text or not text.strip():
            return b""

        active_voice = voice_id or self.voice_id
        speed = getattr(config, "CARTESIA_SPEED", "normal")
        emotion = getattr(config, "CARTESIA_EMOTION", ["positivity:high"])

        attempts = max(1, len(self.api_keys))
        client = await self._get_client()

        for attempt in range(attempts):
            api_key = self._get_active_api_key()
            if not api_key:
                break

            headers = {
                "X-API-Key": api_key,
                "Cartesia-Version": "2024-06-10",
                "Content-Type": "application/json"
            }

            payload = {
                "model_id": self.model_id,
                "transcript": text.strip(),
                "voice": {
                    "mode": "id",
                    "id": active_voice
                },
                "output_format": {
                    "container": "wav",
                    "encoding": "pcm_s16le",
                    "sample_rate": 24000
                },
                "language": "en"
            }

            # Optional voice controls
            voice_controls = {}
            if speed and speed != "normal":
                voice_controls["speed"] = speed
            if emotion and isinstance(emotion, list) and len(emotion) > 0:
                voice_controls["emotion"] = emotion
            if voice_controls:
                payload["voice"]["__experimental_controls"] = voice_controls

            try:
                response = await client.post(self.base_url, headers=headers, json=payload)
                if response.status_code == 200:
                    audio_bytes = response.content
                    logger.debug(f"[CartesiaTTS] Synthesized '{text[:30]}...' -> {len(audio_bytes)} bytes WAV.")
                    return audio_bytes

                # Handle quota / rate limit / bad key errors with rotation
                if response.status_code in (401, 402):
                    logger.warning(
                        f"[CartesiaTTS] Key returned HTTP {response.status_code}. Pruning dead key."
                    )
                    self._rotate_api_key(permanent_failure=True)
                    continue
                elif response.status_code == 429:
                    logger.warning(f"[CartesiaTTS] Rate limited (429). Rotating key.")
                    self._rotate_api_key(permanent_failure=False)
                    continue
                else:
                    response.raise_for_status()

            except httpx.HTTPStatusError as e:
                logger.warning(f"[CartesiaTTS] HTTP error ({e.response.status_code}): {e}")
                self._rotate_api_key(permanent_failure=(e.response.status_code in (401, 402)))
            except Exception as e:
                logger.error(f"[CartesiaTTS] Synthesis request error: {e}")
                self._rotate_api_key(permanent_failure=False)

        # Fallback to Edge-TTS if Cartesia keys are exhausted or rate limited
        logger.warning("[CartesiaTTS] Cartesia key pool exhausted. Engaging Microsoft Edge Neural TTS fallback.")
        return await self._synthesize_edge_fallback(text.strip())

    async def stream_synthesize(self, text: str) -> AsyncGenerator[bytes, None]:
        """Stream synthesized audio bytes."""
        audio_bytes = await self.synthesize(text)
        if audio_bytes:
            yield audio_bytes

    async def close(self):
        """Close underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Global Cartesia TTS singleton
cartesia_tts = CartesiaTTS()
