"""
Audio Stream Capture & Voice Listener from local microphone with Silero Voice Activity Detection.
Supports adaptive device selection, PortAudio fallback, and graceful error handling.
"""

import io
import time
import wave
from typing import Optional
from vision.config import config
from vision.perception.vad import vad_detector
from vision.logger import logger

# sounddevice (PortAudio) and numpy are independent optional deps — split them so
# a headless box without PortAudio doesn't also null numpy.
try:
    import sounddevice as sd
except ImportError:
    sd = None

try:
    import numpy as np
except ImportError:
    np = None


class AudioStreamManager:
    def __init__(self, sample_rate: int = 16000, channels: int = 1, chunk_size: int = 1024):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self._mic_error_logged = False
        self._main_loop = None

    def bind_loop(self, loop):
        """Register the main asyncio loop.

        ``record_phrase`` runs inside a worker thread (``run_in_executor``), where
        ``asyncio.get_event_loop()`` raises and barge-in could never schedule
        ``stop_speech()``. Capturing the main loop here lets the worker thread
        hand the coroutine back with ``run_coroutine_threadsafe``.
        """
        self._main_loop = loop

    def is_mic_available(self) -> bool:
        if sd is None or np is None:
            return False
        try:
            dev = sd.query_devices(kind='input')
            return dev is not None
        except Exception:
            return False

    def record_phrase(
        self,
        energy_threshold: Optional[float] = None,
        silence_timeout: Optional[float] = None,
        min_speech_duration: Optional[float] = None,
        max_duration: float = 25.0
    ) -> Optional[bytes]:
        """
        Listen on the microphone with multi-stage noise rejection:
        - Dynamic ambient noise floor calibration
        - Neural Silero VAD confirmation (rejects typing, breathing, background hum)
        - Consecutive speech frames threshold (prevents triggering on clicks/taps)
        - Minimum speech duration gate (discards accidental noises < 0.45s)
        """
        if sd is None or np is None:
            return None

        silence_timeout = silence_timeout or getattr(config, "VISION_SILENCE_TIMEOUT_SEC", 0.9)
        min_speech_duration = min_speech_duration or getattr(config, "VISION_MIN_SPEECH_DURATION_SEC", 0.45)
        
        from collections import deque
        frames = []
        is_speaking = False
        silence_start_time = None
        consecutive_speech_count = 0
        speech_frame_count = 0
        ambient_rms_samples = []
        calibrated_energy_threshold = energy_threshold or 0.02

        start_time = time.time()

        # Clear any leftover audio in the shared VAD rolling buffer so the previous
        # phrase's tail doesn't contaminate this turn's first speech probability.
        vad_detector.reset_states()

        try:
            dev_info = sd.query_devices(kind='input')
            # `default_samplerate`/`max_input_channels` can be present-but-None or
            # 0 on some drivers; guard with `or` and clamp channels to >= 1 so we
            # never open a stream with 0 channels or a None samplerate.
            native_rate = int(dev_info.get('default_samplerate') or self.sample_rate)
            native_channels = max(1, min(self.channels, dev_info.get('max_input_channels') or 1))

            pre_roll_chunks = int(0.35 * (native_rate / self.chunk_size))  # ~350ms pre-roll
            pre_roll = deque(maxlen=max(2, pre_roll_chunks))

            from vision.synthesis.player import audio_player

            with sd.InputStream(
                samplerate=native_rate,
                channels=native_channels,
                dtype="float32",
                blocksize=self.chunk_size
            ) as stream:
                self._mic_error_logged = False
                
                # Calibrate ambient noise floor for first 5 chunks (~200ms) only if audio_player is NOT playing
                is_currently_playing = getattr(audio_player, "is_playing", False)
                if not is_currently_playing:
                    for _ in range(5):
                        c_data, _ = stream.read(self.chunk_size)
                        c_rms = float(np.sqrt(np.mean(c_data**2)))
                        ambient_rms_samples.append(c_rms)
                        pre_roll.append(c_data.copy())

                    if ambient_rms_samples:
                        avg_ambient = float(np.mean(ambient_rms_samples))
                        calibrated_energy_threshold = max(0.015, min(0.045, avg_ambient * 1.8))
                else:
                    calibrated_energy_threshold = energy_threshold or 0.018

                while True:
                    if time.time() - start_time > max_duration:
                        break

                    data, _ = stream.read(self.chunk_size)
                    rms = float(np.sqrt(np.mean(data**2)))
                    
                    # Convert to int16 bytes for VAD check
                    int16_chunk = (data * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
                    
                    # Check Silero neural speech probability
                    speech_prob = vad_detector.get_speech_probability(int16_chunk, native_rate)
                    is_voice = speech_prob > vad_detector.silero_threshold
                    is_playing = getattr(audio_player, "is_playing", False)

                    # During active TTS playback, prioritize Silero neural probability for instant barge-in
                    if is_playing:
                        speech_active = (speech_prob > 0.40) or (rms > 0.025 and is_voice)
                    else:
                        speech_active = (rms > calibrated_energy_threshold) and is_voice

                    if speech_active:
                        consecutive_speech_count += 1
                        # When VISION is speaking, interrupt immediately on first confirmed vocal frame
                        required_consecutive = 1 if is_playing else 2

                        if not is_speaking and consecutive_speech_count >= required_consecutive:
                            is_speaking = True
                            # Instant Barge-In: Cut speaker output and cancel backend generation
                            try:
                                audio_player.stop()
                                logger.info(f"[AudioStream] 🛑 User speech detected (prob={speech_prob:.2f})! Aborted active speech playback.")
                                from vision.core.engine import vision_engine
                                if hasattr(vision_engine, "stop_speech"):
                                    import asyncio
                                    loop = self._main_loop
                                    if loop is None:
                                        try:
                                            loop = asyncio.get_event_loop()
                                        except Exception:
                                            loop = None
                                    # record_phrase runs in a worker thread, so schedule
                                    # the coroutine onto the main loop thread-safely.
                                    if loop is not None and loop.is_running():
                                        try:
                                            asyncio.run_coroutine_threadsafe(
                                                vision_engine.stop_speech(), loop
                                            )
                                        except Exception:
                                            pass
                            except Exception as ex:
                                logger.debug(f"[AudioStream] Barge-in stop notice: {ex}")

                            # Prepend pre-roll buffer
                            frames.extend(list(pre_roll))

                        if is_speaking:
                            frames.append(data.copy())
                            speech_frame_count += 1
                            silence_start_time = None
                    else:
                        consecutive_speech_count = 0
                        if is_speaking:
                            frames.append(data.copy())
                            if silence_start_time is None:
                                silence_start_time = time.time()
                            elif time.time() - silence_start_time >= silence_timeout:
                                break
                        else:
                            pre_roll.append(data.copy())

            if not frames or not is_speaking:
                return None

            # Calculate total duration of actual speech captured
            chunk_duration_sec = self.chunk_size / native_rate
            total_speech_sec = speech_frame_count * chunk_duration_sec

            # Reject accidental noise bursts shorter than min_speech_duration
            if total_speech_sec < min_speech_duration:
                logger.debug(f"[AudioStream] Rejected noise burst ({total_speech_sec:.2f}s < {min_speech_duration:.2f}s threshold).")
                return None

            audio_array = np.concatenate(frames, axis=0)
            int16_data = (audio_array * 32767).clip(-32768, 32767).astype(np.int16)

            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, "wb") as wf:
                wf.setnchannels(native_channels)
                wf.setsampwidth(2)
                wf.setframerate(native_rate)
                wf.writeframes(int16_data.tobytes())

            return wav_buffer.getvalue()

        except Exception as e:
            if not self._mic_error_logged:
                logger.warning(f"[AudioStream] Microphone capture unavailable ({e}). Please ensure Windows Microphone permissions are enabled.")
                self._mic_error_logged = True
            return None


audio_stream = AudioStreamManager()

