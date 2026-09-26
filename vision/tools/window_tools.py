"""
Window & Desktop Productivity Tools for VISION AI OS.
Provides control over desktop windows, minimizing, maximizing, snapping, switching, and closing applications.
"""

import time
import re
from typing import Optional, List

try:
    import psutil
except Exception:
    # Match the pyautogui/pygetwindow guards below: a broken/partial install can
    # raise more than ImportError at import time.
    psutil = None

from vision.tools.registry import tool
from vision.logger import logger
from vision.platform import IS_WINDOWS

# pyautogui and pygetwindow are independent optional deps. pygetwindow in
# particular raises NotImplementedError (not ImportError) on import on Linux
# where it has no backend, so catch Exception and keep them in separate blocks
# so one failing doesn't disable the other.
try:
    import pyautogui
    if pyautogui:
        pyautogui.FAILSAFE = False
except Exception:
    pyautogui = None

try:
    import pygetwindow as gw
except Exception:
    gw = None


# Common process aliases mapping
PROCESS_ALIASES = {
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "notepad": "notepad.exe",
    "calculator": "CalculatorApp.exe",
    "calc": "CalculatorApp.exe",
    "vlc": "vlc.exe",
    "spotify": "Spotify.exe",
    "whatsapp": "WhatsApp.exe",
    "vs code": "Code.exe",
    "vscode": "Code.exe",
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
    "terminal": "WindowsTerminal.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
}


@tool(name="show_desktop", description="Toggle or show the Windows desktop by minimizing all open windows.")
def show_desktop() -> str:
    """Show the Windows desktop (Win + D)."""
    if not IS_WINDOWS:
        return "Error: show_desktop uses the Windows Win+D shortcut and is only available on Windows."
    if pyautogui:
        pyautogui.hotkey("win", "d")
        logger.info("[WindowTool] Toggled Show Desktop.")
        return "Toggled Windows Desktop (minimized/restored all windows)."
    return "Error: PyAutoGUI is not available."


@tool(name="minimize_all_windows", description="Minimize all active application windows on the desktop.")
def minimize_all_windows() -> str:
    """Minimize all windows (Win + M)."""
    if not IS_WINDOWS:
        return "Error: minimize_all_windows uses the Windows Win+M shortcut and is only available on Windows."
    if pyautogui:
        pyautogui.hotkey("win", "m")
        logger.info("[WindowTool] Minimized all windows.")
        return "Minimized all open windows."
    return "Error: PyAutoGUI is not available."


@tool(name="restore_windows", description="Restore all previously minimized windows back to the screen.")
def restore_windows() -> str:
    """Restore minimized windows (Win + Shift + M)."""
    if not IS_WINDOWS:
        return "Error: restore_windows uses the Windows Win+Shift+M shortcut and is only available on Windows."
    if pyautogui:
        pyautogui.hotkey("win", "shift", "m")
        logger.info("[WindowTool] Restored minimized windows.")
        return "Restored minimized windows."
    return "Error: PyAutoGUI is not available."


@tool(name="close_application", description="Close or terminate a running desktop application (e.g. 'chrome', 'notepad', 'whatsapp', 'spotify', 'edge').")
def close_application(app_name: str) -> str:
    """Close an application gracefully or terminate its process."""
    if not app_name:
        return "Error: Application name is required."

    target = app_name.lower().strip()
    target_proc = PROCESS_ALIASES.get(target, f"{target}.exe" if not target.endswith(".exe") else target)

    closed_count = 0
    # Try process termination (psutil is an optional dependency)
    if psutil is not None:
        for p in psutil.process_iter(['name', 'pid']):
            try:
                p_name = p.info['name']
                if not p_name:
                    continue
                p_low = p_name.lower()
                p_stem = p_low[:-4] if p_low.endswith(".exe") else p_low
                # Exact matches only. A substring fallback (e.g. `target in
                # p_stem`) is dangerous here because terminate() is destructive:
                # "word" would kill wordpad.exe and "note" would kill onenote.exe.
                # Aliases + the ".exe" suffixing already resolve the common apps.
                if p_low == target_proc.lower() or p_stem == target:
                    p.terminate()
                    closed_count += 1
            except Exception:
                pass

    if closed_count > 0:
        logger.info(f"[WindowTool] Terminated {closed_count} process instance(s) of '{app_name}'")
        return f"Successfully closed '{app_name}' ({closed_count} process instance(s) terminated)."

    # Fallback to Alt+F4 only if the focused window actually belongs to the
    # requested app. A blind Alt+F4 would close whatever the user is currently
    # working in, which is destructive and surprising.
    if pyautogui and gw:
        active_title = ""
        try:
            active = gw.getActiveWindow()
            active_title = (active.title or "").lower() if active else ""
        except Exception:
            active_title = ""
        # Require a WHOLE-WORD match (not a loose substring) against the focused
        # window's title, and ignore very short targets. A substring test would
        # fire Alt+F4 on the wrong focused window — e.g. "x" matching "Firefox"
        # / "Excel", or "word" matching a title containing "password".
        stem = target_proc[:-4] if target_proc.lower().endswith(".exe") else target
        candidates = {t for t in (target, stem) if t and len(t) >= 3}
        matched = bool(active_title) and any(
            re.search(rf"\b{re.escape(t)}\b", active_title) for t in candidates
        )
        if matched:
            pyautogui.hotkey("alt", "f4")
            logger.info(f"[WindowTool] Alt+F4 sent to focused '{app_name}' window.")
            return f"Sent close command (Alt+F4) to the active '{app_name}' window."
        return (f"No active process found matching '{app_name}', and the focused window "
                f"does not appear to be it — nothing was closed.")

    return f"No active process found matching '{app_name}'."


