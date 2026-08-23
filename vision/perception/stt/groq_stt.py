"""
Groq Cloud STT Adapter using Whisper Large v3 Turbo with Multi-Key Failover (sub-250ms transcription).
"""

import asyncio
from io import BytesIO
from typing import List, Optional
import httpx
from vision.perception.stt.base import BaseSTT
from vision.config import config
from vision.logger import logger

try:
    from groq import AsyncGroq
except ImportError:
    AsyncGroq = None


DEFAULT_PROMPT = (
    "VISION AI assistant, JARVIS, Python, YouTube, WhatsApp, weather, browser, "
    "terminal, system, music, open, search, remember, schedule, mute, unmute, "
    "volume, battery, memory, notes, status, run, execute, college, hackathon."
)


class GroqSTT(BaseSTT):
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, prompt: Optional[str] = None):
        super().__init__(name="Groq-Whisper")
        keys = []
        if api_key:
            keys.append(api_key)
        if config.GROQ_API_KEY:
            keys.append(config.GROQ_API_KEY)
        keys.extend(config.GROQ_API_KEYS)
        self.api_keys: List[str] = list(dict.fromkeys([k for k in keys if k]))
        self.current_key_idx: int = 0
        self.model = model or config.VISION_STT_MODEL or "whisper-large-v3-turbo"
        self.prompt = prompt or DEFAULT_PROMPT
        self._clients = {}

    def _get_client_for_key(self, key: str) -> Optional[AsyncGroq]:
        if not AsyncGroq or not key:
            return None
        if key not in self._clients:
            self._clients[key] = AsyncGroq(
                api_key=key,
                timeout=httpx.Timeout(5.0, connect=2.0)
            )
        return self._clients[key]

    def _rotate_key(self):
        if len(self.api_keys) > 1:
            self.current_key_idx = (self.current_key_idx + 1) % len(self.api_keys)
            logger.info(f"[GroqSTT] Rotated to Groq API Key {self.current_key_idx + 1}/{len(self.api_keys)}")

    async def transcribe(self, audio_data: bytes, language: str = "en", filename: str = None, prompt: str = None) -> str:
        if not self.api_keys:
            raise RuntimeError("No Groq API keys configured for Speech-to-Text.")

        ext_filename = "input.webm"
        if filename and "." in filename:
            ext_part = filename.rsplit(".", 1)[-1].lower()
            ext_filename = f"input.{ext_part}"
        elif audio_data.startswith(b"RIFF"):
            ext_filename = "input.wav"
        elif audio_data.startswith(b"OggS"):
            ext_filename = "input.ogg"
        elif audio_data.startswith(b"\x1a\x45\xdf\xa3") or b"webm" in audio_data[:64] or b"matroska" in audio_data[:64]:
            ext_filename = "input.webm"

        prompt_text = prompt or self.prompt
        attempts = min(3, len(self.api_keys))

        for attempt in range(attempts):
            key = self.api_keys[self.current_key_idx % len(self.api_keys)]
            client = self._get_client_for_key(key)
            if not client:
                self._rotate_key()
                continue

            try:
                audio_file = BytesIO(audio_data)
                audio_file.name = ext_filename

                transcription = await client.audio.transcriptions.create(
                    file=audio_file,
                    model=self.model,
                    language=language if language and language != "auto" else None,
                    prompt=prompt_text,
                    temperature=0.0,
                    response_format="text"
                )
                text = str(transcription).strip()
                logger.debug(f"[GroqSTT] Transcribed ({len(audio_data)} bytes) -> '{text}'")
                return text

            except Exception as e:
                logger.warning(f"[GroqSTT] Key ...{key[-6:]} error: {e}. Rotating key.")
                self._rotate_key()
                if attempt == attempts - 1:
                    raise e

        raise RuntimeError("[GroqSTT] All Groq API key transcription attempts failed.")
