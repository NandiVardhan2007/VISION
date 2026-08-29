"""
Remote Ubuntu Server Autopilot & KPR Parking Print System Watchdog Tools.
Provides headless SSH management, server health diagnostics, live parking log inspection, log clearing, and system restarts for Nandu's Hyderabad Ubuntu Server (100.93.70.63).
"""

import time
import subprocess
from typing import Optional, Dict, Any
from vision.tools.registry import tool
from vision.config import config
from vision.logger import logger
from vision.platform import open_terminal

try:
    import paramiko
except ImportError:
    paramiko = None

try:
    import pyautogui
    if pyautogui:
        pyautogui.FAILSAFE = False
except ImportError:
    pyautogui = None


def _get_ssh_client(
    host: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    port: Optional[int] = None,
    timeout_seconds: int = 15
):
    """Create an authenticated Paramiko SSH client."""
    if not paramiko:
        raise RuntimeError("paramiko library is not installed.")

    target_host = host or config.UBUNTU_SERVER_HOST
    target_user = username or config.UBUNTU_SERVER_USER
    target_pass = password or config.UBUNTU_SERVER_PASSWORD
    target_port = port or config.UBUNTU_SERVER_PORT

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=target_host,
        port=target_port,
        username=target_user,
        password=target_pass,
        timeout=timeout_seconds,
        banner_timeout=timeout_seconds,
        auth_timeout=timeout_seconds
    )
    return client


@tool(
    name="ssh_execute_command",
    description="Execute a bash command headlessly over SSH on the remote Hyderabad Ubuntu server (100.93.70.63) and return stdout/stderr."
)
def ssh_execute_command(
    command: str,
    working_directory: Optional[str] = None,
    host: Optional[str] = None,
    username: Optional[str] = None,
    timeout_seconds: int = 25
) -> str:
    """
    Execute any shell command on the remote Ubuntu server via SSH and return output.
    """
    if not command:
        return "Error: Command is required."

    target_host = host or config.UBUNTU_SERVER_HOST
    cwd = working_directory or config.KPR_PRINT_SERVER_PATH
    full_cmd = f"cd {cwd} && {command}" if cwd else command

    logger.info(f"[RemoteServer] Executing SSH command on {target_host}: '{full_cmd}'...")
    start_time = time.time()

    client = None
    try:
        client = _get_ssh_client(host=target_host, username=username, timeout_seconds=timeout_seconds)
        stdin, stdout, stderr = client.exec_command(full_cmd, timeout=timeout_seconds)
        
        out_text = stdout.read().decode("utf-8", errors="replace").strip()
        err_text = stderr.read().decode("utf-8", errors="replace").strip()
        exit_code = stdout.channel.recv_exit_status()
        elapsed = round(time.time() - start_time, 2)

        output_parts = []
        if out_text:
            if len(out_text) > 3000:
                out_text = out_text[:3000] + f"\n... [Truncated {len(out_text) - 3000} characters]"
            output_parts.append(out_text)
        if err_text:
            if len(err_text) > 1000:
                err_text = err_text[:1000] + "\n... [Truncated error log]"
            output_parts.append(f"Errors/Warnings:\n{err_text}")

        res = "\n".join(output_parts) if output_parts else "Command executed successfully with no output."
        logger.info(f"[RemoteServer] Finished in {elapsed}s (Exit code: {exit_code})")
        return f"[Host: {target_host} | Exit code: {exit_code} | Time: {elapsed}s]\n{res}"

    except Exception as e:
        logger.error(f"[RemoteServer] SSH execution failed: {e}")
        return f"Error executing SSH command on {target_host}: {str(e)}"
    finally:
        if client:
            client.close()


