"""
Hands-Free Local Wake-Word Engine for VISION AI OS.
Provides continuous ambient listening with local zero-latency openWakeWord ONNX
inference. The trigger phrase(s) come from config.VISION_WAKE_WORDS; the shipped
openWakeWord pretrained models are "hey_jarvis", "alexa", and "hey_mycroft"
(there is no pretrained "hey_vision" model), so "Hey Jarvis" is the default.
"""

import time
from typing import Optional, List, Dict
from vision.logger import logger
from vision.config import config

try:
    import numpy as np
except ImportError:
    np = None

try:
    import sounddevice as sd
except ImportError:
    sd = None

try:
    from openwakeword.model import Model as OWWModel
except ImportError:
    OWWModel = None


class WakeWordEngine:
    def __init__(self, target_phrases: Optional[List[str]] = None, threshold: Optional[float] = None):
        self.target_phrases = target_phrases or list(config.VISION_WAKE_WORDS)
        self.threshold = threshold if threshold is not None else config.VISION_WAKE_WORD_THRESHOLD
        self.sample_rate = 16000
        self.chunk_size = 1280  # 80ms chunk for openwakeword (1280 samples at 16kHz)
        self.model = None
        self._init_model()

    def _friendly_trigger(self) -> str:
        """Human-readable trigger phrase for logs (e.g. 'hey_jarvis' -> 'Hey Jarvis')."""
        if not self.target_phrases:
            return "the wake word"
        return self.target_phrases[0].replace("_", " ").title()

    def _init_model(self):
        """Initialize OpenWakeWord ONNX models."""
        if OWWModel is not None:
            try:
                self.model = OWWModel(
                    wakeword_models=self.target_phrases,
                    inference_framework="onnx"
                )
                logger.info(f"[WakeWord] Initialized local Wake-Word engine with models: {list(self.model.models.keys())}")
            except Exception as e:
                logger.warning(f"[WakeWord] OpenWakeWord init fallback: {e}")
                self.model = None

    def play_activation_chime(self):
        """Plays a pleasant 2-tone ascending activation chime (440Hz -> 880Hz)."""
        if sd is None or np is None:
            return
        try:
            sr = 44100
            dur1, dur2 = 0.07, 0.10
            t1 = np.linspace(0, dur1, int(sr * dur1), False)
            t2 = np.linspace(0, dur2, int(sr * dur2), False)
            tone1 = 0.3 * np.sin(2 * np.pi * 587.33 * t1)  # D5
            tone2 = 0.4 * np.sin(2 * np.pi * 880.00 * t2)  # A5
            
            # Apply quick envelope
            fade = int(sr * 0.01)
            tone1[:fade] *= np.linspace(0, 1, fade)
            tone1[-fade:] *= np.linspace(1, 0, fade)
            tone2[:fade] *= np.linspace(0, 1, fade)
            tone2[-fade:] *= np.linspace(1, 0, fade)
            
            chime = np.concatenate([tone1, tone2]).astype(np.float32)
            sd.play(chime, samplerate=sr, blocking=False)
        except Exception as e:
            logger.debug(f"[WakeWord] Chime playback error: {e}")

    def listen_for_wake_word(self, timeout_seconds: Optional[float] = None) -> bool:
        """
        Continuously listen on microphone until wake-word is triggered.
        Returns True when wake-word is detected.
        """
        if sd is None:
            logger.warning("[WakeWord] sounddevice is unavailable.")
            return False
        if np is None:
            logger.warning("[WakeWord] numpy is unavailable; wake-word detection disabled.")
            return False

        start_time = time.time()
        logger.info(f"[WakeWord] Ambient listening active... (Say '{self._friendly_trigger()}')")

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                blocksize=self.chunk_size
            ) as stream:
                while True:
                    if timeout_seconds and (time.time() - start_time > timeout_seconds):
                        return False

                    audio_data, _ = stream.read(self.chunk_size)
                    # stream.read already returns an int16 ndarray of shape
                    # (frames, channels); flatten to 1-D rather than
                    # reinterpreting the buffer with np.frombuffer.
                    audio_chunk = np.asarray(audio_data, dtype=np.int16).reshape(-1)

                    # 1. OpenWakeWord model inference
                    if self.model is not None:
                        prediction = self.model.predict(audio_chunk)
                        for mdl_name, score in prediction.items():
                            if score >= self.threshold:
                                logger.info(f"[WakeWord] 🎙️ Wake-Word detected! ({mdl_name}: score={score:.2f})")
                                self.play_activation_chime()
                                return True
                    else:
                        # Fallback: High-confidence Energy / VAD Trigger
                        energy = np.sqrt(np.mean(audio_chunk.astype(np.float32)**2))
                        if energy > 2500:
                            logger.info(f"[WakeWord] Energy spike detected ({energy:.0f}). Triggering wake.")
                            self.play_activation_chime()
                            return True

        except Exception as e:
            logger.warning(f"[WakeWord] Stream listening error: {e}")
            return False


# Global Wake Word Singleton
wake_word_engine = WakeWordEngine()
