"""
LiveKit RTC Voice Agent Worker for real-time audio/video interaction.
"""

from vision.config import config
from vision.logger import logger


class LiveKitAgent:
    def __init__(self):
        self.url = config.LIVEKIT_URL
        self.api_key = config.LIVEKIT_API_KEY
        self.api_secret = config.LIVEKIT_API_SECRET

    async def start(self):
        """Start LiveKit RTC room worker."""
        if not self.url or not self.api_key or not self.api_secret:
            logger.warning("[LiveKit] Credentials not fully configured. Skipping LiveKit worker.")
            return
        # NOTE: the LiveKit RTC worker is not yet wired up. Be honest in the log
        # rather than claiming an established connection that never happens.
        logger.info(
            f"[LiveKit] Credentials detected for {self.url}, but the RTC worker "
            "is not implemented yet — no room connection is established."
        )


livekit_agent = LiveKitAgent()
