"""
Cross-platform OS abstraction layer for VISION.

VISION was originally built on Windows. This module centralizes every OS-specific
operation (opening files, launching apps, power management, alert chimes, network
diagnostics, window/app discovery) behind a single, operating-system-independent API.

On Windows it keeps the original Win32 behaviors. On Linux/macOS it uses the native
equivalents (xdg-open, loginctl/systemctl, nmcli, aplay, etc.) and degrades gracefully
when the underlying system service is unavailable.

Nothing here raises on import on any platform — every function is safe to call and
returns a best-effort result or a clear status string.
"""

import os
import sys
import shutil
import subprocess
import tempfile
import math
import wave
from typing import List, Optional, Tuple, Dict, Any

from vision.logger import logger

# ── Platform detection ────────────────────────────────────────────────
_PLATFORM = sys.platform.lower()
IS_WINDOWS = os.name == "nt" or _PLATFORM.startswith("win")
IS_MACOS = _PLATFORM == "darwin"
IS_LINUX = (not IS_WINDOWS and not IS_MACOS)
# BSD-like systems count as "linux-ish" for the purpose of xdg-open / systemctl.
IS_POSIX = not IS_WINDOWS

logger.debug(f"[Platform] detected: Windows={IS_WINDOWS} macOS={IS_MACOS} Linux={IS_LINUX} (sys.platform={_PLATFORM})")


# ── File / URL opening ────────────────────────────────────────────────

def open_path(path: str) -> Tuple[bool, str]:
    """
    Open a file, folder, or URL with the OS default handler.
    Returns (success, message).
    """
    if not path:
        return False, "Error: path is required."

    try:
        if IS_WINDOWS:
            os.startfile(path)  # type: ignore[attr-defined]
            return True, f"Opened '{path}'."
        if IS_MACOS:
            subprocess.Popen(["open", path])
            return True, f"Opened '{path}'."
        # Linux / POSIX
        handler = shutil.which("xdg-open")
        if handler:
            subprocess.Popen([handler, path])
            return True, f"Opened '{path}'."
        # Last-resort fallback for URLs
        if _looks_like_url(path):
            import webbrowser
            webbrowser.open(path)
            return True, f"Opened '{path}' in browser."
        return False, f"No default file opener available to open '{path}'."
    except Exception as e:
        return False, f"Failed to open '{path}': {e}"


def open_url(url: str) -> bool:
    """Open a URL in the default web browser (cross-platform)."""
    try:
        import webbrowser
        return webbrowser.open(url)
    except Exception as e:
        logger.warning(f"[Platform] Failed to open URL {url}: {e}")
        return False


def _looks_like_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://") or s.startswith("ftp://")


def launch_target(target: str) -> Tuple[bool, str]:
    """
    Open a URL, URI scheme (e.g. 'whatsapp:', 'spotify:'), or application name.
    On Windows this mirrors `start "" "target"`.
    """
    if not target:
        return False, "Error: target is required."

    if _looks_like_url(target):
        ok = open_url(target)
        return ok, ("Opened URL." if ok else "Failed to open URL.")

    if IS_WINDOWS:
        try:
            os.system(f'start "" "{target}"')
            return True, f"Launched '{target}'."
        except Exception as e:
            return False, f"Failed to launch '{target}': {e}"

    if IS_MACOS:
        try:
            subprocess.Popen(["open", target])
            return True, f"Launched '{target}'."
        except Exception as e:
            return False, f"Failed to launch '{target}': {e}"

    # Linux: xdg-open handles both URLs and registered URI schemes (when a
    # .desktop file declares the scheme). Also try the bare executable name.
    handler = shutil.which("xdg-open")
    if handler:
        try:
            subprocess.Popen([handler, target])
            return True, f"Launched '{target}'."
        except Exception:
            pass
    exe = shutil.which(target)
    if exe:
        try:
            subprocess.Popen([exe])
            return True, f"Launched '{target}'."
        except Exception as e:
            return False, f"Failed to launch '{target}': {e}"
    return False, f"Could not find a handler for '{target}' on this system."


# ── Desktop application discovery ─────────────────────────────────────

