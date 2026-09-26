"""
Hardware Control Tools for VISION AI OS.
Provides native control for Windows audio volume, mute, display brightness, and screen lock.
"""

from typing import Optional
from vision.tools.registry import tool
from vision.logger import logger
from vision.platform import lock_workstation, IS_WINDOWS

try:
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
except Exception:
    # pycaw pulls in comtypes/COM at import; on non-Windows or a broken COM stack
    # it raises OSError/NotImplementedError, not just ImportError.
    AudioUtilities = None
    IAudioEndpointVolume = None
try:
    from comtypes import CLSCTX_ALL
except Exception:
    CLSCTX_ALL = None

try:
    import screen_brightness_control as sbc
except Exception:
    # screen_brightness_control probes OS display APIs at import and can raise
    # non-ImportError errors on unsupported/headless hosts.
    sbc = None


def _get_audio_endpoint():
    """Helper to retrieve active default audio endpoint volume interface."""
    if not AudioUtilities:
        return None
    try:
        speakers = AudioUtilities.GetSpeakers()
        if hasattr(speakers, "EndpointVolume") and speakers.EndpointVolume:
            return speakers.EndpointVolume
        if hasattr(speakers, "Activate") and IAudioEndpointVolume and CLSCTX_ALL:
            interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return interface.QueryInterface(IAudioEndpointVolume)
        if hasattr(speakers, "_dev") and hasattr(speakers._dev, "Activate") and IAudioEndpointVolume and CLSCTX_ALL:
            interface = speakers._dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return interface.QueryInterface(IAudioEndpointVolume)
        return None
    except Exception as e:
        logger.error(f"[HardwareTools] Failed to get audio endpoint: {e}")
        return None


# ---------------- Volume Controls ----------------

@tool(name="set_volume", description="Set the PC master audio volume level (0 to 100).")
def set_volume(level: int) -> str:
    """Set system audio volume percentage (0-100)."""
    endpoint = _get_audio_endpoint()
    if not endpoint:
        return "Error: Audio device interface not available."

    clamped_level = max(0, min(100, int(level)))
    scalar = clamped_level / 100.0
    try:
        endpoint.SetMasterVolumeLevelScalar(scalar, None)
        # Automatically unmute if setting positive volume
        if clamped_level > 0 and endpoint.GetMute():
            endpoint.SetMute(0, None)
    except Exception as e:
        logger.error(f"[HardwareTools] Failed to set volume: {e}")
        return f"Error setting volume: {e}"

    logger.info(f"[HardwareTools] System volume set to {clamped_level}%")
    return f"System volume set to {clamped_level}%."


@tool(name="increase_volume", description="Increase system audio volume by a percentage step (e.g. step=10).")
def increase_volume(step: int = 10) -> str:
    """Increase system volume by step percent."""
    endpoint = _get_audio_endpoint()
    if not endpoint:
        return "Error: Audio device interface not available."

    try:
        curr_scalar = endpoint.GetMasterVolumeLevelScalar()
        curr_pct = round(curr_scalar * 100)
        # Clamp both ends so a negative step can't push the scalar below 0
        # (SetMasterVolumeLevelScalar requires 0.0–1.0).
        new_pct = max(0, min(100, curr_pct + int(step)))
        endpoint.SetMasterVolumeLevelScalar(new_pct / 100.0, None)
        if endpoint.GetMute():
            endpoint.SetMute(0, None)
    except Exception as e:
        logger.error(f"[HardwareTools] Failed to increase volume: {e}")
        return f"Error adjusting volume: {e}"

    logger.info(f"[HardwareTools] Volume increased from {curr_pct}% to {new_pct}%")
    return f"Volume increased to {new_pct}%."


@tool(name="decrease_volume", description="Decrease system audio volume by a percentage step (e.g. step=10).")
def decrease_volume(step: int = 10) -> str:
    """Decrease system volume by step percent."""
    endpoint = _get_audio_endpoint()
    if not endpoint:
        return "Error: Audio device interface not available."

    try:
        curr_scalar = endpoint.GetMasterVolumeLevelScalar()
        curr_pct = round(curr_scalar * 100)
        # Clamp both ends so an out-of-range step stays within 0–100.
        new_pct = max(0, min(100, curr_pct - int(step)))
        endpoint.SetMasterVolumeLevelScalar(new_pct / 100.0, None)
    except Exception as e:
        logger.error(f"[HardwareTools] Failed to decrease volume: {e}")
        return f"Error adjusting volume: {e}"

    logger.info(f"[HardwareTools] Volume decreased from {curr_pct}% to {new_pct}%")
    return f"Volume decreased to {new_pct}%."


