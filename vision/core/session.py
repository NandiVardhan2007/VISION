"""
Persistent session and conversation history tracking for VISION.
Stores and loads all past user/assistant conversations in `data/conversations.json`
so conversations persist permanently across app reboots.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
import json
import time
import uuid
from vision.logger import logger

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CONVERSATIONS_FILE = DATA_DIR / "conversations.json"


@dataclass
class Message:
    role: str
    content: Optional[str] = None
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    label: Optional[str] = None
    time_str: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp
        }
        if self.name:
            d["name"] = self.name
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.label:
            d["label"] = self.label
        if self.time_str:
            d["time"] = self.time_str
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(
            role=data.get("role", "user"),
            content=data.get("content"),
            name=data.get("name"),
            tool_calls=data.get("tool_calls"),
            tool_call_id=data.get("tool_call_id"),
            timestamp=data.get("timestamp", time.time()),
            label=data.get("label"),
            time_str=data.get("time")
        )


@dataclass
class Session:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    channel: str = "web"
    user_id: str = "default_user"
    messages: List[Message] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)

    def add_message(self, role: str, content: Optional[str] = None, **kwargs) -> Message:
        msg = Message(role=role, content=content, **kwargs)
        self.messages.append(msg)
        self.last_active_at = time.time()
        # Persist only genuine conversational turns (user/assistant text) to the
        # durable transcript. Tool results and empty assistant tool-call stubs are
        # working-memory only. Previously this called session_manager.save_to_disk()
        # directly, which re-wrote the untouched _transcripts list — so new turns
        # were never persisted (lost on restart) and every message triggered a
        # redundant full-file rewrite.
        if role in ("user", "assistant") and content and not kwargs.get("tool_calls"):
            session_manager.append_transcript(
                speaker="ai" if role == "assistant" else "user",
                label="VISION" if role == "assistant" else "You",
                text=content,
            )
        return msg

    def get_messages_for_llm(self, max_history: int = 25) -> List[Dict[str, Any]]:
        # Retrieve recent non-tool or tool-paired context for LLM
        recent = self.messages[-max_history:]
        formatted = []
        for m in recent:
            item: Dict[str, Any] = {"role": m.role}
            if m.content is not None:
                item["content"] = m.content
            if m.name:
                item["name"] = m.name
            if m.tool_calls:
                item["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                item["tool_call_id"] = m.tool_call_id
            formatted.append(item)
        return formatted

    def clear(self):
        self.messages.clear()
        self.last_active_at = time.time()
        session_manager.save_to_disk()


def _parse_timestamp(ts_str: Any) -> float:
    if not ts_str or not isinstance(ts_str, str):
        return time.time()
    try:
        cleaned = ts_str.strip().replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).timestamp()
    except Exception:
        return time.time()


class SessionManager:
    def __init__(self):
        self._sessions: Dict[str, Session] = {}
        self._transcripts: List[Dict[str, Any]] = []
        self._ensure_dir()
        self.load_from_disk()

    def _ensure_dir(self):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"[SessionManager] Error creating data directory: {e}")

    def load_from_disk(self):
        """Loads persistent conversations from data/conversations.json."""
        if not CONVERSATIONS_FILE.exists():
            logger.info("[SessionManager] No previous conversations.json found. Starting fresh.")
            return

        try:
            with open(CONVERSATIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            raw_transcripts = data.get("conversations") or []
            self._transcripts = raw_transcripts

            # Populate primary sessions so LLM immediately has past conversation turns in working memory
            target_session_ids = ["vision_hud_session", "web_session", "default_session"]
            for s_id in target_session_ids:
                s = self.get_or_create(s_id)
                s.messages.clear()

                # Only seed the last 200 turns into each live session's working
                # memory — loading the full on-disk history would balloon the LLM
                # context (and memory) on every restart as the archive grows.
                for item in raw_transcripts[-200:]:
                    speaker = item.get("speaker", "user")
                    role = "assistant" if speaker == "ai" else "user"
                    text = item.get("text", "")
                    if text:
                        msg = Message(
                            role=role,
                            content=text,
                            label=item.get("label"),
                            time_str=item.get("time"),
                            timestamp=_parse_timestamp(item.get("timestamp"))
                        )
                        s.messages.append(msg)

            logger.info(f"[SessionManager] Loaded {len(self._transcripts)} persistent conversation messages from {CONVERSATIONS_FILE}")
        except Exception as e:
            logger.warning(f"[SessionManager] Error loading conversations.json: {e}")

    def save_to_disk(self):
        """Atomically saves all conversation history to data/conversations.json."""
        try:
            self._ensure_dir()
            payload = {
                "last_updated": datetime.now().isoformat(),
                "total_conversations": len(self._transcripts),
                "conversations": self._transcripts
            }
            tmp_file = CONVERSATIONS_FILE.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            tmp_file.replace(CONVERSATIONS_FILE)
            logger.debug(f"[SessionManager] Persisted {len(self._transcripts)} messages to {CONVERSATIONS_FILE}")
        except Exception as e:
            logger.error(f"[SessionManager] Error saving conversations.json: {e}")

    def get_or_create(self, session_id: Optional[str] = None, channel: str = "web", user_id: str = "default_user") -> Session:
        s_id = session_id or "vision_hud_session"
        if s_id not in self._sessions:
            self._sessions[s_id] = Session(session_id=s_id, channel=channel, user_id=user_id)
        return self._sessions[s_id]

    def get(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def get_all_transcripts(self) -> List[Dict[str, Any]]:
        """Returns the full list of transcripts for the frontend/API."""
        return list(self._transcripts)

    def append_transcript(self, speaker: str, label: str, text: str, time_str: Optional[str] = None, timestamp: Optional[str] = None):
        """Appends a new conversation entry and persists it to conversations.json."""
        now = datetime.now()
        entry = {
            "index": len(self._transcripts) + 1,
            "speaker": speaker,
            "label": label,
            "text": text,
            "time": time_str or now.strftime("%I:%M:%S %p"),
            "timestamp": timestamp or now.isoformat()
        }
        self._transcripts.append(entry)
        # Cap persisted history: save_to_disk rewrites the entire list on every
        # append, so an unbounded transcript means ever-growing files and O(n)
        # writes. Keep the most recent 2000 turns.
        MAX_TRANSCRIPTS = 2000
        if len(self._transcripts) > MAX_TRANSCRIPTS:
            del self._transcripts[:-MAX_TRANSCRIPTS]
        self.save_to_disk()
        return entry

    def set_all_transcripts(self, transcripts: List[Dict[str, Any]]):
        """Overwrites transcript list with validated list and persists."""
        self._transcripts = transcripts
        self.save_to_disk()

    def clear_all(self):
        """Clears all conversation history."""
        self._transcripts = []
        for s in self._sessions.values():
            s.messages.clear()
        self.save_to_disk()


# Global session manager singleton
session_manager = SessionManager()