@tool(
    name="check_ubuntu_server_health",
    description="Check remote Ubuntu server health diagnostics (CPU load, RAM usage, storage/disk free, uptime, temperature, active network IP) on Hyderabad server (100.93.70.63)."
)
def check_ubuntu_server_health(host: Optional[str] = None) -> str:
    """
    Retrieves real-time system metrics from the Ubuntu server.
    """
    target_host = host or config.UBUNTU_SERVER_HOST
    cmd = (
        "echo '=== UPTIME & LOAD ===' && uptime && "
        "echo '\n=== MEMORY USAGE (MB) ===' && free -m && "
        "echo '\n=== DISK SPACE (/) ===' && df -h / && "
        "echo '\n=== CPU TEMPERATURE & SENSORS ===' && (sensors 2>/dev/null || cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 'N/A') && "
        "echo '\n=== PRINT SERVER PROCESSES ===' && (pgrep -fa python3 || echo 'No active python processes')"
    )
    return ssh_execute_command(command=cmd, working_directory="/home/nandu", host=target_host)


@tool(
    name="open_parking_logs_terminal",
    description="Open a visible Windows CMD terminal window, connect via SSH to Ubuntu server (100.93.70.63), auto-enter password, navigate to ~/print-server, and live-stream kpr_print.log."
)
def open_parking_logs_terminal(lines: int = 50, host: Optional[str] = None) -> str:
    """
    Launches a dedicated visible CMD terminal, SSHs into 100.93.70.63, enters password,
    and runs 'cd ~/print-server && tail -n 50 -f kpr_print.log'.
    """
    target_host = host or config.UBUNTU_SERVER_HOST
    target_user = config.UBUNTU_SERVER_USER
    password = config.UBUNTU_SERVER_PASSWORD

    ssh_cmd = f"title KPR Parking Print Server ({target_host}) && ssh {target_user}@{target_host}"
    logger.info(f"[RemoteServer] Launching live SSH parking log terminal...")

    try:
        ok, msg = open_terminal(ssh_cmd)
        time.sleep(1.8)

        if pyautogui and password:
            # Enter password into the SSH prompt
            pyautogui.write(password, interval=0.03)
            time.sleep(0.3)
            pyautogui.press("enter")
            time.sleep(1.5)

            # Navigate to directory and tail the log
            log_cmd = f"cd ~/print-server && tail -n {lines} -f kpr_print.log"
            pyautogui.write(log_cmd, interval=0.02)
            time.sleep(0.2)
            pyautogui.press("enter")
            logger.info(f"[RemoteServer] Live parking log stream started in terminal for {target_user}@{target_host}")

        return f"Opened live SSH terminal window connected to {target_host} and streaming kpr_print.log." if ok else f"Opened terminal: {msg}"
    except Exception as e:
        logger.error(f"[RemoteServer] Failed to open live log terminal: {e}")
        return f"Failed to open live log terminal: {e}"


@tool(
    name="check_parking_logs",
    description="Inspect recent KPR parking print system logs from /home/nandu/print-server/kpr_print.log on the remote Ubuntu server (100.93.70.63) and open a live visible CMD SSH terminal streaming the logs."
)
def check_parking_logs(lines: int = 50, open_terminal: bool = True, host: Optional[str] = None) -> str:
    """
    Fetches the last N lines from the KPR parking log file and opens an interactive visible CMD terminal window.
    """
    target_host = host or config.UBUNTU_SERVER_HOST
    log_path = config.KPR_LOG_PATH
    
    # 1. Open dedicated visible terminal streaming the log in another window
    if open_terminal:
        try:
            open_parking_logs_terminal(lines=lines, host=target_host)
        except Exception as e:
            logger.warning(f"[RemoteServer] Error opening terminal: {e}")

    # 2. Also retrieve the text directly
    cmd = (
        f"if [ -f '{log_path}' ]; then "
        f"echo '=== KPR PARKING LOGS (LAST {lines} LINES) ==='; "
        f"tail -n {lines} '{log_path}'; "
        f"echo '\n=== LOG FILE STATS ==='; "
        f"ls -lh '{log_path}'; "
        f"else echo 'Log file not found at {log_path}'; fi"
    )
    return ssh_execute_command(command=cmd, working_directory=config.KPR_PRINT_SERVER_PATH, host=target_host)


