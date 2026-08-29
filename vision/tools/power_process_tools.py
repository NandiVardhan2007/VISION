"""
Power Management & Process Control Tools for VISION AI OS.
Allows VISION to safely terminate frozen processes, sleep/lock the PC, schedule shutdown, and empty the recycle bin.
"""

import os
import time

try:
    import psutil
except ImportError:
    psutil = None

from typing import Optional
from vision.tools.registry import tool
from vision.logger import logger
from vision.platform import (
    lock_workstation,
    suspend_computer,
    empty_trash,
    shutdown_machine,
    restart_machine,
    cancel_shutdown,
)


@tool(name="kill_process_by_name", description="Force terminate / kill an application or background process by name (e.g. chrome, notepad, discord, code, python).")
def kill_process_by_name(process_name: str) -> str:
    """Terminates matching running processes safely."""
    if not process_name:
        return "Error: Process name is required."

    target = process_name.lower().replace(".exe", "").strip()
    killed_count = 0

    # Protect critical OS processes
    protected = ["explorer", "csrss", "lsass", "services", "system", "svchost", "winlogon", "smss"]
    if target in protected:
        return f"Error: Process '{target}' is a critical Windows system process and cannot be terminated."

    logger.info(f"[PowerTool] Searching to kill processes matching '{target}'...")
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            pname = proc.info['name'].lower().replace(".exe", "")
            if target in pname or pname in target:
                proc.kill()
                killed_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    if killed_count > 0:
        logger.info(f"[PowerTool] Terminated {killed_count} instance(s) of '{target}'.")
        return f"Successfully terminated {killed_count} process instance(s) matching '{process_name}'."
    else:
        return f"No running processes found matching '{process_name}'."


@tool(name="lock_workstation", description="Lock the computer / lock screen immediately.")
def lock_workstation_tool() -> str:
    """Locks the current workstation instantly."""
    logger.info("[PowerTool] Locking workstation...")
    return lock_workstation()


@tool(name="sleep_pc", description="Put the computer into sleep mode.")
def sleep_pc() -> str:
    """Puts the computer to sleep."""
    logger.info("[PowerTool] Putting PC to sleep...")
    return suspend_computer()


@tool(name="empty_recycle_bin", description="Empty the Recycle Bin / Trash to free up disk space.")
def empty_recycle_bin_tool() -> str:
    """Empties the recycle bin / trash silently."""
    logger.info("[PowerTool] Emptying Recycle Bin...")
    return empty_trash()


@tool(name="shutdown_pc", description="Schedule a computer shutdown with a 15-second safety timer (can be cancelled).")
def shutdown_pc(timer_seconds: int = 15) -> str:
    """Schedules a safe shutdown."""
    logger.warning(f"[PowerTool] Scheduling shutdown in {timer_seconds}s...")
    return shutdown_machine(timer_seconds)


@tool(name="restart_pc", description="Schedule a computer restart with a 15-second safety timer (can be cancelled).")
def restart_pc(timer_seconds: int = 15) -> str:
    """Schedules a safe restart."""
    logger.warning(f"[PowerTool] Scheduling restart in {timer_seconds}s...")
    return restart_machine(timer_seconds)


@tool(name="cancel_shutdown", description="Cancel a pending scheduled computer shutdown or restart.")
def cancel_shutdown_tool() -> str:
    """Cancels any pending shutdown or restart."""
    logger.info("[PowerTool] Aborting scheduled shutdown/restart...")
    return cancel_shutdown()
