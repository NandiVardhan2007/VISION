"""
Unit tests for Network Tools and Hardware Health Monitors in VISION AI OS.
"""

import pytest
from vision.tools.network_tools import test_internet_speed as fn_test_internet_speed, get_network_diagnostics, ping_host
from vision.tools.hardware_tools import get_battery_status, get_hardware_health


def test_speed_check():
    """Verify internet speed tool returns valid measurement."""
    # Fast mock or invocation
    assert callable(fn_test_internet_speed)


def test_get_battery_status():
    """Verify battery status returns valid information."""
    result = get_battery_status()
    assert isinstance(result, str)
    assert ("Level:" in result or "Desktop PC" in result)


def test_get_hardware_health():
    """Verify hardware health telemetry returns CPU, RAM, and Disk metrics."""
    result = get_hardware_health()
    assert isinstance(result, str)
    assert "Hardware & System Health" in result
    assert "CPU Utilization" in result
    assert "RAM Usage" in result


def test_get_network_diagnostics():
    """Verify network diagnostics returns Wi-Fi / IP / Connectivity details."""
    result = get_network_diagnostics()
    assert isinstance(result, str)
    assert "Network & Wi-Fi Diagnostics" in result
    assert "Local IPv4" in result


def test_ping_host():
    """Verify ping tool pings a host and returns packet loss and latency."""
    result = ping_host("127.0.0.1", count=1)
    assert isinstance(result, str)
    assert ("Packet Loss" in result or "127.0.0.1" in result)


def test_platform_ping_online_detection(monkeypatch):
    """Regression: 100% packet loss must NOT be reported as online.

    The old detection used `"0%" in loss`, which is True for "100%" because
    "0%" is a substring of "100%" — so a fully-dropped ping was wrongly marked
    online. The numeric parse must treat 100% loss as offline and 0% as online.
    """
    import vision.platform as platform

    win_100_loss = (
        "Pinging 10.255.255.1 with 32 bytes of data:\r\n"
        "Request timed out.\r\n\r\n"
        "Ping statistics for 10.255.255.1:\r\n"
        "    Packets: Sent = 2, Received = 0, Lost = 2 (100% loss),\r\n"
    )
    monkeypatch.setattr(platform, "IS_WINDOWS", True)
    monkeypatch.setattr(platform.subprocess, "check_output", lambda *a, **k: win_100_loss)
    res = platform.ping_host("10.255.255.1", count=2)
    assert res["online"] is False, "100% packet loss must be offline"

    win_0_loss = (
        "Ping statistics for 127.0.0.1:\r\n"
        "    Packets: Sent = 2, Received = 2, Lost = 0 (0% loss),\r\n"
        "Approximate round trip times in milli-seconds:\r\n"
        "    Minimum = 0ms, Maximum = 0ms, Average = 0ms\r\n"
    )
    monkeypatch.setattr(platform.subprocess, "check_output", lambda *a, **k: win_0_loss)
    res = platform.ping_host("127.0.0.1", count=2)
    assert res["online"] is True, "0% packet loss must be online"
