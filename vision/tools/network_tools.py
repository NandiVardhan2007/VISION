"""
Network, Wi-Fi & Internet Health Tools for VISION AI OS.
Provides Ookla Speedtest integration, Wi-Fi signal diagnostics, and network latency probes.
"""

import json
import socket
import subprocess
import shutil
from typing import Optional
from vision.tools.registry import tool
from vision.logger import logger
from vision.platform import ping_host as ping_host_platform, get_wifi_diagnostics, IS_WINDOWS


@tool(name="test_internet_speed", description="Test live internet download/upload speed, ping latency, and ISP information using Ookla Speedtest.")
def test_internet_speed() -> str:
    """
    Runs Ookla Speedtest CLI and returns accurate download/upload speeds (in Mbps),
    ping latency (in ms), jitter, packet loss, and ISP/Server details.
    """
    speedtest_bin = shutil.which("speedtest")
    if not speedtest_bin and IS_WINDOWS:
        # Windows-only install locations; shutil.which validates the full path.
        for path in ["C:\\Windows\\speedtest.exe", "C:\\Program Files\\speedtest\\speedtest.exe"]:
            if shutil.which(path):
                speedtest_bin = path
                break

    if not speedtest_bin:
        return "Error: Ookla Speedtest CLI ('speedtest') is not installed or not in PATH."

    logger.info("[NetworkTool] Running Ookla Speedtest...")
    try:
        cmd = [speedtest_bin, "-f", "json", "--accept-license", "--accept-gdpr"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=45, errors="ignore")
        
        if result.returncode != 0 and not result.stdout:
            logger.error(f"[NetworkTool] Speedtest failed: {result.stderr}")
            return f"Error executing speedtest: {result.stderr.strip()}"

        data = json.loads(result.stdout.strip())

        # Extract metrics
        # Coalesce None→{} so an explicit null for a normally-present object
        # (partial Ookla run) doesn't raise AttributeError and lose all metrics,
        # and coalesce the inner scalars (which can be present-but-null) so
        # round()/arithmetic never sees None.
        ping_ms = round((data.get("ping") or {}).get("latency") or 0, 2)
        jitter_ms = round((data.get("ping") or {}).get("jitter") or 0, 2)

        # Bytes/sec -> Mbps (bytes * 8 / 1,000,000)
        down_bytes_sec = (data.get("download") or {}).get("bandwidth") or 0
        up_bytes_sec = (data.get("upload") or {}).get("bandwidth") or 0

        download_mbps = round((down_bytes_sec * 8) / 1_000_000, 2)
        upload_mbps = round((up_bytes_sec * 8) / 1_000_000, 2)

        isp = data.get("isp") or "Unknown ISP"
        server_info = data.get("server") or {}
        server_name = server_info.get("name") or "Unknown Server"
        server_loc = server_info.get("location") or ""
        server_country = server_info.get("country") or ""
        packet_loss = data.get("packetLoss") or 0
        client_ip = (data.get("interface") or {}).get("externalIp") or ""
        result_url = (data.get("result") or {}).get("url") or ""

        summary = (
            f"Internet Speed Test Results:\n"
            f"• Download: {download_mbps} Mbps\n"
            f"• Upload: {upload_mbps} Mbps\n"
            f"• Ping: {ping_ms} ms (Jitter: {jitter_ms} ms)\n"
            f"• Packet Loss: {packet_loss}%\n"
            f"• ISP: {isp}\n"
            f"• Server: {server_name} ({server_loc}, {server_country})\n"
            f"• Public IP: {client_ip}\n"
            f"• Result URL: {result_url}"
        )
        logger.info(f"[NetworkTool] Speedtest complete: Down {download_mbps} Mbps, Up {upload_mbps} Mbps, Ping {ping_ms} ms")
        return summary
    except subprocess.TimeoutExpired:
        return "Speedtest timed out after 45 seconds."
    except Exception as e:
        logger.error(f"[NetworkTool] Speedtest error: {e}")
        return f"Error running internet speed test: {e}"


@tool(name="get_network_diagnostics", description="Get Wi-Fi signal strength, connected SSID, local IPv4, gateway, and internet connectivity status.")
def get_network_diagnostics() -> str:
    """
    Checks the active Wi-Fi adapter connection quality (SSID, signal percentage, radio type, receive/transmit rates),
    local IP, default gateway, and DNS ping status.
    """
    lines = ["Network & Wi-Fi Diagnostics:"]

    # 1. Wi-Fi interface details (platform-aware)
    try:
        wifi_lines = get_wifi_diagnostics()
        if wifi_lines:
            lines.extend(wifi_lines)
    except Exception as e:
        logger.debug(f"[NetworkTool] wifi diagnostics: {e}")

    # 2. Local IP & Hostname — only if the platform wifi block didn't already
    #    add them (get_wifi_diagnostics appends these on POSIX), to avoid dupes.
    if not any("Hostname:" in ln for ln in lines):
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            lines.append(f"• Hostname: {hostname}")
            lines.append(f"• Local IPv4: {local_ip}")
        except Exception as e:
            logger.debug(f"[NetworkTool] Local IP check: {e}")

    # 3. Connectivity ping to public DNS
    try:
        res = ping_host_platform("8.8.8.8", count=2)
        if res.get("online"):
            avg = res.get("avg", "")
            if avg and avg != "Unknown":
                lines.append(f"• Internet Connectivity: Online (DNS Latency: {avg})")
            else:
                lines.append("• Internet Connectivity: Online")
        else:
            lines.append("• Internet Connectivity: Offline or Ping unreachable")
    except Exception:
        lines.append("• Internet Connectivity: Offline or Ping unreachable")

    return "\n".join(lines)


@tool(name="ping_host", description="Ping a target hostname or IP address (e.g. 'google.com', '8.8.8.8') to verify reachability and latency.")
def ping_host(host: str = "google.com", count: int = 4) -> str:
    """Pings a target host and returns packet loss and average latency."""
    clean_host = host.strip().replace("http://", "").replace("https://", "").split("/")[0]
    try:
        res = ping_host_platform(clean_host, count=count)
        loss = res.get("loss", "0%")
        avg = res.get("avg", "Unknown")
        return f"Ping results for '{clean_host}':\n• Packet Loss: {loss}\n• Average Latency: {avg}"
    except Exception as e:
        return f"Failed to ping '{clean_host}': {e}"
