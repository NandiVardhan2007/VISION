"""
Test suite for Media and YouTube Playback Automation Tools.
"""

from unittest.mock import patch, MagicMock
from vision.tools.registry import tool_registry
from vision.tools.media_tools import (
    play_youtube_video,
    play_media,
    control_youtube_playback,
    set_youtube_fullscreen,
    seek_youtube_video,
    _get_comet_browser_path
)


def test_media_tools_registered():
    """Verify all YouTube and media tools are registered in tool_registry."""
    tools = [
        "play_youtube_video",
        "play_media",
        "control_youtube_playback",
        "set_youtube_fullscreen",
        "seek_youtube_video"
    ]
    for t in tools:
        assert t in tool_registry._tools, f"Tool '{t}' was not found in tool_registry"


@patch("vision.tools.media_tools._extract_top_youtube_video_id", return_value=None)
@patch("vision.tools.media_tools.webbrowser.open")
@patch("vision.tools.media_tools._get_comet_browser_path")
def test_play_youtube_video_comet(mock_get_path, mock_web_open, mock_extract):
    """Test searching and launching YouTube in Comet browser (search-results URL)."""
    mock_get_path.return_value = r"C:\Program Files\Perplexity\Comet\Application\comet.exe"

    with patch("subprocess.Popen") as mock_popen:
        res = play_youtube_video("latest song from the vishwanath and sons")
        assert "vishwanath and sons" in res
        assert "Comet Browser" in res
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "comet.exe" in args[0].lower()
        # No top-video resolution -> falls back to the search results page
        assert "youtube.com/results" in args[1].lower()
        assert "vishwanath%20and%20sons" in args[1].lower()


@patch("vision.tools.media_tools.pyautogui")
def test_control_youtube_playback(mock_pyautogui):
    """Test hotkey control for full-screen, forward (10s, 30s), rewind, and pause."""
    # 1. Full Screen
    res_fs = control_youtube_playback(action="fullscreen")
    assert "full screen" in res_fs
    mock_pyautogui.press.assert_called_with("f")

    # 2. Forward 10s
    mock_pyautogui.reset_mock()
    res_f10 = control_youtube_playback(action="forward", seconds=10)
    assert "10 seconds" in res_f10
    assert mock_pyautogui.press.call_count == 1
    mock_pyautogui.press.assert_called_with("l")

    # 3. Forward 30s (3 presses of 'l')
    mock_pyautogui.reset_mock()
    res_f30 = control_youtube_playback(action="forward", seconds=30)
    assert "30 seconds" in res_f30
    assert mock_pyautogui.press.call_count == 3

    # 4. Rewind 30s (3 presses of 'j')
    mock_pyautogui.reset_mock()
    res_r30 = control_youtube_playback(action="rewind", seconds=30)
    assert "30 seconds" in res_r30
    assert mock_pyautogui.press.call_count == 3

    # 5. Play / Pause
    mock_pyautogui.reset_mock()
    res_pause = control_youtube_playback(action="pause")
    assert "play/pause" in res_pause
    mock_pyautogui.press.assert_called_with("k")


@patch("vision.tools.media_tools.control_youtube_playback")
def test_seek_and_fullscreen_shortcuts(mock_control):
    mock_control.return_value = "Success"
    set_youtube_fullscreen()
    mock_control.assert_called_with(action="fullscreen")

    seek_youtube_video(direction="forward", seconds=30)
    mock_control.assert_called_with(action="forward", seconds=30)
