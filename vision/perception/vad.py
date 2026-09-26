"""
Silero Voice Activity Detection (VAD) & Neural Speech Segmenter.
Provides deep-learning neural VAD (Silero) with automatic 16kHz resampling and adaptive fallback.
"""

from typing import Optional
from vision.config import config
from vision.logger import logger

try:
    import numpy as np
except ImportError:
    np = None

# Silero (and its torch backend) is a heavy optional dependency. Keep it in its
# own block so a missing silero_vad doesn't also null out numpy — otherwise the
# Energy RMS fallback below becomes unreachable and VAD reports speech constantly.
try:
    import torch
    import silero_vad
    from silero_vad import load_silero_vad, VADIterator
except ImportError:
    torch = None
    silero_vad = None
    load_silero_vad = None
    VADIterator = None


class VADDetector:
    def __init__(self, energy_threshold: float = 0.02, silero_threshold: Optional[float] = None):
        self.energy_threshold = energy_threshold
        self.silero_threshold = silero_threshold or getattr(config, "VISION_VAD_THRESHOLD", 0.50)
        self.model = None
        self.vad_iterator = None
        self._buffer_16k = np.array([], dtype=np.float32) if np is not None else []
        self._init_silero()

    def _init_silero(self):
        if load_silero_vad and torch:
            try:
                self.model = load_silero_vad()
                if VADIterator:
                    self.vad_iterator = VADIterator(
                        self.model,
                        threshold=self.silero_threshold,
                        sampling_rate=16000,
                        min_silence_duration_ms=800,
                        speech_pad_ms=250
                    )
                logger.info("[VAD] Silero Neural VAD model and VADIterator loaded successfully.")
            except Exception as e:
                logger.warning(f"[VAD] Failed to initialize Silero VAD: {e}. Using Energy VAD fallback.")
                self.model = None

    def reset_states(self):
        """Reset internal recurrent neural states for a new conversational turn."""
        if np is not None:
            self._buffer_16k = np.array([], dtype=np.float32)
        else:
            self._buffer_16k = []
            
        if self.vad_iterator is not None:
            try:
                self.vad_iterator.reset_states()
            except Exception:
                pass
        elif self.model is not None:
            try:
                self.model.reset_states()
            except Exception:
                pass

    def resample_to_16k(self, audio_data: "np.ndarray", orig_sr: int) -> "np.ndarray":
        """Fast linear interpolation resampling to 16,000 Hz required by Silero."""
        if orig_sr == 16000 or len(audio_data) == 0:
            return audio_data
        target_length = int(len(audio_data) * 16000 / orig_sr)
        return np.interp(
            np.linspace(0, len(audio_data), target_length, endpoint=False),
            np.arange(len(audio_data)),
            audio_data
        ).astype(np.float32)

    def is_speech(self, audio_chunk: bytes, sample_rate: int = 16000) -> bool:
        """Evaluate if an audio chunk contains active human voice activity."""
        prob = self.get_speech_probability(audio_chunk, sample_rate)
        return prob > self.silero_threshold

    def get_speech_probability(self, audio_chunk: bytes, sample_rate: int = 16000) -> float:
        """Get the continuous probability (0.0 to 1.0) that the audio chunk contains human voice."""
        if not audio_chunk:
            return 0.0

        if np is None:
            return 1.0

        samples = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0
        if len(samples) == 0:
            return 0.0

        # Fast RMS energy check
        rms = float(np.sqrt(np.mean(samples**2)))

        # 1. High-accuracy Silero Neural VAD Inference with rolling 16k buffer
        if self.model is not None and torch is not None:
            try:
                # Resample to 16kHz and append to rolling buffer
                samples_16k = self.resample_to_16k(samples, sample_rate) if sample_rate != 16000 else samples
                self._buffer_16k = np.append(self._buffer_16k, samples_16k)

                # Silero expects contiguous 512-sample frames at 16kHz. Consume the
                # buffer in exact non-overlapping 512-sample steps and keep the last
                # frame's probability — feeding overlapping/gapped [-512:] slices
                # corrupts the model's recurrent state and skips ~half the audio.
                last_prob = None
                while len(self._buffer_16k) >= 512:
                    chunk_512 = self._buffer_16k[:512]
                    self._buffer_16k = self._buffer_16k[512:]
                    tensor = torch.from_numpy(chunk_512).float()
                    last_prob = float(self.model(tensor, 16000).item())
                if last_prob is not None:
                    return last_prob
            except Exception:
                pass

        # 2. Fast Energy RMS VAD Fallback
        return 1.0 if rms > self.energy_threshold else 0.0


vad_detector = VADDetector()
