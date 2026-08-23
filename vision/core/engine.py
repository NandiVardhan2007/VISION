"""
Central VISION Autonomous Engine orchestrating perception, cognition, tools, memory (Working + MAG + CAG), and TTS synthesis.
"""

import asyncio
import json
import re
import time
from datetime import datetime
from typing import Optional, Dict, Any, List
from vision.constants import DEFAULT_SYSTEM_PROMPT, VisionEvents
from vision.core.event_bus import event_bus
from vision.core.session import session_manager, Session
from vision.cognitive.load_balancer import load_balancer
from vision.cognitive.router import router
from vision.tools.registry import tool_registry
from vision.memory.working_memory import working_memory
from vision.memory.mag_engine import mag_engine
from vision.memory.cag_engine import cag_engine
from vision.synthesis.cartesia_tts import cartesia_tts
from vision.synthesis.player import audio_player
from vision.config import config
from vision.logger import logger



from vision.core.reminder_daemon import reminder_manager


def _convert_markdown_tables_to_speech(text: str) -> str:
    """Convert markdown tables into clean, natural spoken key-value sentences."""
    lines = text.split("\n")
    processed_lines = []
    in_table = False
    headers = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            # Table row: extract cell contents
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            # Skip separator line like |---|---|
            if all(re.match(r"^:?-+:?$", c) for c in cells if c):
                continue
            if not in_table:
                in_table = True
                headers = cells
                continue
            else:
                # Content row
                if len(cells) == 2 and headers and len(headers) == 2:
                    # Clean key-value pair like | Name | Nandini Kovvuri |
                    k = re.sub(r'[*_`]', '', cells[0]).strip()
                    v = re.sub(r'[*_`]', '', cells[1]).strip()
                    if k and v:
                        processed_lines.append(f"{k}: {v}.")
                else:
                    clean_cells = [re.sub(r'[*_`]', '', c).strip() for c in cells if c.strip()]
                    if clean_cells:
                        processed_lines.append(", ".join(clean_cells) + ".")
        else:
            in_table = False
            headers = []
            processed_lines.append(line)

    return "\n".join(processed_lines)


