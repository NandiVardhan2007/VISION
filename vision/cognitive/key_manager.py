"""
Persistent API Key State & Rate-Limit Manager for VISION.
Saves rate-limited API keys with exact reset timestamps to `data/key_state.json` so that
exhausted keys are remembered across system restarts, and fresh keys are prioritized.
"""

import json
import time
import re
import os
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional
from vision.logger import logger


class KeyStateManager:
    def __init__(self, state_file: str = None):
        if state_file is None:
            project_root = Path(__file__).resolve().parent.parent.parent
            state_file = str(project_root / "data" / "key_state.json")
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        # {key_id: {"exhausted": True, "cooldown_until": timestamp, "error_msg": str}}
        self._state: Dict[str, Dict[str, Any]] = {}
        self._load_state()

    def _get_key_id(self, api_key: str) -> str:
        """Create a safe masked key identifier."""
        if not api_key:
            return "unknown"
        prefix = api_key[:8]
        suffix = api_key[-4:] if len(api_key) > 12 else ""
        h = hashlib.sha256(api_key.encode()).hexdigest()[:8]
        return f"{prefix}...{suffix}_{h}"

    def _load_state(self):
        """Load persistent key state from disk."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    now = time.time()
                    # Filter out expired cooldowns
                    self._state = {
                        k: v for k, v in data.items()
                        if v.get("cooldown_until", 0) > now
                    }
                logger.info(f"[KeyManager] Loaded persistent key state. {len(self._state)} key(s) currently on rate-limit cooldown.")
            except Exception as e:
                logger.warning(f"[KeyManager] Failed to load key state: {e}")
                self._state = {}

    def _save_state(self):
        """Save persistent key state to disk atomically (tmp + replace) so a
        crash mid-write cannot corrupt/empty the cooldown state."""
        try:
            tmp = self.state_file.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2)
            os.replace(tmp, self.state_file)
        except Exception as e:
            logger.warning(f"[KeyManager] Failed to persist key state: {e}")

    def parse_retry_duration(self, err_msg: str) -> float:
        """Parse retry duration from Groq / LLM error message (e.g. '1h12m29s' or '21m6s')."""
        default_seconds = 1800.0  # 30 min default
        # Per-minute (RPM/TPM) limits recover fast, so use a small floor; only
        # per-day quotas warrant a long minimum cooldown.
        is_daily = "per day" in err_msg.lower() or "tokens per day" in err_msg.lower()
        floor = 600.0 if is_daily else 15.0
        m = re.search(r"try again in\s+(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:([\d\.]+)s)?", err_msg, re.IGNORECASE)
        if m:
            hours = float(m.group(1) or 0)
            minutes = float(m.group(2) or 0)
            seconds = float(m.group(3) or 0)
            total = (hours * 3600) + (minutes * 60) + seconds
            if total > 0:
                # Add safety buffer so keys aren't called right at the boundary
                return max(floor, total + 120.0)
        return default_seconds

    def mark_rate_limited(self, api_key: str, err_msg: str):
        """Mark an API key as rate-limited and persist cooldown across restarts."""
        key_id = self._get_key_id(api_key)
        duration = self.parse_retry_duration(err_msg)
        cooldown_until = time.time() + duration

        self._state[key_id] = {
            "exhausted": True,
            "cooldown_until": cooldown_until,
            "cooldown_duration_sec": duration,
            "set_at": time.time(),
            "reason": err_msg[:120]
        }
        self._save_state()
        logger.warning(f"[KeyManager] Key [{key_id}] marked RATE-LIMITED for {round(duration/60, 1)} minutes. Persisted to disk.")

    def is_available(self, api_key: str) -> bool:
        """Check if an API key is healthy and not in cooldown."""
        if not api_key:
            return False
        key_id = self._get_key_id(api_key)
        entry = self._state.get(key_id)
        if not entry:
            return True

        if time.time() > entry.get("cooldown_until", 0):
            # Cooldown expired! Re-enable key
            self._state.pop(key_id, None)
            self._save_state()
            logger.info(f"[KeyManager] Cooldown expired for key [{key_id}]. Key is now active again.")
            return True

        return False

    def get_remaining_cooldown(self, api_key: str) -> float:
        """Get remaining cooldown time in seconds."""
        key_id = self._get_key_id(api_key)
        entry = self._state.get(key_id)
        if not entry:
            return 0.0
        return max(0.0, entry.get("cooldown_until", 0) - time.time())

    def get_cluster_status(self) -> Dict[str, Any]:
        """Return summary of all tracked keys and cooldowns."""
        return {
            "total_rate_limited_keys": len(self._state),
            "keys_in_cooldown": {
                k: f"{round(max(0.0, v.get('cooldown_until', 0) - time.time())/60, 1)}m remaining"
                for k, v in self._state.items()
            }
        }


# Global KeyStateManager Singleton
key_manager = KeyStateManager()
