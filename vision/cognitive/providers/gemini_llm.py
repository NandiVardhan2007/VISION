"""
Google Gemini LLM Provider Adapter with vision and function calling support.
Uses active gemini-1.5-flash model.
"""

from typing import List, Dict, Any, AsyncGenerator, Optional
import time
import warnings
from vision.cognitive.providers.base import BaseLLMProvider
from vision.logger import logger

warnings.filterwarnings("ignore", category=FutureWarning, message=".*google.generativeai.*")

try:
    import google.generativeai as genai
except ImportError:
    genai = None


class GeminiLLMProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        super().__init__(name="Gemini", model=model)
        self.api_key = api_key
        if genai and api_key:
            genai.configure(api_key=api_key)
            self.client = genai.GenerativeModel(model_name=model)
        else:
            self.client = None

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        if not self.client:
            raise RuntimeError("google-generativeai package not installed or API key missing.")

        self.active_requests += 1
        start_time = time.time()
        try:
            contents = []
            for msg in messages:
                msg_role = msg.get("role", "user")
                content = msg.get("content") or ""

                # Skip assistant messages that are purely tool_calls with no text
                if msg_role == "assistant" and msg.get("tool_calls") and not content:
                    continue

                # Convert tool result messages to user messages
                if msg_role == "tool":
                    tool_name = msg.get("name", "tool")
                    content = f"[Tool Result from {tool_name}]: {content}"
                    msg_role = "user"

                role = "user" if msg_role in ["user", "system", "tool"] else "model"
                if content:
                    contents.append({"role": role, "parts": [content]})

            response = await self.client.generate_content_async(
                contents,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens
                ),
                request_options={"timeout": 20}
            )
            duration_ms = (time.time() - start_time) * 1000
            self._update_stats(duration_ms)

            # response.text raises ValueError when the candidate has no text part
            # (safety/recitation block, or MAX_TOKENS with no text). Treat that as
            # an empty reply so a blocked Gemini turn doesn't crash the balancer.
            try:
                text = response.text
            except Exception:
                text = ""

            return {
                "role": "assistant",
                "content": text,
                "tool_calls": None,
                "finish_reason": "stop",
                "provider": self.name,
                "latency_ms": duration_ms
            }
        except Exception as e:
            self.failed_requests += 1
            logger.error(f"[GeminiLLM] Completion failed: {e}")
            raise e
        finally:
            self.active_requests = max(0, self.active_requests - 1)

    async def stream_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> AsyncGenerator[str, None]:
        if not self.client:
            raise RuntimeError("google-generativeai package not installed or API key missing.")

        self.active_requests += 1
        try:
            contents = []
            for msg in messages:
                msg_role = msg.get("role", "user")
                content = msg.get("content") or ""

                # Skip assistant tool-call stubs with no text (mirrors chat_completion)
                if msg_role == "assistant" and msg.get("tool_calls") and not content:
                    continue

                # Fold tool results into a user turn so Gemini sees them as input
                if msg_role == "tool":
                    tool_name = msg.get("name", "tool")
                    content = f"[Tool Result from {tool_name}]: {content}"
                    msg_role = "user"

                role = "user" if msg_role in ["user", "system", "tool"] else "model"
                if content:
                    # Never append parts:[None] — the Gemini API rejects it.
                    contents.append({"role": role, "parts": [content]})

            response = await self.client.generate_content_async(
                contents,
                stream=True,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens
                ),
                request_options={"timeout": 20}
            )
            async for chunk in response:
                # .text raises on non-text/blocked chunks — skip them instead of
                # aborting the whole stream.
                try:
                    chunk_text = chunk.text
                except Exception:
                    chunk_text = ""
                if chunk_text:
                    yield chunk_text
        finally:
            self.active_requests = max(0, self.active_requests - 1)

    def _update_stats(self, duration_ms: float):
        self.total_requests += 1
        self.average_latency_ms = (
            (self.average_latency_ms * (self.total_requests - 1) + duration_ms) / self.total_requests
        )