@tool(name="switch_to_window", description="Bring a specific open application window to the foreground and focus it.")
def switch_to_window(app_name: str) -> str:
    """Bring target application window to front."""
    if not app_name:
        return "Error: App name is required."

    target = app_name.lower().strip()
    # Resolve alias (e.g. "vs code" -> "Code.exe") and build whole-word match
    # candidates, mirroring close_application. A loose substring test focused the
    # wrong window (e.g. "x" matching "Firefox"/"Excel").
    target_proc = PROCESS_ALIASES.get(target, target)
    stem = target_proc[:-4] if target_proc.lower().endswith(".exe") else target_proc
    candidates = {t for t in (target, stem) if t and len(t) >= 3}
    if gw and candidates:
        try:
            for w in gw.getAllWindows():
                title_low = (w.title or "").lower()
                if title_low and any(re.search(rf"\b{re.escape(t)}\b", title_low) for t in candidates):
                    if w.isMinimized:
                        w.restore()
                    w.activate()
                    time.sleep(0.15)
                    logger.info(f"[WindowTool] Focused window: '{w.title}'")
                    return f"Switched to '{w.title}'."
        except Exception as e:
            logger.debug(f"[WindowTool] Window activate note: {e}")

    # No blind Alt+Tab fallback: it would switch to an arbitrary window while
    # falsely reporting success for the requested app.
    return f"Could not find an open window matching '{app_name}'."


@tool(name="maximize_window", description="Maximize the currently active window.")
def maximize_window() -> str:
    """Maximize current window (Win + Up)."""
    if not IS_WINDOWS:
        return "Error: maximize_window uses the Windows Win+Up shortcut and is only available on Windows."
    if pyautogui:
        pyautogui.hotkey("win", "up")
        logger.info("[WindowTool] Maximized active window.")
        return "Maximized active window."
    return "Error: PyAutoGUI not available."


@tool(name="snap_window", description="Snap the active window to the screen side (direction='left' or direction='right').")
def snap_window(direction: str = "left") -> str:
    """Snap active window left or right."""
    if not IS_WINDOWS:
        return "Error: snap_window uses Windows Win+arrow shortcuts and is only available on Windows."
    if not pyautogui:
        return "Error: PyAutoGUI not available."

    dir_clean = direction.lower().strip()
    if "left" in dir_clean:
        pyautogui.hotkey("win", "left")
        return "Snapped window to the left side."
    elif "right" in dir_clean:
        pyautogui.hotkey("win", "right")
        return "Snapped window to the right side."
    elif "up" in dir_clean or "top" in dir_clean:
        pyautogui.hotkey("win", "up")
        return "Maximized / snapped window up."
    elif "down" in dir_clean or "bottom" in dir_clean:
        pyautogui.hotkey("win", "down")
        return "Minimized / snapped window down."

    return f"Unsupported snap direction '{direction}'. Use 'left' or 'right'."


@tool(name="list_running_applications", description="List common user-facing applications currently running on your PC.")
def list_running_applications() -> str:
    """List running user apps."""
    if psutil is None:
        return "Error: psutil is not installed; cannot enumerate running processes."
    found = set()
    for p in psutil.process_iter(['name']):
        try:
            name = p.info['name']
            if name:
                n_lower = name.lower()
                for alias, proc in PROCESS_ALIASES.items():
                    if n_lower == proc.lower():
                        found.add(alias.title())
        except Exception:
            pass

    if not found:
        return "No known user-facing apps currently detected in foreground processes."

    return "Running User Applications:\n" + "\n".join(f"- {app}" for app in sorted(found))
