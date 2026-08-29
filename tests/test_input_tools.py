"""
Test suite for Desktop Input and Typing Automation Tools.
"""

from vision.tools.input_tools import type_text_into_application, press_keyboard_shortcut
from vision.tools.registry import tool_registry
import pytest

try:
    import pyautogui  # noqa: F401
    _AUTOGUI_AVAILABLE = True
except ImportError:
    _AUTOGUI_AVAILABLE = False


def test_input_tools_registered():
    assert "type_text_into_application" in tool_registry._tools
    assert "press_keyboard_shortcut" in tool_registry._tools


def test_input_tool_validation():
    res = type_text_into_application("", target_app=None)
    assert "Error" in res

    if not _AUTOGUI_AVAILABLE:
        pytest.skip("pyautogui not available on this OS.")
    short_res = press_keyboard_shortcut("ctrl+c")
    assert "Pressed" in short_res or "Failed" in short_res