@tool(
    name="clear_parking_logs",
    description="Clear and reset the KPR parking print log (/home/nandu/print-server/kpr_print.log) on the Hyderabad Ubuntu server (100.93.70.63), creating a backup first."
)
def clear_parking_logs(backup_first: bool = True, host: Optional[str] = None) -> str:
    """
    Clears /home/nandu/print-server/kpr_print.log with optional backup.
    """
    target_host = host or config.UBUNTU_SERVER_HOST
    log_path = config.KPR_LOG_PATH
    
    if backup_first:
        cmd = (
            f"if [ -f '{log_path}' ]; then "
            f"cp '{log_path}' '{log_path}.bak_$(date +%Y%m%d_%H%M%S)' && "
            f"> '{log_path}' && "
            f"echo 'Successfully backed up and cleared {log_path}. New file size: 0 bytes'; "
            f"else > '{log_path}' && echo 'Created fresh empty log file at {log_path}'; fi"
        )
    else:
        cmd = f"> '{log_path}' && echo 'Cleared {log_path}. File size: 0 bytes'"

    return ssh_execute_command(command=cmd, working_directory=config.KPR_PRINT_SERVER_PATH, host=target_host)


@tool(
    name="restart_kpr_print_system",
    description="Restart the KPR parking print server application (print_server_ubuntu.py) on the remote Ubuntu server (100.93.70.63)."
)
def restart_kpr_print_system(host: Optional[str] = None) -> str:
    """
    Restarts the print server daemon/script on the remote Ubuntu server.
    """
    target_host = host or config.UBUNTU_SERVER_HOST
    cwd = config.KPR_PRINT_SERVER_PATH
    
    cmd = (
        f"echo 'Stopping existing print server processes...' && "
        f"pkill -f print_server_ubuntu.py || true && "
        f"sleep 1 && "
        f"echo 'Starting KPR print server in background...' && "
        f"nohup /home/nandu/print-server/venv/bin/python3 print_server_ubuntu.py > /dev/null 2>&1 & "
        f"sleep 2 && "
        f"echo 'Current running print processes:' && "
        f"pgrep -fa print_server_ubuntu.py"
    )
    return ssh_execute_command(command=cmd, working_directory=cwd, host=target_host)


@tool(
    name="open_interactive_ssh_terminal",
    description="Open a visible Windows CMD terminal and log directly into the Hyderabad Ubuntu Server (100.93.70.63) via interactive SSH with auto-password entry."
)
def open_interactive_ssh_terminal(host: Optional[str] = None, username: Optional[str] = None, initial_directory: Optional[str] = "~/print-server") -> str:
    """
    Opens an interactive visible terminal session logged into the Ubuntu server.
    """
    target_host = host or config.UBUNTU_SERVER_HOST
    target_user = username or config.UBUNTU_SERVER_USER
    password = config.UBUNTU_SERVER_PASSWORD

    ssh_cmd = f"title Ubuntu Server ({target_user}@{target_host}) && ssh {target_user}@{target_host}"
    logger.info(f"[RemoteServer] Launching interactive SSH session...")

    try:
        ok, msg = open_terminal(ssh_cmd)
        time.sleep(1.8)

        if pyautogui and password:
            pyautogui.write(password, interval=0.03)
            time.sleep(0.3)
            pyautogui.press("enter")
            if initial_directory:
                time.sleep(1.5)
                pyautogui.write(f"cd {initial_directory} && ls -la", interval=0.02)
                time.sleep(0.2)
                pyautogui.press("enter")
            logger.info(f"[RemoteServer] Authenticated interactive SSH to {target_user}@{target_host}")

        return f"Opened interactive terminal connected to Ubuntu server ({target_user}@{target_host})." if ok else f"Opened terminal: {msg}"
    except Exception as e:
        logger.error(f"[RemoteServer] Interactive SSH failed: {e}")
        return f"Failed to open interactive SSH terminal: {e}"
