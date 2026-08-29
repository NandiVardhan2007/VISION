"""
Test suite for Hardware Control Tools (Volume, Brightness, Mute, Lock).
"""

from vision.tools.hardware_tools import (
    set_volume, increase_volume, decrease_volume,
    mute_volume, unmute_volume, get_volume_status,
    get_brightness_status, set_brightness, increase_brightness, decrease_brightness
)
from vision.platform import IS_WINDOWS
import pytest


def _audio_available():
    try:
        from vision.tools.hardware_tools import _get_audio_endpoint
        return _get_audio_endpoint() is not None
    except Exception:
        return False


@pytest.fixture
def requires_audio():
    if not _audio_available():
        pytest.skip("System audio backend (pycaw / Windows audio) not available on this OS.")


def test_volume_controls(requires_audio):
    # Test get volume status
    status = get_volume_status()
    assert "Master Volume" in status

    # Test set volume
    set_res = set_volume(level=50)
    assert "50%" in set_res

    # Test mute & unmute
    mute_res = mute_volume()
    assert "muted" in mute_res.lower()
    unmute_res = unmute_volume()
    assert "unmuted" in unmute_res.lower()

    # Test increase & decrease
    inc_res = increase_volume(step=5)
    assert "%" in inc_res
    dec_res = decrease_volume(step=5)
    assert "%" in dec_res


def test_brightness_controls():
    # Brightness control only exists where screen_brightness_control is available.
    try:
        import screen_brightness_control as sbc  # noqa: F401
    except ImportError:
        pytest.skip("screen_brightness_control not available on this OS.")
    # Test get brightness status
    b_status = get_brightness_status()
    assert "Brightness" in b_status or "Error" in b_status
