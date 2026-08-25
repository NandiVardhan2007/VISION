"""
Custom Fine-Tuned Model Provider for VISION.
Connects to local or remote endpoints (Ollama, vLLM, LM Studio, llama.cpp, TGI)
serving the fine-tuned VISION tool-calling model.
"""

from typing import Optional
from vision.cognitive.providers.openai_compatible import OpenAICompatibleProvider
from vision.config import config
from vision.logger import logger


class CustomFineTunedLLMProvider(OpenAICompatibleProvider):
    """
    Dedicated provider for fine-tuned VISION models.
    Supports local OpenAI-compatible endpoints with automatic fallback.
    """
    def __init__(
        self,
        name: str = "custom_finetuned_llm",
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None
    ):
        url = base_url or config.CUSTOM_MODEL_URL
        model_name = model or config.CUSTOM_MODEL_NAME
        key = api_key or config.CUSTOM_MODEL_API_KEY

        super().__init__(
            name=name,
            api_key=key,
            base_url=url,
            model=model_name
        )
        logger.info(f"[CustomFineTunedLLM] Initialized provider '{name}' pointing to {url} (model: {model_name})")
