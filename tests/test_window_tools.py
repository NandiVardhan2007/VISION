"""
Test suite for Window & Desktop Productivity Tools.
"""

from vision.tools.window_tools import (
    show_desktop, minimize_all_windows, restore_windows,
    maximize_window, snap_window, list_running_applications,
    close_application
)
from vision.tools.registry import tool_registry
import pytest

try:
    import pyautogui  # noqa: F401
    _AUTOGUI_AVAILABLE = True
except ImportError:
    _AUTOGUI_AVAILABLE = False


def test_window_tools_registered():
    registered = tool_registry._tools
    assert "show_desktop" in registered
    assert "minimize_all_windows" in registered
    assert "restore_windows" in registered
    assert "maximize_window" in registered
    assert "snap_window" in registered
    assert "close_application" in registered
    assert "list_running_applications" in registered


def test_window_tool_actions():
    if not _AUTOGUI_AVAILABLE:
        pytest.skip("pyautogui not available on this OS.")
    snap_res = snap_window("left")
    assert "left" in snap_res.lower()

    snap_invalid = snap_window("diagonal")
    assert "Unsupported" in snap_invalid

    app_res = list_running_applications()
    assert isinstance(app_res, str)

    close_res = close_application("non_existent_fake_app_xyz")
    assert "No active process" in close_res or "Sent close" in close_res