def clean_text_for_speech(text: str) -> str:
    """Normalize and clean LLM response text for natural, fluid spoken voice playback."""
    if not text:
        return ""
    t = text.strip()

    # If model returned raw JSON tool call payload
    if t.startswith("{") and ("\"name\"" in t or "'name'" in t or "\"action\"" in t):
        return "Action completed successfully, Nandu!"

    # Remove thinking tags if model outputs <think>...</think>
    t = re.sub(r'<think>.*?</think>', '', t, flags=re.DOTALL)

    # Convert markdown tables into natural spoken sentences
    t = _convert_markdown_tables_to_speech(t)

    # Remove markdown code blocks ```...```
    t = re.sub(r'```[\s\S]*?```', '', t)

    # Remove inline code `...`
    t = re.sub(r'`([^`]+)`', r'\1', t)

    # Remove markdown links [text](url) -> text
    t = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', t)

    # Remove raw URLs
    t = re.sub(r'https?://\S+', '', t)

    # Remove markdown headers #, ##, ###
    t = re.sub(r'^\s*#+\s*', '', t, flags=re.MULTILINE)

    # Remove bold / italic markers **text**, *text*, _text_
    t = re.sub(r'\*\*([^*]+)\*\*', r'\1', t)
    t = re.sub(r'\*([^*]+)\*', r'\1', t)
    t = re.sub(r'__([^_]+)__', r'\1', t)
    t = re.sub(r'_([^_]+)_', r'\1', t)

    # Convert markdown bullet points or numbered lists into natural spoken pauses
    t = re.sub(r'^\s*[\*\-\+•]\s*', '', t, flags=re.MULTILINE)
    t = re.sub(r'^\s*\d+\.\s*', '', t, flags=re.MULTILINE)

    # Remove any remaining stray pipe characters (|) so TTS never speaks "vertical bar"
    t = t.replace('|', ' ')

    # Replace all non-standard unicode whitespace (narrow spaces, zero-width, non-breaking) with standard space
    t = re.sub(r'[\u00a0\u1680\u2000-\u200f\u2028-\u202f\u205f\u3000\ufeff]', ' ', t)

    # Clean phone numbers and spaced-out digit sequences so TTS speaks them fluently without unnatural gaps
    # E.g. "910 021 9275", "9 1 0 0 2 1 9 2 7 5", "+91 910 021 9275" -> "9100219275"
    def _join_spaced_phone_digits(m):
        raw = m.group(0)
        digits = re.sub(r'[^\d+]', '', raw)
        return digits

    t = re.sub(r'(?:\+?91[\s\-\.]*)?(?:\d[\s\-\.]*){9,12}\d', _join_spaced_phone_digits, t)

    # Remove markdown table dashes / dividers
    t = re.sub(r'[-–—]{2,}', ' ', t)

    # Remove repeated dots / ellipses that cause long artificial pauses
    t = re.sub(r'\.{2,}', '.', t)

    # Remove isolated special symbols
    t = re.sub(r'[\~^&|#]', ' ', t)

    # Normalize smart quotes, dashes, and special typography
    t = t.replace('\u2011', '-').replace('\u2013', '-').replace('\u2014', ' - ')
    t = t.replace('\u2018', "'").replace('\u2019', "'")
    t = t.replace('\u201c', '"').replace('\u201d', '"')

    # Strip emoji and special decorative unicode symbols for clean voice synthesis
    t = re.sub(r'[\U00010000-\U0010ffff]', '', t)
    t = re.sub(r'[\u2600-\u27bf\u2300-\u23ff]', '', t)

    # Normalize multiple whitespace / line breaks
    t = re.sub(r'\n+', ' ', t)
    t = re.sub(r'\s{2,}', ' ', t)

    return t.strip()


