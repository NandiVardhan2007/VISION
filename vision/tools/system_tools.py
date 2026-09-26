"""
System and OS automation tools for Windows/Desktop control.
Handles Windows UWP apps, protocol handlers, Start Menu search, system metrics, and real-time clock.
"""

import os
from datetime import datetime
from typing import Optional
from pathlib import Path
from vision.tools.registry import tool
from vision.perception.vision.screen import screen_capture
from vision.perception.vision.gemini_vision import gemini_vision
from vision.logger import logger
from vision.platform import (
    IS_WINDOWS,
    launch_target,
    launch_application_command,
    find_desktop_app,
    open_path,
)

try:
    import psutil
except Exception:
    # psutil is a compiled C-extension; a broken/partial install can raise
    # beyond ImportError — catch broadly so module import (and all system
    # tools) survive a degraded psutil.
    psutil = None

# Known Windows protocol and executable map
APP_PROTOCOL_MAP = {
    "whatsapp": "whatsapp:",
    "whatsapp beta": "whatsapp:",
    "spotify": "spotify:",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "notepad": "notepad.exe",
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "settings": "ms-settings:",
    "camera": "microsoft.windows.camera:",
    "photos": "ms-photos:",
    "mail": "mailto:",
    "vscode": "code",
    "vs code": "code",
    "code": "code",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "terminal": "wt.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "microsoft store": "ms-windows-store:",
    "microsoftstore": "ms-windows-store:",
    "ms store": "ms-windows-store:",
    "store": "ms-windows-store:",
    "paint": "mspaint.exe",
    "wordpad": "wordpad.exe",
    "snipping tool": "ms-screenclip:",
    "snip": "ms-screenclip:",
    "control panel": "control.exe",
    "clock": "ms-clock:",
    "alarms": "ms-clock:",
    "weather": "bingweather:",
    "news": "bingnews:",
    "maps": "bingmaps:",
    "xbox": "xbox:",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "task manager": "taskmgr.exe",
    "taskmgr": "taskmgr.exe",
    "discord": "discord:",
    "telegram": "telegram:",
}


def _find_in_start_menu(app_name: str) -> Optional[Path]:
    """Search for matching .lnk shortcut in Windows Start Menu directories."""
    if not IS_WINDOWS:
        # On Linux/macOS use the cross-platform .desktop / Applications scan.
        return find_desktop_app(app_name)
    app_name_lower = app_name.lower().replace(" ", "")
    search_dirs = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("ProgramData", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("USERPROFILE", "")) / "Desktop",
        Path(os.environ.get("PUBLIC", "")) / "Desktop",
    ]

    for sdir in search_dirs:
        if sdir.exists():
            for lnk in sdir.rglob("*.lnk"):
                clean_stem = lnk.stem.lower().replace(" ", "")
                if app_name_lower in clean_stem or clean_stem in app_name_lower:
                    return lnk
    return None


@tool(name="open_application", description="Launch an installed desktop application, app-store app, or open a URL. Cross-platform: works on Windows, Linux, and macOS.")
def open_application(app_name: str) -> str:
    """Launch an application on the host OS."""
    clean_name = app_name.strip().lower()

    # 1. Check known protocol map (e.g. WhatsApp, Spotify, Calculator, Settings)
    if clean_name in APP_PROTOCOL_MAP:
        target = APP_PROTOCOL_MAP[clean_name]
        try:
            ok, msg = launch_target(target)
            if ok:
                logger.info(f"[SystemTool] Launched via protocol/command: {target}")
                return f"Successfully opened {app_name}."
            logger.warning(f"[SystemTool] Protocol launch failed for {target}: {msg}")
        except Exception as e:
            logger.warning(f"[SystemTool] Protocol launch failed for {target}: {e}")

    # 2. Check Start Menu / Applications / .desktop shortcuts
    lnk_path = _find_in_start_menu(app_name)
    if lnk_path:
        try:
            # On Windows the result is always a .lnk path → os.startfile handles it.
            # On Linux/macOS find_desktop_app may return a COMMAND string
            # (e.g. "gtk-launch foo"), not a real file — open_path would then
            # try to xdg-open a non-existent path. Route non-Windows results
            # through launch_application_command, which runs the command when it
            # is one and otherwise falls back to launch_target for real paths.
            if IS_WINDOWS:
                ok, msg = open_path(str(lnk_path))
            else:
                ok, msg = launch_application_command(str(lnk_path))
            if ok:
                logger.info(f"[SystemTool] Launched via shortcut: {lnk_path}")
                label = getattr(lnk_path, "stem", app_name)
                return f"Successfully opened {label}."
        except Exception as e:
            logger.warning(f"[SystemTool] Shortcut launch failed: {e}")

    # 3. Try the bare executable name / URI scheme via cross-platform launcher
    try:
        ok, msg = launch_target(clean_name)
        if ok:
            logger.info(f"[SystemTool] Attempted launch: {app_name}")
            return f"Successfully launched {app_name}."
    except Exception:
        pass

    # 4. Fallback to launching the raw command
    try:
        from vision.platform import launch_application_command
        ok, msg = launch_application_command(app_name)
        if ok:
            return f"Successfully launched {app_name}."
    except Exception:
        pass
    return f"Could not find or launch '{app_name}' on this system."


@tool(name="get_current_time_and_date", description="Get the exact current local system time, day of the week, and date.")
def get_current_time_and_date() -> str:
    """Get the current live local time and date."""
    now = datetime.now()
    return f"Current Local Time: {now.strftime('%I:%M:%S %p')}\nCurrent Date: {now.strftime('%A, %B %d, %Y')}"


@tool(name="get_system_stats", description="Get CPU, memory, and battery status of the host computer.")
def get_system_stats() -> str:
    """Retrieve host performance statistics."""
    if not psutil:
        return "psutil package is not installed; system metrics unavailable."
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    # sensors_battery() is absent on some platforms (server Linux, some macOS)
    # and can raise, not just return None — guard both.
    try:
        battery = psutil.sensors_battery()
    except Exception:
        battery = None
    bat_str = f"{battery.percent}% ({'Plugged in' if battery.power_plugged else 'On Battery'})" if battery else "No battery detected"
    return f"CPU Usage: {cpu}%\nRAM Usage: {mem.percent}% ({mem.used // (1024*1024)}MB / {mem.total // (1024*1024)}MB)\nBattery: {bat_str}"


@tool(name="read_screen", description="Take a screenshot and use vision AI to describe the current desktop contents.")
async def read_screen(query: str = "Describe what is currently visible on the screen") -> str:
    """Inspect and analyze the screen visually."""
    img_bytes = screen_capture.capture_screen()
    if not img_bytes:
        return "Failed to capture desktop screenshot."
    try:
        analysis = await gemini_vision.analyze_image(img_bytes, prompt=query)
        return analysis
    except Exception as e:
        return f"Failed to analyze screen with Vision AI: {e}"
