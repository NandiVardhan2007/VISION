"""
Unit tests for permanent conversation history JSON persistence and session endpoints.
"""

import json
import pytest
from fastapi.testclient import TestClient

from vision.gateways.web.server import app
from vision.core.session import session_manager, CONVERSATIONS_FILE


def test_conversations_json_persistence():
    """Verify conversations are saved to data/conversations.json and loaded across app sessions."""
    client = TestClient(app)

    test_conversations = [
        {
            "index": 1,
            "speaker": "ai",
            "label": "VISION",
            "text": "VISION is online.",
            "time": "System",
            "timestamp": "2026-08-23T18:00:00.000Z"
        },
        {
            "index": 2,
            "speaker": "user",
            "label": "You (Spoken)",
            "text": "VISION, do you remember our conversation yesterday?",
            "time": "06:00:05 PM",
            "timestamp": "2026-08-23T18:00:05.000Z"
        },
        {
            "index": 3,
            "speaker": "ai",
            "label": "VISION",
            "text": "Yes, Nandu! I have all our past conversations saved in my codebase.",
            "time": "06:00:08 PM",
            "timestamp": "2026-08-23T18:00:08.000Z"
        }
    ]

    # 1. Sync conversations
    sync_resp = client.post(
        "/api/conversations/sync",
        json={"conversations": test_conversations}
    )
    assert sync_resp.status_code == 200
    assert sync_resp.json()["status"] == "success"

    # 2. Verify file exists on disk in codebase
    assert CONVERSATIONS_FILE.exists()
    with open(CONVERSATIONS_FILE, "r", encoding="utf-8") as f:
        file_data = json.load(f)
    assert file_data["total_conversations"] == 3
    assert file_data["conversations"][1]["text"] == "VISION, do you remember our conversation yesterday?"

    # 3. Verify GET /api/conversations returns the full history
    get_resp = client.get("/api/conversations")
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["status"] == "success"
    assert len(get_data["conversations"]) == 3
    assert get_data["conversations"][2]["text"] == "Yes, Nandu! I have all our past conversations saved in my codebase."

    # 4. Simulate app reboot: reload from disk
    session_manager.load_from_disk()
    transcripts = session_manager.get_all_transcripts()
    assert len(transcripts) == 3
    assert transcripts[1]["text"] == "VISION, do you remember our conversation yesterday?"
