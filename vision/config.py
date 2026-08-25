"""
Configuration management and validation for VISION.
Supports Pydantic Settings with automatic pure Python fallback.
"""

import os
from pathlib import Path
from typing import List, Optional

# Load .env file manually if python-dotenv is not installed
def _load_env_file(filepath: str = ".env"):
    p = Path(filepath)
    if not p.exists():
        return
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            # Strip surrounding quotes from values
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                v = v[1:-1]
            if k and k not in os.environ:
                os.environ[k] = v

_load_env_file()


def _get_list(key: str, default: str = "") -> List[str]:
    val = os.getenv(key, default)
    if not val:
        return []
    return [x.strip() for x in val.split(",") if x.strip()]


class VisionConfig:
    def __init__(self):
        # ── LiveKit ──────────────────────────────────────────
        self.LIVEKIT_URL: Optional[str] = os.getenv("LIVEKIT_URL")
        self.LIVEKIT_API_KEY: Optional[str] = os.getenv("LIVEKIT_API_KEY")
        self.LIVEKIT_API_SECRET: Optional[str] = os.getenv("LIVEKIT_API_SECRET")

        # ── Groq API ─────────────────────────────────────────
        self.GROQ_API_KEY: Optional[str] = os.getenv("GROQ_API_KEY")
        self.GROQ_API_KEYS: List[str] = _get_list("GROQ_API_KEYS")

        # ── NVIDIA NIM ───────────────────────────────────────
        self.NVIDIA_API_KEY: Optional[str] = os.getenv("NVIDIA_API_KEY")
        self.NVIDIA_API_KEYS: List[str] = _get_list("NVIDIA_API_KEYS")

        # ── Cartesia TTS ─────────────────────────────────────
        cart_keys = []
        if os.getenv("CARTESIA_API_KEY"):
            cart_keys.append(os.getenv("CARTESIA_API_KEY"))
        cart_keys.extend(_get_list("CARTESIA_API_KEYS"))
        for k, v in os.environ.items():
            if k.startswith("CARTESIA_API_KEY_") and v:
                cart_keys.append(v)
        self.CARTESIA_API_KEYS: List[str] = list(dict.fromkeys([k for k in cart_keys if k]))
        self.CARTESIA_API_KEY: Optional[str] = self.CARTESIA_API_KEYS[0] if self.CARTESIA_API_KEYS else None
        self.CARTESIA_MODEL_ID: str = os.getenv("CARTESIA_MODEL_ID", "sonic-2")
        self.CARTESIA_VOICE_ID: str = os.getenv("CARTESIA_VOICE_ID", "1259b7e3-cb8a-43df-9446-30971a46b8b0")
        self.CARTESIA_SPEED: str = os.getenv("CARTESIA_SPEED", "normal")
        self.CARTESIA_EMOTION: List[str] = ["positivity:high"]
        self.USE_CARTESIA_VOICE: bool = True




        # ── OpenRouter Key Pool ──────────────────────────────
        self.OPENROUTER_API_KEYS: List[str] = _get_list("OPENROUTER_API_KEYS")
        self.OPENROUTER_LLM_MODEL: str = os.getenv("OPENROUTER_LLM_MODEL", "meta-llama/llama-3.3-70b-instruct")
        self.VISION_LOAD_BALANCER_STRATEGY: str = os.getenv("VISION_LOAD_BALANCER_STRATEGY", "least_busy")

        # ── Models & Engines ─────────────────────────────────
        self.VISION_LLM_PROVIDER: str = os.getenv("VISION_LLM_PROVIDER", "groq")
        self.VISION_LLM_MODEL: str = os.getenv("VISION_LLM_MODEL", "llama-3.3-70b-versatile")
        self.VISION_NIM_LLM_MODEL: str = os.getenv("VISION_NIM_LLM_MODEL", "meta/llama-3.1-8b-instruct")
        self.VISION_STT_ENGINE: str = os.getenv("VISION_STT_ENGINE", "groq")
        self.VISION_STT_MODEL: str = os.getenv("VISION_STT_MODEL", "whisper-large-v3-turbo")
        self.VISION_LOCAL_STT_MODEL: str = os.getenv("VISION_LOCAL_STT_MODEL", "small.en")
        try:
            self.VISION_VAD_THRESHOLD: float = float(os.getenv("VISION_VAD_THRESHOLD", "0.55"))
        except (ValueError, TypeError):
            self.VISION_VAD_THRESHOLD = 0.55
        try:
            self.VISION_MIN_SPEECH_DURATION_SEC: float = float(os.getenv("VISION_MIN_SPEECH_DURATION_SEC", "0.45"))
        except (ValueError, TypeError):
            self.VISION_MIN_SPEECH_DURATION_SEC = 0.45
        try:
            self.VISION_SILENCE_TIMEOUT_SEC: float = float(os.getenv("VISION_SILENCE_TIMEOUT_SEC", "0.9"))
        except (ValueError, TypeError):
            self.VISION_SILENCE_TIMEOUT_SEC = 0.9


        # ── Multimodal Vision & Gemini ───────────────────────
        self.GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
        self.GEMINI_API_KEYS: List[str] = _get_list("GEMINI_API_KEYS")

        # ── Mobile & ADB Integration ─────────────────────────
        self.VISION_PHONE_IP: str = os.getenv("VISION_PHONE_IP", "192.168.1.3")
        try:
            self.VISION_PHONE_PORT: int = int(os.getenv("VISION_PHONE_PORT", "42381"))
        except (ValueError, TypeError):
            self.VISION_PHONE_PORT: int = 42381
        self.VISION_PHONE_PASSWORD: str = os.getenv("VISION_PHONE_PASSWORD", "1234")
        self.ADB_PATH: str = os.getenv("ADB_PATH", "adb")

        # ── Media & System ───────────────────────────────────
        self.YOUTUBE_API_KEY: Optional[str] = os.getenv("YOUTUBE_API_KEY")
        self.VISION_EMAIL: Optional[str] = os.getenv("VISION_EMAIL") or os.getenv("EMAIL_SENDER")
        self.EMAIL_PASSWORD: Optional[str] = os.getenv("VISION_EMAIL_PASSWORD") or os.getenv("EMAIL_PASSWORD")
        self.EMAIL_SMTP_HOST: str = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
        try:
            self.EMAIL_SMTP_PORT: int = int(os.getenv("EMAIL_SMTP_PORT", "587"))
        except (ValueError, TypeError):
            self.EMAIL_SMTP_PORT: int = 587

        # ── Remote Ubuntu Server & KPR Watchdog ──────────────
        self.UBUNTU_SERVER_HOST: str = os.getenv("UBUNTU_SERVER_HOST", "100.93.70.63")
        try:
            self.UBUNTU_SERVER_PORT: int = int(os.getenv("UBUNTU_SERVER_PORT", "22"))
        except (ValueError, TypeError):
            self.UBUNTU_SERVER_PORT: int = 22
        self.UBUNTU_SERVER_USER: str = os.getenv("UBUNTU_SERVER_USER", "nandu")
        self.UBUNTU_SERVER_PASSWORD: str = os.getenv("UBUNTU_SERVER_PASSWORD", "1234567890")
        self.KPR_PRINT_SERVER_PATH: str = os.getenv("KPR_PRINT_SERVER_PATH", "/home/nandu/print-server")
        self.KPR_LOG_PATH: str = os.getenv("KPR_LOG_PATH", "/home/nandu/print-server/kpr_print.log")

        # ── Server & Security ────────────────────────────────
        self.HOST: str = os.getenv("HOST", "0.0.0.0")
        try:
            self.PORT: int = int(os.getenv("PORT", "8000"))
        except (ValueError, TypeError):
            self.PORT: int = 8000
        self.DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
        self.SECRET_KEY: str = os.getenv("SECRET_KEY", "vision-default-secret-key-change-me")

        # ── Custom Fine-Tuned Model Endpoint ─────────────────
        self.CUSTOM_MODEL_URL: str = os.getenv("CUSTOM_MODEL_URL", "http://localhost:11434/v1")
        self.CUSTOM_MODEL_NAME: str = os.getenv("CUSTOM_MODEL_NAME", "vision-tool-calling-qlora")
        self.CUSTOM_MODEL_API_KEY: str = os.getenv("CUSTOM_MODEL_API_KEY", "ollama")
        self.ENABLE_CUSTOM_MODEL_PROVIDER: bool = os.getenv(
            "ENABLE_CUSTOM_MODEL_PROVIDER", "False"
        ).lower() in ("true", "1", "yes")


config = VisionConfig()
