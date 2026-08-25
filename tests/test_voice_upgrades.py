"""
Unit and integration tests for VISION Cartesia Voice & Latency Upgrades:
- Full-Duplex Interruption & Barge-in
- CartesiaTTS streaming neural synthesis & multi-key failover
- Pipelined sentence synthesis & chunking
- Clean text speech normalization
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from vision.synthesis.player import AudioPlayer, audio_player
from vision.synthesis.cartesia_tts import CartesiaTTS, cartesia_tts
from vision.core.engine import VisionEngine, clean_text_for_speech


@pytest.mark.asyncio
async def test_audio_player_interrupt():
    """Test that AudioPlayer responds immediately to stop() and sets interrupt event."""
    player = AudioPlayer()
    assert not player.is_interrupted()
    player.stop()
    assert player.is_interrupted()
    player.reset_interrupt()
    assert not player.is_interrupted()


@pytest.mark.asyncio
async def test_cartesia_tts_key_rotation():
    """Test that CartesiaTTS automatically rotates keys upon quota exhaustion / 402 / 429."""
    tts = CartesiaTTS(api_key="key1")
    tts.api_keys = ["key1", "key2"]
    tts.current_key_index = 0

    mock_resp_fail = MagicMock()
    mock_resp_fail.status_code = 402
    mock_resp_fail.text = "Quota exceeded"

    mock_resp_ok = MagicMock()
    mock_resp_ok.status_code = 200
    mock_resp_ok.content = b"RIFF....WAVEfmt ...."

    mock_client = AsyncMock()
    mock_client.post.side_effect = [mock_resp_fail, mock_resp_ok]

    with patch.object(tts, "_get_client", return_value=mock_client):
        audio = await tts.synthesize("Hello world")
        assert audio == b"RIFF....WAVEfmt ...."
        # A 402 permanently prunes the exhausted key: key1 is removed and the
        # pool now contains only the surviving key(s).
        assert "key1" not in tts.api_keys
        assert tts._get_active_api_key() != "key1"


def test_clean_text_for_speech():
    """Test markdown normalization and cleaning for speech output."""
    raw = "Here is the plan:\n\n* First item\n* Second item\n\n```python\nprint('hello')\n```\nDone!"
    cleaned = clean_text_for_speech(raw)
    assert "```" not in cleaned
    assert "First item" in cleaned
    assert "Second item" in cleaned
    assert "Done!" in cleaned


@pytest.mark.asyncio
async def test_speak_pipelined_interruption():
    """Test that speak_pipelined stops when audio_player is interrupted."""
    engine = VisionEngine()
    audio_player.stop()  # Pre-interrupt
    result = await engine.speak_pipelined("Sentence one. Sentence two. Sentence three.")
    assert result is False  # Should abort due to barge-in interrupt
    audio_player.reset_interrupt()