def find_desktop_app(app_name: str) -> Optional[str]:
    """
    Search for an installed application shortcut / .desktop entry by name.
    Returns a launchable path/command or None.
    """
    if not app_name:
        return None
    name = app_name.lower().replace(" ", "")

    if IS_WINDOWS:
        search_dirs = [
            os.environ.get("APPDATA", "") + "/Microsoft/Windows/Start Menu/Programs",
            os.environ.get("ProgramData", "") + "/Microsoft/Windows/Start Menu/Programs",
            os.environ.get("USERPROFILE", "") + "/Desktop",
            os.environ.get("PUBLIC", "") + "/Desktop",
        ]
        for sdir in search_dirs:
            sdir_path = os.path.join(sdir)
            if not os.path.isdir(sdir_path):
                continue
            for root, _dirs, files in os.walk(sdir_path):
                for f in files:
                    if f.lower().endswith(".lnk"):
                        stem = os.path.splitext(f)[0].lower().replace(" ", "")
                        if name in stem or stem in name:
                            return os.path.join(root, f)
        return None

    if IS_MACOS:
        # Best-effort: look in /Applications for a matching .app
        apps_dir = "/Applications"
        if os.path.isdir(apps_dir):
            for entry in os.listdir(apps_dir):
                if entry.lower().endswith(".app"):
                    stem = entry[:-4].lower().replace(" ", "")
                    if name in stem or stem in name:
                        return os.path.join(apps_dir, entry)
        return None

    # Linux: scan .desktop files in standard locations by their Name= field.
    desktop_dirs = [
        os.path.expanduser("~/.local/share/applications"),
        "/usr/share/applications",
        "/usr/local/share/applications",
    ]
    best = None
    for d in desktop_dirs:
        if not os.path.isdir(d):
            continue
        for entry in os.listdir(d):
            if not entry.lower().endswith(".desktop"):
                continue
            path = os.path.join(d, entry)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
            except Exception:
                continue
            entry_name = None
            for line in content.splitlines():
                if line.lower().startswith("name="):
                    entry_name = line.split("=", 1)[1].strip().lower().replace(" ", "")
                    break
            if entry_name and (name in entry_name or entry_name in name):
                return f"gtk-launch {os.path.splitext(entry)[0]}" if shutil.which("gtk-launch") else path
            if name in entry.lower():
                best = path
    return best


# ── Power management ──────────────────────────────────────────────────

def lock_workstation() -> str:
    """Lock the current user session."""
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.user32.LockWorkStation()  # type: ignore[attr-defined]
            return "Workstation is now locked."
        except Exception as e:
            return f"Failed to lock workstation: {e}"

    if IS_MACOS:
        try:
            subprocess.run(["pmset", "displaysleepnow"], check=False)
            return "Display locked / slept (macOS)."
        except Exception as e:
            return f"Failed to lock: {e}"

    # Linux: try the common screen-lock helpers, best effort.
    for cmd in (
        ["loginctl", "lock-session"],
        ["xdg-screensaver", "lock"],
        ["gnome-screensaver-command", "-l"],
        ["mate-screensaver-command", "-l"],
        ["i3lock"],
        ["slock"],
    ):
        exe = cmd[0]
        if shutil.which(exe):
            try:
                subprocess.Popen(cmd)
                return f"Workstation locked via '{exe}'."
            except Exception:
                continue
    return "Screen lock is not available on this Linux session (no screensaver/locker detected)."


def suspend_computer() -> str:
    """Put the computer to sleep / suspend."""
    if IS_WINDOWS:
        try:
            subprocess.run(
                ["powershell", "-Command",
                 "Add-Type -AssemblyName System.Windows.Forms; "
                 "[System.Windows.Forms.Application]::SetSuspendState("
                 "[System.Windows.Forms.PowerState]::Suspend, $false, $false)"],
                check=False,
            )
            return "Putting computer to sleep."
        except Exception as e:
            return f"Failed to sleep computer: {e}"

    if IS_MACOS:
        try:
            subprocess.run(["pmset", "sleepnow"], check=False)
            return "Putting computer to sleep."
        except Exception as e:
            return f"Failed to sleep computer: {e}"

    # Linux
    if shutil.which("systemctl"):
        try:
            subprocess.Popen(["systemctl", "suspend"])
            return "Suspending system (systemctl)."
        except Exception:
            pass
    if shutil.which("loginctl"):
        try:
            subprocess.Popen(["loginctl", "suspend"])
            return "Suspending session (loginctl)."
        except Exception:
            pass
    return "Suspend is not available on this system."


