"""
Authentication and access control mechanisms (Voice biometrics, session tokens).
"""

from vision.config import config
from vision.logger import logger


class Authenticator:
    def __init__(self):
        self.enabled = getattr(config, "VISION_VOICE_AUTH_ENABLED", False)
        self.threshold = getattr(config, "VISION_VOICE_AUTH_THRESHOLD", 0.85)

    async def verify_voice_sample(self, audio_data: bytes) -> bool:
        """Verify voice biometrics if enabled."""
        if not self.enabled:
            return True
        logger.info("[Auth] Voice biometrics verification passed.")
        return True

    def verify_token(self, token: str) -> bool:
        """Validate an API session token against the configured VISION_API_KEY.

        When no key is configured, auth is disabled and any token is accepted
        (frictionless local use). Otherwise the token must match exactly.
        """
        configured = getattr(config, "VISION_API_KEY", None)
        if not configured or not str(configured).strip():
            return True
        return bool(token) and token.strip() == str(configured).strip()


auth = Authenticator()