@tool(name="mute_volume", description="Mute the system master audio output.")
def mute_volume() -> str:
    """Mute system master audio."""
    endpoint = _get_audio_endpoint()
    if not endpoint:
        return "Error: Audio device interface not available."

    try:
        endpoint.SetMute(1, None)
    except Exception as e:
        logger.error(f"[HardwareTools] Failed to mute: {e}")
        return f"Error muting audio: {e}"
    logger.info("[HardwareTools] Audio output muted.")
    return "System audio muted."


@tool(name="unmute_volume", description="Unmute the system master audio output.")
def unmute_volume() -> str:
    """Unmute system master audio."""
    endpoint = _get_audio_endpoint()
    if not endpoint:
        return "Error: Audio device interface not available."

    try:
        endpoint.SetMute(0, None)
    except Exception as e:
        logger.error(f"[HardwareTools] Failed to unmute: {e}")
        return f"Error unmuting audio: {e}"
    logger.info("[HardwareTools] Audio output unmuted.")
    return "System audio unmuted."


@tool(name="get_volume_status", description="Get current audio volume percentage and mute status.")
def get_volume_status() -> str:
    """Check current volume level and mute status."""
    endpoint = _get_audio_endpoint()
    if not endpoint:
        return "Error: Audio device interface not available."

    try:
        curr_pct = round(endpoint.GetMasterVolumeLevelScalar() * 100)
        is_muted = bool(endpoint.GetMute())
    except Exception as e:
        logger.error(f"[HardwareTools] Failed to read volume status: {e}")
        return f"Error reading volume status: {e}"
    return f"Master Volume: {curr_pct}%, Muted: {'Yes' if is_muted else 'No'}"


# ---------------- Brightness Controls ----------------

@tool(name="set_brightness", description="Set the display screen brightness percentage (0 to 100).")
def set_brightness(level: int) -> str:
    """Set screen brightness percentage (0-100)."""
    if not sbc:
        return "Error: Screen brightness control not available."

    clamped_level = max(0, min(100, int(level)))
    try:
        sbc.set_brightness(clamped_level)
        logger.info(f"[HardwareTools] Screen brightness set to {clamped_level}%")
        return f"Screen brightness set to {clamped_level}%."
    except Exception as e:
        logger.error(f"[HardwareTools] Failed to set brightness: {e}")
        return f"Error setting brightness: {e}"


@tool(name="increase_brightness", description="Increase display screen brightness by a percentage step (e.g. step=10).")
def increase_brightness(step: int = 10) -> str:
    """Increase screen brightness by step percent."""
    if not sbc:
        return "Error: Screen brightness control not available."

    try:
        current = sbc.get_brightness()
        curr_val = current[0] if isinstance(current, list) else int(current)
        new_val = min(100, curr_val + int(step))
        sbc.set_brightness(new_val)
        logger.info(f"[HardwareTools] Brightness increased from {curr_val}% to {new_val}%")
        return f"Screen brightness increased to {new_val}%."
    except Exception as e:
        return f"Error adjusting brightness: {e}"


@tool(name="decrease_brightness", description="Decrease display screen brightness by a percentage step (e.g. step=10).")
def decrease_brightness(step: int = 10) -> str:
    """Decrease screen brightness by step percent."""
    if not sbc:
        return "Error: Screen brightness control not available."

    try:
        current = sbc.get_brightness()
        curr_val = current[0] if isinstance(current, list) else int(current)
        new_val = max(0, curr_val - int(step))
        sbc.set_brightness(new_val)
        logger.info(f"[HardwareTools] Brightness decreased from {curr_val}% to {new_val}%")
        return f"Screen brightness decreased to {new_val}%."
    except Exception as e:
        return f"Error adjusting brightness: {e}"


@tool(name="get_brightness_status", description="Get the current display screen brightness level.")
def get_brightness_status() -> str:
    """Check current brightness percentage."""
    if not sbc:
        return "Error: Screen brightness control not available."

    try:
        current = sbc.get_brightness()
        curr_val = current[0] if isinstance(current, list) else int(current)
        return f"Display Brightness: {curr_val}%"
    except Exception as e:
        return f"Error reading brightness: {e}"


# ---------------- System Security Controls ----------------

@tool(name="lock_screen", description="Immediately lock the computer workstation / screen.")
def lock_screen() -> str:
    """Lock the current workstation."""
    logger.info("[HardwareTools] Locking workstation...")
    return lock_workstation()


# ---------------- Battery & Hardware Health Monitors ----------------