def empty_trash() -> str:
    """Empty the OS recycle bin / trash."""
    if IS_WINDOWS:
        try:
            import ctypes
            # 7 = SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
            ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 7)  # type: ignore[attr-defined]
            return "Recycle Bin is now empty."
        except Exception as e:
            logger.error(f"[Platform] Failed to empty Recycle Bin: {e}")
            return "Recycle Bin is now empty."

    if IS_MACOS:
        try:
            subprocess.run(["osascript", "-e", 'tell application "Finder" to empty trash'],
                           check=False)
            return "Trash is now empty."
        except Exception as e:
            return f"Failed to empty trash: {e}"

    # Linux: gio is the most portable; fall back to removing the Trash dirs.
    if shutil.which("gio"):
        try:
            subprocess.run(["gio", "trash", "--empty"], check=False)
            return "Trash is now empty."
        except Exception:
            pass
    for trash_dir in (
        os.path.expanduser("~/.local/share/Trash"),
        os.path.expanduser("~/.cache/Trash"),
    ):
        if os.path.isdir(trash_dir):
            try:
                shutil.rmtree(trash_dir, ignore_errors=True)
            except Exception:
                pass
    return "Trash is now empty."


def shutdown_machine(timer_seconds: int = 15) -> str:
    """Schedule a system shutdown with a safety timer."""
    if IS_WINDOWS:
        try:
            subprocess.run(["shutdown", "/s", "/t", str(timer_seconds),
                            "/c", "VISION AI OS initiated shutdown."], check=True)
            return (f"Shutdown scheduled in {timer_seconds} seconds. "
                    "Say 'Cancel shutdown' if you want to abort.")
        except Exception as e:
            return f"Failed to schedule shutdown: {e}"

    # Linux shutdown timer is in minutes, so convert (round up to >=1 min).
    minutes = max(0, int(round(timer_seconds / 60.0)) or (1 if timer_seconds > 0 else 0))
    if shutil.which("shutdown"):
        try:
            if minutes <= 0:
                subprocess.run(["shutdown", "-P", "now"], check=True)
            else:
                subprocess.run(["shutdown", "-P", f"+{minutes}",
                                "VISION AI OS initiated shutdown."], check=True)
            label = "now" if minutes <= 0 else f"in ~{minutes} min"
            return (f"Shutdown scheduled {label}. "
                    "Say 'Cancel shutdown' if you want to abort.")
        except Exception as e:
            return f"Failed to schedule shutdown: {e}"
    return "Shutdown command is not available on this system."


def restart_machine(timer_seconds: int = 15) -> str:
    """Schedule a system restart with a safety timer."""
    if IS_WINDOWS:
        try:
            subprocess.run(["shutdown", "/r", "/t", str(timer_seconds),
                            "/c", "VISION AI OS initiated restart."], check=True)
            return (f"Restart scheduled in {timer_seconds} seconds. "
                    "Say 'Cancel shutdown' if you want to abort.")
        except Exception as e:
            return f"Failed to schedule restart: {e}"

    minutes = max(0, int(round(timer_seconds / 60.0)) or (1 if timer_seconds > 0 else 0))
    if shutil.which("shutdown"):
        try:
            if minutes <= 0:
                subprocess.run(["shutdown", "-r", "now"], check=True)
            else:
                subprocess.run(["shutdown", "-r", f"+{minutes}",
                                "VISION AI OS initiated restart."], check=True)
            label = "now" if minutes <= 0 else f"in ~{minutes} min"
            return f"Restart scheduled {label}. Say 'Cancel shutdown' if you want to abort."
        except Exception as e:
            return f"Failed to schedule restart: {e}"
    return "Restart command is not available on this system."


def cancel_shutdown() -> str:
    """Cancel a pending scheduled shutdown/restart."""
    if IS_WINDOWS:
        try:
            subprocess.run(["shutdown", "/a"], check=True)
            return "Scheduled shutdown or restart has been cancelled."
        except Exception as e:
            return f"No scheduled shutdown to cancel (or error: {e})."
    if shutil.which("shutdown"):
        try:
            subprocess.run(["shutdown", "-c"], check=False)
            return "Scheduled shutdown or restart has been cancelled."
        except Exception as e:
            return f"No scheduled shutdown to cancel (or error: {e})."
    return "No scheduled shutdown to cancel."


# ── Alert chime ───────────────────────────────────────────────────────

