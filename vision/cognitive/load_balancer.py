"""
Autonomous Cognitive Load Balancer orchestrating 20+ LLM endpoints,
persistent key health tracking across restarts, and instant failover.
"""

import time
import asyncio
from typing import List, Dict, Any, AsyncGenerator, Optional
from vision.config import config
from vision.logger import logger
from vision.cognitive.providers.base import BaseLLMProvider
from vision.cognitive.providers.groq_llm import GroqLLMProvider
from vision.cognitive.providers.openai_compatible import OpenAICompatibleProvider
from vision.cognitive.providers.gemini_llm import GeminiLLMProvider
from vision.cognitive.key_manager import key_manager


def _is_rate_limit_error(e: Exception) -> bool:
    """Detect a rate-limit error via the SDK status code first, then fall back
    to substring matching (avoids both false positives from ids containing '429'
    and false negatives when the message is worded differently)."""
    status = getattr(e, "status_code", None) or getattr(e, "code", None)
    if status == 429:
        return True
    err_str = str(e).lower()
    return "429" in err_str or "rate_limit" in err_str or "rate limit" in err_str or "tokens per day" in err_str


class LoadBalancer:
    def __init__(self, strategy: str = "least_busy"):
        self.strategy = strategy
        self.providers: List[BaseLLMProvider] = []
        self._round_robin_idx = 0
        self._initialize_providers()

    def _initialize_providers(self):
        """Initialize all provider instances across all configured API keys."""
        # 1. Primary: Groq Multi-Key Cluster
        groq_keys = ([config.GROQ_API_KEY] if config.GROQ_API_KEY else []) + config.GROQ_API_KEYS
        for idx, key in enumerate(groq_keys):
            self.providers.append(
                GroqLLMProvider(api_key=key, model=config.VISION_LLM_MODEL)
            )

        # 2. NVIDIA NIM Cluster
        nvidia_keys = ([config.NVIDIA_API_KEY] if config.NVIDIA_API_KEY else []) + config.NVIDIA_API_KEYS
        for idx, key in enumerate(nvidia_keys):
            self.providers.append(
                OpenAICompatibleProvider(
                    name=f"NVIDIA-NIM-{idx+1}",
                    api_key=key,
                    base_url="https://integrate.api.nvidia.com/v1",
                    model=config.VISION_NIM_LLM_MODEL
                )
            )

        # 3. OpenRouter Failover
        for idx, key in enumerate(config.OPENROUTER_API_KEYS):
            self.providers.append(
                OpenAICompatibleProvider(
                    name=f"OpenRouter-{idx+1}",
                    api_key=key,
                    base_url="https://openrouter.ai/api/v1",
                    model=config.OPENROUTER_LLM_MODEL,
                    default_headers={"HTTP-Referer": "https://vision.ai", "X-Title": "VISION AI"}
                )
            )

        # 4. Google Gemini (Multimodal / Fallback)
        if config.GEMINI_API_KEY:
            self.providers.append(
                GeminiLLMProvider(api_key=config.GEMINI_API_KEY)
            )

        # 5. Custom fine-tuned model (local Ollama/vLLM/llama.cpp endpoint)
        # Opt-in via ENABLE_CUSTOM_MODEL_PROVIDER=true so an offline local
        # endpoint never sits at the front of the failover chain by accident.
        if getattr(config, "ENABLE_CUSTOM_MODEL_PROVIDER", False):
            from vision.cognitive.providers.custom_finetuned_llm import (
                CustomFineTunedLLMProvider,
            )
            self.providers.append(CustomFineTunedLLMProvider())
            logger.info("[LoadBalancer] Custom fine-tuned model provider enabled.")

        logger.info(f"[LoadBalancer] Initialized {len(self.providers)} endpoints with strategy '{self.strategy}'.")

    def _is_on_cooldown(self, provider: BaseLLMProvider) -> bool:
        """Check if provider key is in rate-limit cooldown via persistent key_manager."""
        api_key = getattr(provider, "api_key", None)
        if api_key:
            return not key_manager.is_available(api_key)
        return False

    def _select_provider_order(self) -> List[BaseLLMProvider]:
        """Return a ranked list of available providers, prioritizing healthy active keys."""
        if not self.providers:
            raise RuntimeError("No LLM providers configured.")

        # Separate healthy active vs rate-limited providers
        active = [p for p in self.providers if not self._is_on_cooldown(p)]

        if not active:
            # If all are in cooldown, use least recently cooled
            active = sorted(self.providers, key=lambda p: key_manager.get_remaining_cooldown(getattr(p, 'api_key', '')))

        if self.strategy == "least_busy":
            ordered_active = sorted(active, key=lambda p: (p.active_requests, p.failed_requests))
        elif self.strategy == "latency_based":
            ordered_active = sorted(active, key=lambda p: (p.average_latency_ms, p.failed_requests))
        elif self.strategy == "round_robin":
            n = len(active)
            idx = self._round_robin_idx % max(1, n)
            self._round_robin_idx += 1
            ordered_active = active[idx:] + active[:idx]
        else:
            ordered_active = list(active)

        return ordered_active

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """Execute chat completion with automatic failover across ranked providers."""
        ranked_providers = self._select_provider_order()
        last_error = None

        for provider in ranked_providers:
            # NOTE: do NOT skip cooled-down providers here. _select_provider_order
            # already de-prioritizes them, but when every key is rate-limited it
            # deliberately returns them ordered by soonest-to-recover. Skipping
            # them here would mean *no* provider is ever attempted in that case,
            # turning a temporary rate limit into a total outage.
            try:
                logger.debug(f"[LoadBalancer] Routing to '{provider.name}' ({provider.model})")
                # Hard cap on top of each SDK's own timeout so any provider that
                # hangs past its client timeout still triggers failover.
                return await asyncio.wait_for(
                    provider.chat_completion(
                        messages=messages,
                        tools=tools,
                        temperature=temperature,
                        max_tokens=max_tokens
                    ),
                    timeout=30,
                )
            except Exception as e:
                err_str = str(e)
                # Persist rate limit to disk so next query immediately skips this key
                if _is_rate_limit_error(e):
                    api_key = getattr(provider, "api_key", None)
                    if api_key:
                        key_manager.mark_rate_limited(api_key, err_str)
                    logger.info(f"[LoadBalancer] Key rate-limited on '{provider.name}'. Instantly routing to next provider...")
                else:
                    logger.warning(f"[LoadBalancer] Provider '{provider.name}' failed: {e}. Failing over.")
                last_error = e

        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    async def stream_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> AsyncGenerator[str, None]:
        """Stream tokens with failover on initial connection."""
        ranked_providers = self._select_provider_order()
        last_error = None
        for provider in ranked_providers:
            # See chat_completion: never skip cooled-down providers here or an
            # all-rate-limited state produces a silently empty stream.
            yielded = False
            try:
                async for chunk in provider.stream_chat_completion(
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens
                ):
                    yielded = True
                    yield chunk
                return
            except Exception as e:
                err_str = str(e)
                if _is_rate_limit_error(e):
                    api_key = getattr(provider, "api_key", None)
                    if api_key:
                        key_manager.mark_rate_limited(api_key, err_str)
                logger.warning(f"[LoadBalancer] Stream provider '{provider.name}' failed: {e}. Failing over.")
                last_error = e
                if yielded:
                    # Partial output already emitted downstream; failing over to
                    # another provider would concatenate a second, duplicated
                    # response onto the garbled first. Abort instead.
                    raise RuntimeError(
                        f"Streaming provider '{provider.name}' failed after partial output: {e}"
                    ) from e

        raise RuntimeError(f"All LLM streaming providers failed. Last error: {last_error}")


# Global Load Balancer Singleton
load_balancer = LoadBalancer(strategy=config.VISION_LOAD_BALANCER_STRATEGY)
LLMLoadBalancer = LoadBalancer