class VisionEngine:
    def __init__(self):
        self.tts = cartesia_tts
        self.is_running = False
        self._current_speech_task: Optional[asyncio.Task] = None
        self._current_speech_gen: int = 0

    async def stop_speech(self):
        """Immediately abort all active speech synthesis, streaming, and playback."""
        self._current_speech_gen += 1
        audio_player.stop()
        if self._current_speech_task and not self._current_speech_task.done():
            self._current_speech_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._current_speech_task), timeout=0.05)
            except Exception:
                pass
            self._current_speech_task = None

    async def initialize(self):
        """Initialize engine components and background listeners."""
        self.is_running = True
        logger.info("[VisionEngine] Initialized successfully with Full-Duplex Cartesia Neural TTS + MAG + CAG.")
        
        # Launch Autonomous Spoken Reminder Daemon
        async def _reminder_speaker(alert_text: str):
            logger.info(f"[VisionEngine] 🗣️ Speaking proactive reminder: '{alert_text}'")
            if self.tts:
                try:
                    audio_bytes = await self.tts.synthesize(alert_text)
                    audio_player.play_wav_bytes(audio_bytes, force_reset=True)
                except Exception as e:
                    logger.error(f"[VisionEngine] Reminder voice synthesis error: {e}")

        asyncio.create_task(reminder_manager.start_daemon(speech_callback=_reminder_speaker))
        
        # Launch Autonomous Academic Timetable Watchdog Daemon
        from vision.tools.academic_tools import start_academic_daemon
        asyncio.create_task(start_academic_daemon(speech_callback=_reminder_speaker))
        
        await event_bus.publish(VisionEvents.SYSTEM_STARTED)

    async def speak_pipelined(
        self,
        text: str,
        voice_id: Optional[str] = None,
        playback_started_event: Optional[asyncio.Event] = None,
        session_id: str = "default_session"
    ) -> bool:
        """
        Synthesize and stream voice playback with zero-latency pipelining and barge-in.
        - For conversational responses (< 350 chars), synthesizes the entire natural response
          in one ultra-fast Cartesia call (<180ms) for 100% natural prosody with zero gaps.
        - For longer multi-paragraph responses, uses an async producer-consumer pipeline
          so chunk N+1 is pre-synthesized in the background while chunk N is playing.
        """
        if not text or not self.tts:
            if playback_started_event and not playback_started_event.is_set():
                playback_started_event.set()
            return True

        spoken_text = clean_text_for_speech(text)
        if not spoken_text:
            if playback_started_event and not playback_started_event.is_set():
                playback_started_event.set()
            return True

        this_gen = self._current_speech_gen
        if audio_player.is_interrupted():
            if playback_started_event and not playback_started_event.is_set():
                playback_started_event.set()
            return False

        # Fast path: For conversational turns, synthesize as a single fluid block
        if len(spoken_text) <= 350:
            if audio_player.is_interrupted() or self._current_speech_gen != this_gen:
                if playback_started_event and not playback_started_event.is_set():
                    playback_started_event.set()
                return False
            try:
                audio_bytes = await self.tts.synthesize(spoken_text)
                if playback_started_event and not playback_started_event.is_set():
                    playback_started_event.set()
                if audio_bytes and not audio_player.is_interrupted() and self._current_speech_gen == this_gen:
                    return await asyncio.to_thread(audio_player.play_wav_bytes, audio_bytes, True, False)
                return False
            except Exception as e:
                logger.error(f"[VisionEngine] Speech synthesis error: {e}")
                if playback_started_event and not playback_started_event.is_set():
                    playback_started_event.set()
                return False

        this_gen = self._current_speech_gen
        audio_player.reset_interrupt()

        # Split text into natural sentence/clause chunks (~150-250 characters each)
        raw_sentences = re.split(r'(?<=[.!?])\s+', spoken_text)
        chunks = []
        cur = ""
        for s in raw_sentences:
            s = s.strip()
            if not s:
                continue
            if len(cur) + len(s) < 220:
                cur = f"{cur} {s}".strip() if cur else s
            else:
                if cur:
                    chunks.append(cur)
                cur = s
        if cur:
            chunks.append(cur)

        if not chunks:
            if playback_started_event and not playback_started_event.is_set():
                playback_started_event.set()
            return True

        if len(chunks) == 1:
            try:
                audio_bytes = await self.tts.synthesize(chunks[0])
                if playback_started_event and not playback_started_event.is_set():
                    playback_started_event.set()
                if audio_bytes and not audio_player.is_interrupted() and self._current_speech_gen == this_gen:
                    return await asyncio.to_thread(audio_player.play_wav_bytes, audio_bytes, True, False)
                return False
            except Exception as e:
                logger.error(f"[VisionEngine] Speech synthesis error: {e}")
                if playback_started_event and not playback_started_event.is_set():
                    playback_started_event.set()
                return False

        # Asynchronous Producer-Consumer pipeline for gapless background prefetching
        audio_queue: asyncio.Queue = asyncio.Queue(maxsize=3)

        async def _synthesize_producer():
            try:
                for chunk in chunks:
                    if audio_player.is_interrupted() or self._current_speech_gen != this_gen:
                        break
                    try:
                        audio_data = await self.tts.synthesize(chunk)
                        if audio_player.is_interrupted() or self._current_speech_gen != this_gen:
                            break
                        if audio_data:
                            await audio_queue.put(audio_data)
                    except Exception as ex:
                        logger.warning(f"[VisionEngine] Pipeline chunk synthesis error: {ex}")
            finally:
                await audio_queue.put(None)  # Sentinel to signal end of stream

        producer_task = asyncio.create_task(_synthesize_producer())

        try:
            while True:
                if audio_player.is_interrupted() or self._current_speech_gen != this_gen:
                    break
                audio_bytes = await audio_queue.get()
                if audio_bytes is None:
                    break
                if audio_player.is_interrupted() or self._current_speech_gen != this_gen:
                    break
                if playback_started_event and not playback_started_event.is_set():
                    playback_started_event.set()
                completed = await asyncio.to_thread(audio_player.play_wav_bytes, audio_bytes, True, False)
                if not completed:
                    break
        finally:
            if playback_started_event and not playback_started_event.is_set():
                playback_started_event.set()
            if not producer_task.done():
                producer_task.cancel()

        return not audio_player.is_interrupted() and self._current_speech_gen == this_gen

    async def _stream_and_speak(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.6,
        max_tokens: Optional[int] = 1024,
        token_callback: Optional[Any] = None,
        session_id: str = "default_session",
        playback_started_event: Optional[asyncio.Event] = None
    ) -> str:
        """
        Stream LLM tokens in real-time and start TTS on each sentence as soon as
        a sentence boundary is detected — while the LLM is still generating.

        Returns the full accumulated response text.
        """
        full_text = ""
        sentence_buffer = ""
        sentence_end_re = re.compile(r'[.!?]\s+')

        this_gen = self._current_speech_gen
        audio_player.reset_interrupt()

        audio_queue: asyncio.Queue = asyncio.Queue(maxsize=4)
        producer_done = asyncio.Event()

        async def _tts_producer(text_queue: asyncio.Queue):
            try:
                while True:
                    sentence = await text_queue.get()
                    if sentence is None:  # Sentinel
                        break
                    if audio_player.is_interrupted() or self._current_speech_gen != this_gen:
                        break
                    try:
                        audio_bytes = await self.tts.synthesize(sentence)
                        if audio_bytes and not audio_player.is_interrupted() and self._current_speech_gen == this_gen:
                            await audio_queue.put(audio_bytes)
                    except Exception as ex:
                        logger.warning(f"[VisionEngine] Stream TTS chunk error: {ex}")
            finally:
                await audio_queue.put(None)

        async def _playback_consumer():
            try:
                while True:
                    audio_bytes = await audio_queue.get()
                    if audio_bytes is None:
                        break
                    if audio_player.is_interrupted() or self._current_speech_gen != this_gen:
                        break
                    if playback_started_event and not playback_started_event.is_set():
                        playback_started_event.set()
                    completed = await asyncio.to_thread(audio_player.play_wav_bytes, audio_bytes, True, False)
                    if not completed:
                        break
            finally:
                if playback_started_event and not playback_started_event.is_set():
                    playback_started_event.set()
                producer_done.set()

        text_queue: asyncio.Queue = asyncio.Queue(maxsize=8)
        tts_task = asyncio.create_task(_tts_producer(text_queue))
        playback_task = asyncio.create_task(_playback_consumer())

        try:
            async for token in load_balancer.stream_chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            ):
                if audio_player.is_interrupted() or self._current_speech_gen != this_gen:
                    break

                full_text += token
                sentence_buffer += token

                # Publish event to event_bus for real-time WebSocket listeners
                await event_bus.publish(VisionEvents.LLM_STREAM_CHUNK, {"text": token, "session_id": session_id})

                # Invoke token callback if provided (e.g. SSE streaming route)
                if token_callback:
                    try:
                        res = token_callback(token)
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception as cb_err:
                        logger.debug(f"[VisionEngine] token_callback exception: {cb_err}")

                # Check for sentence boundaries in the buffer
                while True:
                    match = sentence_end_re.search(sentence_buffer)
                    if not match:
                        break
                    end_pos = match.start() + 1
                    complete_sentence = sentence_buffer[:end_pos].strip()
                    sentence_buffer = sentence_buffer[match.end():]

                    if complete_sentence:
                        cleaned = clean_text_for_speech(complete_sentence)
                        if cleaned:
                            await text_queue.put(cleaned)

            # Flush any remaining text in the buffer
            remaining = sentence_buffer.strip()
            if remaining and not audio_player.is_interrupted() and self._current_speech_gen == this_gen:
                cleaned = clean_text_for_speech(remaining)
                if cleaned:
                    await text_queue.put(cleaned)

        except Exception as e:
            logger.error(f"[VisionEngine] LLM streaming error: {e}")
        finally:
            await text_queue.put(None)
            # Store active speech task in self._current_speech_task so barge-in can cancel it
            self._current_speech_task = playback_task

            # Wait briefly for audio playback to commence so response and audio are synchronized
            if playback_started_event and not playback_started_event.is_set():
                try:
                    await asyncio.wait_for(playback_started_event.wait(), timeout=1.5)
                except Exception:
                    pass

        return full_text

    async def process_user_input(
        self,
        user_text: str,
        session_id: str = "default_session",
        channel: str = "web",
        synthesize_voice: bool = True,
        token_callback: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Core multi-turn conversational loop with CAG caching, MAG memory, dynamic tool calling & pipelined voice."""
        start_time = time.time()
        
        # Stop any active background speech from previous turns before processing new input
        await self.stop_speech()

        session: Session = session_manager.get_or_create(session_id=session_id, channel=channel)

        # 1. Record user message
        session.add_message(role="user", content=user_text)
        await event_bus.publish(VisionEvents.USER_QUERY_RECEIVED, {"text": user_text, "session_id": session_id})

        # 2. Check CAG (Cache-Augmented Generation) Cache
        cached_result = cag_engine.lookup(user_text)
        if cached_result:
            final_text = cached_result["response"]
            elapsed_ms = round((time.time() - start_time) * 1000, 1)
            logger.info(f"[VisionEngine] CAG Cache HIT -> returning in {elapsed_ms}ms (Age: {cached_result['age_seconds']}s)")
            
            session.add_message(role="assistant", content=final_text)
            await event_bus.publish(VisionEvents.LLM_RESPONSE_DONE, {"text": final_text, "session_id": session_id, "cached": True})

            if token_callback:
                try:
                    res = token_callback(final_text)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:
                    pass

            if synthesize_voice and final_text:
                audio_player.reset_interrupt()
                playback_started = asyncio.Event()
                self._current_speech_task = asyncio.create_task(
                    self.speak_pipelined(final_text, playback_started_event=playback_started, session_id=session_id)
                )
                try:
                    await asyncio.wait_for(playback_started.wait(), timeout=1.5)
                except Exception:
                    pass

            return {
                "session_id": session_id,
                "response": final_text,
                "provider": "CAG-Cache (Ultra-Low Latency)",
                "latency_ms": elapsed_ms,
                "cached": True
            }

        # 3. Dynamic temporal, MAG Long-term Memory & Working Memory injection
        live_now = datetime.now().strftime("%A, %B %d, %Y - %I:%M:%S %p")
        system_content = (
            DEFAULT_SYSTEM_PROMPT
            + f"\n[CURRENT LIVE SYSTEM TIME: {live_now}]\n"
            + mag_engine.get_mag_prompt_injection(user_text)
            + working_memory.get_context_injection_prompt()
        )
        llm_messages = [{"role": "system", "content": system_content}] + session.get_messages_for_llm(max_history=15)

        # 4. Dynamic Tool Routing
        all_tool_schemas = tool_registry.get_all_schemas()
        relevant_tools = router.route_tools(user_text, all_tool_schemas)

        # 5. Multi-Turn LLM & Tool Execution Loop
        has_executed_tools = False
        max_tool_turns = 5
        turn_count = 0
        response: Dict[str, Any] = {}

        # If tools are relevant, use the non-streaming tool-call loop
        if relevant_tools:
            while turn_count < max_tool_turns:
                turn_count += 1
                llm_messages = [{"role": "system", "content": system_content}] + session.get_messages_for_llm(max_history=15)

                response = await load_balancer.chat_completion(
                    messages=llm_messages,
                    tools=relevant_tools,
                    temperature=0.6,
                    max_tokens=1024
                )

                tool_calls = response.get("tool_calls")
                if not tool_calls:
                    break

                has_executed_tools = True
                session.add_message(
                    role="assistant",
                    content=response.get("content") or "",
                    tool_calls=tool_calls
                )

                for tc in tool_calls:
                    func_name = tc.get("function", {}).get("name")
                    raw_args = tc.get("function", {}).get("arguments", {})

                    args = {}
                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args) if raw_args.strip() else {}
                        except Exception:
                            args = {}
                    elif isinstance(raw_args, dict):
                        args = raw_args

                    await event_bus.publish(VisionEvents.TOOL_CALL_DETECTED, {"tool": func_name, "args": args})
                    tool_result = await tool_registry.execute(func_name, args)
                    await event_bus.publish(VisionEvents.TOOL_EXECUTION_COMPLETED, {"tool": func_name, "result": tool_result})

                    mag_engine.record_event(
                        event_type="tool_execution",
                        description=f"Executed {func_name}",
                        metadata=json.dumps({"args": args, "status": "success"})
                    )

                    session.add_message(
                        role="tool",
                        name=func_name,
                        tool_call_id=tc.get("id"),
                        content=str(tool_result)
                    )

            final_text = response.get("content") or ""
            if not final_text and has_executed_tools:
                final_text = "Done. I have executed the requested actions."

            session.add_message(role="assistant", content=final_text)
            await event_bus.publish(VisionEvents.LLM_RESPONSE_DONE, {"text": final_text, "session_id": session_id})

            if token_callback:
                try:
                    res = token_callback(final_text)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:
                    pass

            # Spoken response for tool results (non-blocking background playback)
            if synthesize_voice and final_text:
                audio_player.reset_interrupt()
                self._current_speech_task = asyncio.create_task(self.speak_pipelined(final_text))

        else:
            # ── Pure conversational: STREAM LLM + live TTS ──────────────
            logger.info("[VisionEngine] Using streaming LLM → live TTS pipeline.")

            if synthesize_voice:
                final_text = await self._stream_and_speak(
                    messages=llm_messages,
                    temperature=0.6,
                    max_tokens=1024,
                    token_callback=token_callback,
                    session_id=session_id
                )
            else:
                final_text = ""
                async for token in load_balancer.stream_chat_completion(
                    messages=llm_messages,
                    temperature=0.6,
                    max_tokens=1024
                ):
                    final_text += token
                    await event_bus.publish(VisionEvents.LLM_STREAM_CHUNK, {"text": token, "session_id": session_id})
                    if token_callback:
                        try:
                            res = token_callback(token)
                            if asyncio.iscoroutine(res):
                                await res
                        except Exception:
                            pass

            if not final_text:
                final_text = ""

            session.add_message(role="assistant", content=final_text)
            await event_bus.publish(VisionEvents.LLM_RESPONSE_DONE, {"text": final_text, "session_id": session_id})

        # 7. Store in CAG Cache if not a dynamic tool execution
        if not has_executed_tools and not cag_engine.should_bypass(user_text):
            cag_engine.put(user_text, final_text, category="qa_general", ttl_seconds=3600)

        # 8. Autonomous Fact & Habit Extraction
        try:
            mag_engine.auto_extract_facts(user_text, final_text)
        except Exception as e:
            logger.debug(f"[VisionEngine] Auto fact extraction skipped: {e}")

        return {
            "session_id": session_id,
            "response": final_text,
            "provider": "streaming" if not has_executed_tools else response.get("provider"),
            "latency_ms": round((time.time() - start_time) * 1000, 1)
        }


# Global Vision engine singleton
vision_engine = VisionEngine()

