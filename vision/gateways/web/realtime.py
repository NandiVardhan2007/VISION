"""
OpenAI Realtime Protocol (/v1/realtime) WebSocket Gateway for VISION.
Provides full duplex speech-to-speech streaming, turn-taking, token-to-audio pipelining,
and barge-in interruption compatibility with standard OpenAI Realtime clients and Web Audio interfaces.
"""

import asyncio
import base64
import io
import json
import time
import uuid
import wave
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from vision.core.engine import vision_engine, clean_text_for_speech
from vision.perception.stt import smart_stt, is_valid_speech_text
from vision.synthesis.cartesia_tts import cartesia_tts
from vision.gateways.web.security import verify_ws_api_key
from vision.logger import logger

router = APIRouter()


def pcm16_to_wav(pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """Convert raw PCM16 audio bytes into standard WAV container bytes."""
    if pcm_bytes.startswith(b"RIFF"):
        return pcm_bytes
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return out.getvalue()


class RealtimeSession:
    """
    Manages an active bidirectional OpenAI Realtime WebSocket session.
    """

    def __init__(self, websocket: WebSocket):
        self.ws = websocket
        self.session_id = f"sess_{uuid.uuid4().hex[:12]}"
        self.audio_buffer = bytearray()
        self.sample_rate = 24000
        self.input_format = "pcm16"
        self.output_format = "pcm16"
        self.voice = "sonic-2"
        self.instructions = ""
        self.turn_detection = {
            "type": "server_vad",
            "threshold": 0.5,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 500
        }
        self.modalities = ["text", "audio"]
        self.temperature = 0.6
        self.max_response_output_tokens = 1024

        self._active_response_task: Optional[asyncio.Task] = None
        self._is_responding = False
        self._speech_in_progress = False
        self._last_audio_append_time = 0.0
        self._vad_monitor_task: Optional[asyncio.Task] = None
        self._is_active = True

    async def send_event(self, event_type: str, data: Optional[Dict[str, Any]] = None):
        """Send a formatted OpenAI Realtime event over the WebSocket."""
        payload = {
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "type": event_type
        }
        if data:
            payload.update(data)
        try:
            await self.ws.send_text(json.dumps(payload))
        except Exception as e:
            logger.debug(f"[RealtimeGateway] WebSocket send failed: {e}")

    async def initialize(self):
        """Send session.created event upon client connection."""
        await self.send_event("session.created", {
            "session": {
                "id": self.session_id,
                "object": "realtime.session",
                "model": "vision-realtime-v1",
                "modalities": self.modalities,
                "instructions": self.instructions,
                "voice": self.voice,
                "input_audio_format": self.input_format,
                "output_audio_format": self.output_format,
                "input_audio_transcription": {"model": "whisper-large-v3-turbo"},
                "turn_detection": self.turn_detection,
                "tools": [],
                "tool_choice": "auto",
                "temperature": self.temperature,
                "max_response_output_tokens": self.max_response_output_tokens
            }
        })
        # Start background VAD silence monitor
        self._vad_monitor_task = asyncio.create_task(self._vad_silence_loop())

    async def handle_event(self, payload: Dict[str, Any]):
        """Dispatch inbound client events."""
        event_type = payload.get("type", "")

        if event_type == "session.update":
            # `or {}` not `.get(k, {})`: clients may send "session": null explicitly.
            new_session = payload.get("session") or {}
            if "instructions" in new_session:
                self.instructions = new_session["instructions"]
            if "voice" in new_session:
                self.voice = new_session["voice"]
            if "modalities" in new_session:
                self.modalities = new_session["modalities"]
            if "turn_detection" in new_session:
                self.turn_detection = new_session["turn_detection"]
            if "temperature" in new_session:
                self.temperature = new_session["temperature"]
            await self.send_event("session.updated", {"session": new_session})

        elif event_type == "input_audio_buffer.append":
            audio_b64 = payload.get("audio", "")
            if audio_b64:
                try:
                    chunk = base64.b64decode(audio_b64)
                    self.audio_buffer.extend(chunk)
                    self._last_audio_append_time = time.time()

                    # Trigger barge-in if assistant is currently speaking
                    if self._is_responding:
                        logger.info("[RealtimeGateway] 🛑 Barge-in detected from client audio stream. Interrupting assistant...")
                        await self.cancel_active_response()

                    if not self._speech_in_progress and len(self.audio_buffer) > 1600:
                        self._speech_in_progress = True
                        await self.send_event("input_audio_buffer.speech_started", {
                            "audio_start_ms": int(time.time() * 1000),
                            "item_id": f"item_{uuid.uuid4().hex[:10]}"
                        })
                except Exception as e:
                    logger.warning(f"[RealtimeGateway] Failed to decode audio chunk: {e}")

        elif event_type == "input_audio_buffer.commit":
            await self._commit_and_process_audio()

        elif event_type == "input_audio_buffer.clear":
            self.audio_buffer.clear()
            self._speech_in_progress = False
            await self.send_event("input_audio_buffer.cleared")

        elif event_type == "conversation.item.create":
            item = payload.get("item") or {}
            await self.send_event("conversation.item.created", {
                "previous_item_id": payload.get("previous_item_id"),
                "item": item
            })
            # If user provided a text item and wants a response
            content_list = item.get("content", [])
            for c in content_list:
                if c.get("type") in ("input_text", "text"):
                    user_text = c.get("text", "")
                    if user_text:
                        await self.start_response(user_text)

        elif event_type == "response.create":
            response_conf = payload.get("response") or {}
            user_text = response_conf.get("instructions", "")
            if not user_text and len(self.audio_buffer) > 0:
                await self._commit_and_process_audio()
            elif user_text:
                await self.start_response(user_text)

        elif event_type == "response.cancel":
            await self.cancel_active_response()

    async def _vad_silence_loop(self):
        """Monitors audio streaming buffer for silence after speech to trigger auto-turn."""
        silence_threshold = 0.55  # seconds
        try:
            while self._is_active:
                await asyncio.sleep(0.1)
                if (
                    self.turn_detection
                    and self.turn_detection.get("type") == "server_vad"
                    and self._speech_in_progress
                    and len(self.audio_buffer) > 4000
                ):
                    elapsed_silence = time.time() - self._last_audio_append_time
                    if elapsed_silence >= silence_threshold:
                        logger.debug(f"[RealtimeGateway] Server VAD silence detected ({elapsed_silence:.2f}s). Processing speech...")
                        self._speech_in_progress = False
                        await self.send_event("input_audio_buffer.speech_stopped", {
                            "audio_end_ms": int(time.time() * 1000),
                            "item_id": f"item_{uuid.uuid4().hex[:10]}"
                        })
                        await self._commit_and_process_audio()
        except asyncio.CancelledError:
            pass

    async def _commit_and_process_audio(self):
        """Transcribe committed buffer and launch conversational response."""
        if not self.audio_buffer:
            return

        raw_bytes = bytes(self.audio_buffer)
        self.audio_buffer.clear()
        self._speech_in_progress = False

        item_id = f"item_{uuid.uuid4().hex[:10]}"
        await self.send_event("input_audio_buffer.committed", {
            "previous_item_id": None,
            "item_id": item_id
        })

        # Convert to WAV for STT processing. Must use the session's advertised
        # input sample rate (self.sample_rate) — hardcoding 16000 while the client
        # streams 24 kHz PCM16 pitch/speed-shifts the audio and garbles Whisper.
        wav_bytes = pcm16_to_wav(raw_bytes, sample_rate=self.sample_rate)

        # Run STT in background
        try:
            transcript = await smart_stt.transcribe(wav_bytes)
            if not transcript or not is_valid_speech_text(transcript):
                logger.debug(f"[RealtimeGateway] Filtered empty/hallucinatory speech transcription.")
                return

            logger.info(f"[RealtimeGateway] 🎙️ Transcribed User Audio: '{transcript}'")
            # Emit conversation user item
            await self.send_event("conversation.item.created", {
                "item": {
                    "id": item_id,
                    "object": "realtime.item",
                    "type": "message",
                    "status": "completed",
                    "role": "user",
                    "content": [{"type": "input_text", "text": transcript}]
                }
            })

            # Launch response pipeline
            await self.start_response(transcript)

        except Exception as e:
            logger.error(f"[RealtimeGateway] STT error during audio commit: {e}")
            await self.send_event("error", {"error": {"message": str(e), "type": "stt_error"}})

    async def cancel_active_response(self):
        """Cancel any running response generation and audio output (barge-in)."""
        if self._active_response_task and not self._active_response_task.done():
            self._active_response_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._active_response_task), timeout=0.1)
            except (asyncio.CancelledError, Exception):
                # CancelledError derives from BaseException (Py3.8+), so a plain
                # `except Exception` lets the shielded task's re-raised cancellation
                # escape the barge-in path and tear down the whole session.
                pass
            self._active_response_task = None

        if self._is_responding:
            self._is_responding = False
            await vision_engine.stop_speech()
            await self.send_event("response.cancelled")

    async def start_response(self, user_text: str):
        """Start streaming tokens and generating audio deltas."""
        await self.cancel_active_response()
        self._active_response_task = asyncio.create_task(self._generate_realtime_response(user_text))

    async def _generate_realtime_response(self, user_text: str):
        """Executes VISION engine and streams text tokens + audio chunks to client."""
        self._is_responding = True
        response_id = f"resp_{uuid.uuid4().hex[:12]}"
        item_id = f"item_{uuid.uuid4().hex[:10]}"

        await self.send_event("response.created", {
            "response": {
                "id": response_id,
                "object": "realtime.response",
                "status": "in_progress",
                "output": []
            }
        })

        await self.send_event("response.output_item.added", {
            "response_id": response_id,
            "output_index": 0,
            "item": {
                "id": item_id,
                "object": "realtime.item",
                "type": "message",
                "status": "in_progress",
                "role": "assistant",
                "content": []
            }
        })

        accumulated_text = ""
        sentence_buffer = ""
        sentence_delimiters = (". ", "! ", "? ", "\n")
        streamer_task = None  # ensure it exists for the finally even if we raise early

        try:
            # We process through VISION engine multi-turn loop and stream
            # Define streaming sentence synthesizer queue
            audio_queue: asyncio.Queue = asyncio.Queue(maxsize=5)

            async def _audio_streamer():
                """Reads synthesized audio chunks and streams base64 deltas over WS."""
                try:
                    while True:
                        audio_data = await audio_queue.get()
                        if audio_data is None:
                            break
                        # Convert/send base64 delta
                        b64_audio = base64.b64encode(audio_data).decode("utf-8")
                        await self.send_event("response.audio.delta", {
                            "response_id": response_id,
                            "item_id": item_id,
                            "output_index": 0,
                            "content_index": 0,
                            "delta": b64_audio
                        })
                except Exception as ex:
                    logger.debug(f"[RealtimeGateway] Audio streaming task aborted: {ex}")

            streamer_task = asyncio.create_task(_audio_streamer())

            # Callback for text tokens emitted by engine
            async def _on_token_chunk(token: str):
                nonlocal accumulated_text, sentence_buffer
                accumulated_text += token
                sentence_buffer += token

                # Emit transcript delta
                await self.send_event("response.audio_transcript.delta", {
                    "response_id": response_id,
                    "item_id": item_id,
                    "output_index": 0,
                    "content_index": 0,
                    "delta": token
                })

                # Check for completed sentence to stream to TTS
                for sep in sentence_delimiters:
                    if sep in sentence_buffer:
                        parts = sentence_buffer.split(sep, 1)
                        complete_sentence = parts[0] + sep.strip()
                        sentence_buffer = parts[1]
                        spoken_chunk = clean_text_for_speech(complete_sentence)
                        if spoken_chunk:
                            try:
                                audio_bytes = await cartesia_tts.synthesize(spoken_chunk)
                                if audio_bytes:
                                    await audio_queue.put(audio_bytes)
                            except Exception as e:
                                logger.debug(f"[RealtimeGateway] TTS chunk generation failed: {e}")
                        break

            # Execute VISION engine with token callback
            response_dict = await vision_engine.process_user_input(
                user_text=user_text,
                session_id=self.session_id,
                channel="realtime_ws",
                synthesize_voice=False,  # We handle direct realtime streaming deltas here
                token_callback=_on_token_chunk
            )

            # Flush remaining sentence buffer
            if sentence_buffer.strip():
                spoken_chunk = clean_text_for_speech(sentence_buffer.strip())
                if spoken_chunk:
                    try:
                        audio_bytes = await cartesia_tts.synthesize(spoken_chunk)
                        if audio_bytes:
                            await audio_queue.put(audio_bytes)
                    except Exception as e:
                        logger.debug(f"[RealtimeGateway] TTS final chunk generation failed: {e}")

            # Signal end of audio stream
            await audio_queue.put(None)
            if not streamer_task.done():
                await streamer_task

            final_text = response_dict.get("response", accumulated_text)

            await self.send_event("response.audio_transcript.done", {
                "response_id": response_id,
                "item_id": item_id,
                "output_index": 0,
                "content_index": 0,
                "transcript": final_text
            })

            await self.send_event("response.audio.done", {
                "response_id": response_id,
                "item_id": item_id,
                "output_index": 0,
                "content_index": 0
            })

            await self.send_event("response.output_item.done", {
                "response_id": response_id,
                "output_index": 0,
                "item": {
                    "id": item_id,
                    "object": "realtime.item",
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": final_text},
                        {"type": "audio", "transcript": final_text}
                    ]
                }
            })

            await self.send_event("response.done", {
                "response": {
                    "id": response_id,
                    "object": "realtime.response",
                    "status": "completed",
                    "output": [
                        {
                            "id": item_id,
                            "object": "realtime.item",
                            "type": "message",
                            "status": "completed",
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": final_text}
                            ]
                        }
                    ]
                }
            })

        except asyncio.CancelledError:
            logger.info(f"[RealtimeGateway] Response {response_id} cancelled.")
        except Exception as e:
            logger.error(f"[RealtimeGateway] Error in response generation: {e}")
            await self.send_event("error", {
                "error": {
                    "message": str(e),
                    "type": "response_error",
                    "response_id": response_id
                }
            })
        finally:
            self._is_responding = False
            # If we raised before draining the queue, the streamer coroutine is
            # still blocked on audio_queue.get() — cancel it so it doesn't leak.
            if streamer_task and not streamer_task.done():
                streamer_task.cancel()

    async def close(self):
        """Cleanup session resources."""
        self._is_active = False
        if self._vad_monitor_task and not self._vad_monitor_task.done():
            self._vad_monitor_task.cancel()
        await self.cancel_active_response()


@router.websocket("/v1/realtime")
async def realtime_websocket_endpoint(websocket: WebSocket):
    """
    OpenAI Realtime Protocol WebSocket endpoint.
    Connect here with standard OpenAI Realtime clients or Web Audio streaming frontends.
    """
    if not verify_ws_api_key(websocket):
        await websocket.close(code=1008)  # policy violation
        return
    await websocket.accept()
    logger.info("[RealtimeGateway] Client connected to /v1/realtime.")
    session = RealtimeSession(websocket)
    await session.initialize()

    try:
        while True:
            message_text = await websocket.receive_text()
            try:
                payload = json.loads(message_text)
                await session.handle_event(payload)
            except json.JSONDecodeError:
                logger.warning(f"[RealtimeGateway] Received invalid JSON payload: {message_text[:100]}")
    except WebSocketDisconnect:
        logger.info("[RealtimeGateway] Client disconnected from /v1/realtime.")
    except Exception as e:
        logger.error(f"[RealtimeGateway] WebSocket exception: {e}")
    finally:
        await session.close()
