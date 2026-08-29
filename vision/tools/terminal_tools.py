"""
Terminal, Shell & Developer Execution Tools for VISION AI OS.
Allows VISION to safely execute shell commands, run Python snippets, query Git status, and connect to SSH/Ubuntu servers.
"""

import os
import sys
import time
import subprocess
import re
from pathlib import Path
from typing import Optional, Dict, Any
from vision.tools.registry import tool
from vision.logger import logger
from vision.platform import open_terminal, IS_WINDOWS

try:
    import pyautogui
    if pyautogui:
        pyautogui.FAILSAFE = False
except ImportError:
    pyautogui = None

# Banned dangerous commands for host security
DANGEROUS_PATTERNS = [
    r"\bformat\s+[a-z]:",
    r"\brmdir\s+/s\s+/q\s+c:\\windows",
    r"\bdel\s+/f\s+/s\s+/q\s+c:\\windows",
    r"\bdiskpart\b",
    r":\(\)\{\s*:\s*\|\s*:\s*&\s*\}\s*;",  # Fork bomb
]


def _is_safe_command(cmd: str) -> bool:
    """Check if command contains destructive system deletion commands."""
    cmd_lower = cmd.lower().strip()
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, cmd_lower):
            return False
    return True


@tool(name="execute_terminal_command", description="Execute a PowerShell/CMD shell command (e.g. dir, git, npm, pip, python, curl, ping, netstat, tasklist, ipconfig) and return stdout/stderr.")
def execute_terminal_command(command: str, working_directory: Optional[str] = None, timeout_seconds: int = 30) -> str:
    """
    Safely executes a shell command in PowerShell/CMD, capturing stdout and stderr.
    Default working directory is the VISION project root or user home directory.
    """
    if not command:
        return "Error: Command string is required."

    if not _is_safe_command(command):
        return f"Error: Command blocked for security safety: '{command}'"

    cwd = working_directory or str(Path.cwd())
    if not Path(cwd).exists():
        cwd = str(Path.home())

    # Coerce timeout to integer to prevent string type errors from LLM arguments
    try:
        t_sec = int(timeout_seconds) if timeout_seconds else 30
    except Exception:
        t_sec = 30

    logger.info(f"[TerminalTool] Executing command: '{command}' in '{cwd}' (timeout: {t_sec}s)...")
    start_time = time.time()

    try:
        # Run through PowerShell on Windows; through the default POSIX shell elsewhere.
        if IS_WINDOWS:
            process = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=t_sec,
                encoding="utf-8",
                errors="replace",
            )
        else:
            process = subprocess.run(
                command,
                cwd=cwd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=t_sec,
                encoding="utf-8",
                errors="replace",
            )

        elapsed = round(time.time() - start_time, 2)
        stdout = process.stdout.strip()
        stderr = process.stderr.strip()

        # Format output cleanly
        output_parts = []
        if stdout:
            # Truncate very long terminal output to keep prompt token-efficient
            if len(stdout) > 2500:
                stdout = stdout[:2500] + f"\n... [Truncated {len(stdout) - 2500} characters]"
            output_parts.append(stdout)
        if stderr:
            if len(stderr) > 1000:
                stderr = stderr[:1000] + f"\n... [Truncated error log]"
            output_parts.append(f"Errors/Warnings:\n{stderr}")

        result_text = "\n".join(output_parts) if output_parts else "Command completed with no output."
        logger.info(f"[TerminalTool] Command finished in {elapsed}s (Exit code: {process.returncode})")
        return f"[Exit code: {process.returncode} | Time: {elapsed}s]\n{result_text}"

    except subprocess.TimeoutExpired:
        logger.warning(f"[TerminalTool] Command timed out after {t_sec}s: '{command}'")
        return f"Error: Command timed out after {t_sec} seconds."
    except Exception as e:
        logger.error(f"[TerminalTool] Command execution error: {e}")
        return f"Error executing command: {e}"