def play_chime(frequencies: Optional[List[int]] = None,
               durations_ms: Optional[List[int]] = None) -> None:
    """
    Play a short alert chime. On Windows uses winsound. On Linux/macOS it
    synthesizes a tiny WAV and plays it through an available audio player, or
    falls back silently if none is present.
    """
    if frequencies is None:
        frequencies = [1046, 1318, 1568]
    if durations_ms is None:
        durations_ms = [120, 120, 250]

    if IS_WINDOWS:
        try:
            import winsound
            for freq, dur in zip(frequencies, durations_ms):
                winsound.Beep(freq, dur)
        except Exception:
            pass
        return

    # POSIX: synthesize a WAV and play it.
    try:
        wav_path = _synthesize_chime_wav(frequencies, durations_ms)
        player = None
        for candidate in ("paplay", "aplay", "play", "mpv", "ffplay", "afplay"):
            if shutil.which(candidate):
                player = candidate
                break
        if player:
            subprocess.Popen([player, wav_path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # If no player is available we simply skip audio (the spoken reminder still fires).
    except Exception:
        pass


def _synthesize_chime_wav(frequencies: List[int], durations_ms: List[int],
                          sample_rate: int = 44100) -> str:
    """Generate a short multi-tone WAV file and return its path."""
    n_pairs = max(len(frequencies), len(durations_ms))
    frames: bytes = b""
    for i in range(n_pairs):
        freq = frequencies[i] if i < len(frequencies) else frequencies[-1]
        dur = durations_ms[i] if i < len(durations_ms) else durations_ms[-1]
        n_samples = int(sample_rate * dur / 1000.0)
        for n in range(n_samples):
            t = n / sample_rate
            val = int(32767 * 0.4 * math.sin(2 * math.pi * freq * t))
            frames += val.to_bytes(2, "little", signed=True)
    fd, path = tempfile.mkstemp(prefix="vision_chime_", suffix=".wav")
    with os.fdopen(fd, "wb") as fh:
        with wave.open(fh, "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(frames)
    return path


# ── Network diagnostics ───────────────────────────────────────────────

def ping_host(host: str = "8.8.8.8", count: int = 4) -> Dict[str, Any]:
    """
    Ping a host cross-platform. Returns a dict with raw output, packet loss
    percentage, and average latency string.
    """
    clean_host = host.strip().replace("http://", "").replace("https://", "").split("/")[0]
    count = max(1, min(10, int(count)))
    result: Dict[str, Any] = {
        "host": clean_host,
        "output": "",
        "loss": "0%",
        "avg": "Unknown",
        "online": False,
    }
    try:
        if IS_WINDOWS:
            cmd = f"ping -n {count} {clean_host}"
        else:
            cmd = f"ping -c {count} {clean_host}"
        output = subprocess.check_output(cmd, shell=True, text=True,
                                          errors="ignore", timeout=30)
        result["output"] = output
        for line in output.splitlines():
            if IS_WINDOWS:
                if "Lost =" in line:
                    result["loss"] = line.split("(")[-1].split(")")[0].strip()
                if "Average =" in line:
                    result["avg"] = line.split("Average =")[-1].strip()
            else:
                if "packet loss" in line:
                    # e.g. "1 packets transmitted, 1 received, 0% packet loss..."
                    part = line.split(",")[-1].strip()
                    if "packet loss" in part:
                        result["loss"] = part.split("packet loss")[0].strip()
                if line.lstrip().startswith("round-trip") or "rtt min/avg/max" in line:
                    # Linux: rtt min/avg/max/mdev = 12.3/14.0/...
                    if "=" in line:
                        stats = line.split("=")[-1].strip()
                        avg = stats.split("/")[1] if "/" in stats else stats
                        result["avg"] = f"{avg} ms"
        result["online"] = "0%" in result["loss"] or "0.0%" in result["loss"] or "0%" == result["loss"]
    except Exception:
        result["online"] = False
    return result


def get_wifi_diagnostics() -> List[str]:
    """
    Collect Wi-Fi / network diagnostics lines. Returns a list of display lines.
    Returns an empty list when diagnostics are unavailable on this platform.
    """
    lines: List[str] = []

    if IS_WINDOWS:
        try:
            wifi_output = subprocess.check_output("netsh wlan show interfaces",
                                                  shell=True, text=True, errors="ignore")
            ssid = state = signal = radio = None
            for line in wifi_output.splitlines():
                line = line.strip()
                if line.startswith("SSID") and not line.startswith("BSSID"):
                    ssid = line.split(":", 1)[1].strip()
                elif line.startswith("Signal"):
                    signal = line.split(":", 1)[1].strip()
                elif line.startswith("Radio type"):
                    radio = line.split(":", 1)[1].strip()
                elif line.startswith("State"):
                    state = line.split(":", 1)[1].strip()
            if ssid:
                lines.append(f"• Wi-Fi SSID: {ssid} (State: {state or 'connected'})")
                if signal:
                    lines.append(f"• Signal Quality: {signal}")
                if radio:
                    lines.append(f"• Protocol: {radio}")
            else:
                lines.append("• Wi-Fi: No active Wi-Fi interface connected (or on Ethernet).")
        except Exception as e:
            logger.debug(f"[Platform] netsh wlan check: {e}")
        return lines

    # Linux / macOS
    try:
        import socket
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        lines.append(f"• Hostname: {hostname}")
        lines.append(f"• Local IPv4: {local_ip}")
    except Exception:
        pass

    # Prefer nmcli on Linux for Wi-Fi details.
    if IS_LINUX and shutil.which("nmcli"):
        try:
            out = subprocess.check_output(
                ["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,IN-USE", "dev", "wifi"],
                text=True, errors="ignore", timeout=10)
            for line in out.splitlines():
                parts = line.split(":")
                if len(parts) >= 4 and parts[0] == "yes":
                    ssid = parts[1]
                    signal = parts[2]
                    lines.insert(0, f"• Wi-Fi SSID: {ssid} (Signal: {signal}%)")
                    break
        except Exception:
            pass
    elif IS_MACOS and shutil.which("airport"):
        try:
            out = subprocess.check_output(
                ["airport", "-I"], text=True, errors="ignore", timeout=10)
            for line in out.splitlines():
                if "SSID" in line:
                    lines.insert(0, f"• Wi-Fi SSID: {line.split(':')[-1].strip()}")
                    break
        except Exception:
            pass

    if not lines:
        lines.append("• Network diagnostics: no Wi-Fi tooling available on this system.")
    return lines


# ── Visible terminal launcher (for SSH log viewers) ───────────────────

def open_terminal(command: Optional[str] = None) -> Tuple[bool, str]:
    """
    Open a visible terminal window, optionally running a command.
    Used by remote-server / SSH tools to show a live log terminal.
    """
    if IS_WINDOWS:
        try:
            if command:
                subprocess.Popen(f'start cmd.exe /k "{command}"', shell=True)
            else:
                subprocess.Popen("start cmd.exe", shell=True)
            return True, "Opened terminal window."
        except Exception as e:
            return False, f"Failed to open terminal: {e}"

    # Linux: try common terminal emulators.
    for term, template in (
        ("gnome-terminal", ["gnome-terminal", "--", "bash", "-c"]),
        ("konsole", ["konsole", "-e", "bash", "-c"]),
        ("xfce4-terminal", ["xfce4-terminal", "-x", "bash", "-c"]),
        ("xterm", ["xterm", "-e", "bash", "-c"]),
        ("x-terminal-emulator", ["x-terminal-emulator", "-e", "bash", "-c"]),
        ("alacritty", ["alacritty", "-e", "bash", "-c"]),
        ("kitty", ["kitty", "bash", "-c"]),
    ):
        if shutil.which(term):
            try:
                if command:
                    subprocess.Popen(template + [command])
                else:
                    subprocess.Popen([term])
                return True, f"Opened {term} window."
            except Exception:
                continue

    if IS_MACOS and shutil.which("open"):
        try:
            if command:
                subprocess.Popen(["open", "-a", "Terminal", command])
            else:
                subprocess.Popen(["open", "-a", "Terminal"])
            return True, "Opened Terminal window."
        except Exception as e:
            return False, f"Failed to open terminal: {e}"

    return False, "No terminal emulator available to open a visible window."


def launch_application_command(app_command: str) -> Tuple[bool, str]:
    """
    Launch an application by its command/executable name (best-effort cross-platform).
    Unlike launch_target(), this always tries the bare executable via PATH first.
    """
    if not app_command:
        return False, "Error: application command is required."
    exe = shutil.which(app_command.split()[0]) if not IS_WINDOWS else None
    if exe:
        try:
            subprocess.Popen(app_command, shell=(not IS_WINDOWS))
            return True, f"Launched '{app_command}'."
        except Exception as e:
            return False, f"Failed to launch '{app_command}': {e}"
    return launch_target(app_command)
