"""
Groq LLM Provider Adapter with token rate limiting, multi-key support,
and self-healing function recovery for malformed tool generations.
"""

import re
import json
import time
from typing import List, Dict, Any, AsyncGenerator, Optional
from vision.cognitive.providers.base import BaseLLMProvider
from vision.logger import logger

try:
    from groq import AsyncGroq
except ImportError:
    AsyncGroq = None


class GroqLLMProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile"):
        super().__init__(name="Groq", model=model)
        self.api_key = api_key
        # Cap every request so a stalled connection triggers failover instead of
        # blocking the whole chain for the SDK's ~600s default.
        self.client = AsyncGroq(api_key=api_key, timeout=20.0, max_retries=1) if AsyncGroq else None
        self._total_latency_ms = 0.0

    def _recover_failed_tool_call(self, err_msg: str) -> Optional[List[Dict[str, Any]]]:
        """Recover tool calls from Groq's failed_generation raw XML or JSON string."""
        # 1. XML style: <function=name>{...}</function>
        m = re.search(r"<function=(\w+)>(.*?)(?:</function>|$)", err_msg, re.DOTALL)
        if not m:
            m = re.search(r"<function=(\w+)[\s\(]*(\{.*?\})[\s\)]*(?:>)?(?:</function>)?", err_msg, re.DOTALL)
        if m:
            func_name = m.group(1)
            raw_args = m.group(2).strip()
            parsed_args = {}
            try:
                parsed_args = json.loads(raw_args)
            except Exception:
                start = raw_args.find("{")
                end = raw_args.rfind("}")
                if start != -1 and end != -1:
                    try:
                        parsed_args = json.loads(raw_args[start:end+1])
                    except Exception:
                        pass

            call_id = f"call_recovered_{int(time.time() * 1000)}"
            logger.info(f"[GroqLLM] Self-healed malformed XML tool call -> {func_name}({parsed_args})")
            return [{
                "id": call_id,
                "type": "function",
                "function": {
                    "name": func_name,
                    "arguments": json.dumps(parsed_args)
                }
            }]

        # 2. JSON style inside failed_generation (e.g. 'failed_generation': '{"name": "snap_window", "arguments": {"direction":"left"}}')
        fg_match = re.search(r"failed_generation['\"]?\s*:\s*['\"](\{.*?\})['\"]", err_msg)
        candidate_str = fg_match.group(1) if fg_match else None

        if not candidate_str:
            name_match = re.search(r'(\{\s*"(?:name|function)"\s*:\s*.*?\})', err_msg)
            if name_match:
                candidate_str = name_match.group(1)

        if candidate_str:
            candidate_str = candidate_str.replace('\\"', '"').replace("\\'", "'")
            try:
                data = json.loads(candidate_str)
                func_name = data.get("name") or (data.get("function") or {}).get("name")
                args = data.get("arguments") or data.get("parameters") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        pass
                if func_name:
                    call_id = f"call_recovered_{int(time.time() * 1000)}"
                    logger.info(f"[GroqLLM] Self-healed malformed JSON tool call -> {func_name}({args})")
                    return [{
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": func_name,
                            "arguments": json.dumps(args) if isinstance(args, dict) else str(args)
                        }
                    }]
            except Exception as e:
                logger.debug(f"[GroqLLM] Could not parse candidate JSON tool call: {e}")

        return None

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        if not self.client:
            raise RuntimeError("groq package is not installed.")

        self.active_requests += 1
        start_time = time.time()
        try:
            kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
            }
            if max_tokens:
                kwargs["max_tokens"] = max_tokens
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            response = await self.client.chat.completions.create(**kwargs)
            duration_ms = (time.time() - start_time) * 1000
            self._update_stats(duration_ms)

            # OpenAI-compatible endpoints can return HTTP 200 with choices:[] on
            # an upstream hiccup — surface it clearly instead of an IndexError.
            if not response.choices:
                raise RuntimeError(f"[{self.name}] empty choices in response")
            choice = response.choices[0]
            message_obj = choice.message
            tool_calls = None
            if message_obj.tool_calls:
                tool_calls = [tc.model_dump() for tc in message_obj.tool_calls]

            return {
                "role": "assistant",
                "content": message_obj.content,
                "tool_calls": tool_calls,
                "finish_reason": choice.finish_reason,
                "provider": self.name,
                "latency_ms": duration_ms
            }
        except Exception as e:
            err_str = str(e)
            # Automatic fallback if model is decommissioned / not found on Groq
            if "model_not_found" in err_str or "does not exist" in err_str or "model_decommissioned" in err_str:
                fallback_model = "openai/gpt-oss-120b"
                if self.model != fallback_model:
                    logger.warning(f"[GroqLLM] Model '{self.model}' unavailable on Groq. Auto-recovering with '{fallback_model}'.")
                    self.model = fallback_model
                    kwargs["model"] = fallback_model
                    try:
                        response = await self.client.chat.completions.create(**kwargs)
                        duration_ms = (time.time() - start_time) * 1000
                        self._update_stats(duration_ms)
                        if not response.choices:
                            raise RuntimeError(f"[{self.name}] empty choices in fallback response")
                        choice = response.choices[0]
                        message_obj = choice.message
                        tool_calls = None
                        if message_obj.tool_calls:
                            tool_calls = [tc.model_dump() for tc in message_obj.tool_calls]
                        return {
                            "role": "assistant",
                            "content": message_obj.content,
                            "tool_calls": tool_calls,
                            "finish_reason": choice.finish_reason,
                            "provider": self.name,
                            "latency_ms": duration_ms
                        }
                    except Exception as e2:
                        err_str = str(e2)

            # Check for self-healing tool call recovery on Groq 400
            if "failed_generation" in err_str or "tool_use_failed" in err_str:
                recovered = self._recover_failed_tool_call(err_str)
                if recovered:
                    duration_ms = (time.time() - start_time) * 1000
                    self._update_stats(duration_ms)
                    return {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": recovered,
                        "finish_reason": "tool_calls",
                        "provider": self.name,
                        "latency_ms": duration_ms
                    }

            self.failed_requests += 1
            if "429" in err_str or "rate_limit" in err_str or "tokens per day" in err_str:
                logger.debug(f"[GroqLLM] Rate limit encountered on key {self.api_key[:8]}... Yielding to load balancer.")
            else:
                logger.error(f"[GroqLLM] Completion failed: {e}")
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
            raise RuntimeError("groq package is not installed.")

        self.active_requests += 1
        try:
            kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "stream": True
            }
            if max_tokens:
                kwargs["max_tokens"] = max_tokens
            # Forward tools when supplied instead of silently dropping them.
            if tools:
                kwargs["tools"] = tools

            stream = await self.client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        finally:
            self.active_requests = max(0, self.active_requests - 1)

    def _update_stats(self, duration_ms: float):
        self.total_requests += 1
        self._total_latency_ms += duration_ms
        self.average_latency_ms = self._total_latency_ms / max(1, self.total_requests)