@tool(name="run_python_code", description="Run a Python script or code snippet and return its execution output.")
def run_python_code(code: str, timeout_seconds: int = 20) -> str:
    """
    Executes a Python code snippet using the current Python environment and returns stdout/stderr.
    """
    if not code:
        return "Error: Python code content is required."

    try:
        t_sec = int(timeout_seconds) if timeout_seconds else 20
    except Exception:
        t_sec = 20

    logger.info(f"[TerminalTool] Running Python snippet ({len(code)} chars)...")
    start_time = time.time()

    try:
        process = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=t_sec,
            encoding="utf-8",
            errors="replace"
        )

        elapsed = round(time.time() - start_time, 2)
        stdout = process.stdout.strip()
        stderr = process.stderr.strip()

        output = stdout if stdout else "Code executed with no stdout output."
        if stderr:
            output += f"\nErrors:\n{stderr}"

        return f"[Exit code: {process.returncode} | Time: {elapsed}s]\n{output}"

    except subprocess.TimeoutExpired:
        return f"Error: Python code execution timed out after {timeout_seconds} seconds."
    except Exception as e:
        return f"Error executing Python code: {e}"


@tool(name="git_status_and_summary", description="Get Git branch, modified files, and recent commits for a repository directory.")
def git_status_and_summary(repo_path: Optional[str] = None) -> str:
    """Check Git status, current branch, uncommitted changes, and last 3 commits."""
    cwd = repo_path or str(Path.cwd())
    if not (Path(cwd) / ".git").exists():
        return f"Error: '{cwd}' is not a Git repository."

    status_out = execute_terminal_command("git status --short", working_directory=cwd, timeout_seconds=10)
    log_out = execute_terminal_command("git log -n 3 --oneline", working_directory=cwd, timeout_seconds=10)
    branch_out = execute_terminal_command("git branch --show-current", working_directory=cwd, timeout_seconds=5)

    return f"Git Branch: {branch_out.strip()}\n\nModified Files:\n{status_out.strip()}\n\nRecent Commits:\n{log_out.strip()}"


def _resolve_server_credentials(target: str, username_override: Optional[str] = None) -> tuple[str, str, Optional[str]]:
    """
    Dynamically retrieve SSH host, username, and password from MAG long-term memory.
    """
    clean_target = (target or "ubuntu").strip()
    host = clean_target
    user = username_override or "nandu"
    password = None

    try:
        from vision.memory.mag_engine import mag_engine
        query = f"{clean_target} server ssh ip password host hyderabad kpr"
        memories = mag_engine.search_memories(query, limit=5)
        for m in memories:
            content = m.get("content", "")
            # 1. Search for IP
            ip_match = re.search(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", content)
            if ip_match and ("server" in clean_target.lower() or "ubuntu" in clean_target.lower() or "kpr" in clean_target.lower() or "hyderabad" in clean_target.lower() or clean_target in content.lower()):
                host = ip_match.group(1)

            # 2. Search for username
            user_match = re.search(r"username\s+(?:is\s+)?([a-zA-Z0-9_\-]+)", content, re.IGNORECASE)
            if user_match and not username_override:
                user = user_match.group(1)

            # 3. Search for password
            pwd_match = re.search(r"password\s+(?:is\s+)?([^\s\.,;]+)", content, re.IGNORECASE)
            if pwd_match:
                password = pwd_match.group(1)

        logger.info(f"[TerminalTool] Resolved server '{clean_target}' -> {user}@{host} from MAG memory.")
    except Exception as e:
        logger.debug(f"[TerminalTool] Server memory lookup note: {e}")

    return host, user, password


@tool(name="connect_to_ssh_server", description="Open a new visible CMD terminal and connect via SSH to a remote server (retrieves IP, username, and auth from MAG memory).")
def connect_to_ssh_server(server_name_or_ip: str = "ubuntu", username: Optional[str] = None) -> str:
    """
    Opens a visible terminal, retrieves credentials from MAG memory, connects via SSH, and auto-authenticates.
    """
    host, user, password = _resolve_server_credentials(server_name_or_ip, username)

    ssh_cmd = f"title Ubuntu Server ({user}@{host}) && ssh {user}@{host}"
    logger.info(f"[TerminalTool] Launching SSH session...")

    try:
        ok, msg = open_terminal(ssh_cmd)
        time.sleep(1.8)

        if pyautogui and password:
            # Enter password into the open SSH terminal
            pyautogui.write(password, interval=0.03)
            time.sleep(0.3)
            pyautogui.press("enter")
            logger.info(f"[TerminalTool] Authenticated SSH connection to {user}@{host}")

        return f"Opened terminal and connected to SSH server ({user}@{host})." if ok else f"Opened terminal: {msg}"
    except Exception as e:
        logger.error(f"[TerminalTool] SSH connection failed: {e}")
        return f"Failed to connect to SSH server: {e}"