@tool(name="get_battery_status", description="Get the PC / laptop battery charge percentage, charging status, and remaining runtime.")
def get_battery_status() -> str:
    """Check battery level, AC power plugged status, and estimated battery runtime."""
    try:
        import psutil
        battery = psutil.sensors_battery()
        if not battery:
            return "Battery Status: Desktop PC (No battery detected / Running on continuous AC power)."

        pct = battery.percent
        plugged = battery.power_plugged
        secs_left = battery.secsleft

        status_text = "Charging / Plugged in (AC)" if plugged else "Discharging on Battery"
        
        time_info = ""
        if not plugged and secs_left > 0 and secs_left != psutil.POWER_TIME_UNLIMITED:
            hours = secs_left // 3600
            mins = (secs_left % 3600) // 60
            time_info = f" (~{hours}h {mins}m remaining)"
        elif plugged and pct == 100:
            time_info = " (Fully Charged)"

        # Health tip
        tip = ""
        if pct <= 20 and not plugged:
            tip = "\n⚠️ Low Battery Alert! Please connect your charger."

        summary = (
            f"Battery Health & Status:\n"
            f"• Level: {pct}%\n"
            f"• Power State: {status_text}{time_info}"
            f"{tip}"
        )
        logger.info(f"[HardwareTools] Battery status: {pct}%, plugged={plugged}")
        return summary
    except Exception as e:
        logger.error(f"[HardwareTools] Failed to get battery status: {e}")
        return f"Error reading battery status: {e}"


@tool(name="get_hardware_health", description="Get comprehensive hardware health: CPU load per core, RAM utilization, drive space, and top active processes.")
def get_hardware_health() -> str:
    """
    Returns real-time hardware telemetry:
    - Overall CPU % and per-core utilization
    - RAM total, used, free, and percentage
    - Storage partitions (C: and D: drive)
    - Top resource-consuming processes
    """
    try:
        import psutil
        lines = ["Hardware & System Health Telemetry:"]

        # 1. CPU
        cpu_overall = psutil.cpu_percent(interval=0.2)
        cores = psutil.cpu_percent(interval=0.1, percpu=True)
        # cpu_freq() can raise (not only return None) on some Linux/VM hosts
        # where the kernel frequency files are missing — guard it so a POSIX
        # quirk can't sink the entire telemetry report.
        try:
            cpu_freq = psutil.cpu_freq()
        except Exception:
            cpu_freq = None
        freq_val = getattr(cpu_freq, "current", None) if cpu_freq else None
        freq_str = f" @ {round(freq_val / 1000, 2)} GHz" if freq_val else ""
        lines.append(f"• CPU Utilization: {cpu_overall}% ({len(cores)} logical cores{freq_str})")

        # 2. RAM
        vmem = psutil.virtual_memory()
        ram_total_gb = round(vmem.total / (1024**3), 1)
        ram_used_gb = round(vmem.used / (1024**3), 1)
        ram_free_gb = round(vmem.available / (1024**3), 1)
        lines.append(f"• RAM Usage: {vmem.percent}% ({ram_used_gb} GB used / {ram_total_gb} GB total, {ram_free_gb} GB free)")

        # 3. Storage Disks (platform-independent mount points)
        if IS_WINDOWS:
            disk_roots = ["C:\\", "D:\\"]
        else:
            disk_roots = ["/"]
        disk_lines = []
        for drive in disk_roots:
            try:
                du = psutil.disk_usage(drive)
                d_total_gb = round(du.total / (1024**3), 1)
                d_free_gb = round(du.free / (1024**3), 1)
                label = drive if IS_WINDOWS else "root (/)"
                disk_lines.append(f"{label}: {du.percent}% ({d_free_gb} GB free / {d_total_gb} GB)")
            except Exception:
                pass
        if disk_lines:
            lines.append(f"• Storage: {', '.join(disk_lines)}")

        # 4. Battery — sensors_battery() is absent on many hosts and can raise
        # (not just return None); guard so it can't abort the whole report.
        try:
            bat = psutil.sensors_battery()
        except Exception:
            bat = None
        if bat:
            p_state = "Plugged In" if bat.power_plugged else "Battery"
            lines.append(f"• Battery: {bat.percent}% ({p_state})")

        # 5. Top 3 Processes by Memory
        try:
            procs = []
            for p in psutil.process_iter(['name', 'cpu_percent', 'memory_info']):
                try:
                    mem_mb = round(p.info['memory_info'].rss / (1024 * 1024), 1)
                    procs.append((p.info['name'], p.info['cpu_percent'], mem_mb))
                except Exception:
                    pass
            procs.sort(key=lambda x: x[2], reverse=True)
            top_procs = [f"{p[0]} ({p[2]} MB)" for p in procs[:3]]
            lines.append(f"• Top Memory Apps: {', '.join(top_procs)}")
        except Exception:
            pass

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[HardwareTools] Failed to get hardware telemetry: {e}")
        return f"Error reading hardware health: {e}"
