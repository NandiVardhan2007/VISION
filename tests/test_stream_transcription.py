"""
Unit tests for SSE chat streaming and live transcription token callbacks.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from vision.gateways.web.server import app
from vision.core.engine import vision_engine


def test_chat_stream_endpoint():
    """Verify POST /api/chat/stream returns SSE events (start, tokens, done)."""
    client = TestClient(app)

    async def mock_process(user_text, session_id="default_session", channel="web", synthesize_voice=True, token_callback=None):
        if token_callback:
            await token_callback("Hello")
            await token_callback(" Nandu!")
        return {
            "response": "Hello Nandu!",
            "provider": "MockAI",
            "latency_ms": 120.0
        }

    with patch.object(vision_engine, "process_user_input", side_effect=mock_process):
        response = client.post(
            "/api/chat/stream",
            json={
                "message": "Hello Vision",
                "session_id": "test_stream_session",
                "synthesize_voice": False
            }
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        events = []
        for line in response.text.split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[6:])
                events.append(data)

        types = [e["type"] for e in events]
        assert "start" in types
        assert "token" in types
        assert "done" in types

        done_event = next(e for e in events if e["type"] == "done")
        assert done_event["response"] == "Hello Nandu!"
