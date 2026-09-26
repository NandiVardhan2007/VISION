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
except Exception:
    # pyautogui can raise beyond ImportError on a headless/no-DISPLAY host;
    # a bare `except ImportError` would let that kill module import.
    pyautogui = None

# Banned dangerous commands for host security (Windows + POSIX)
DANGEROUS_PATTERNS = [
    # ── Windows ──────────────────────────────────────────────
    r"\bformat\s+[a-z]:",
    r"\brmdir\s+/s\s+/q\s+c:\\windows",
    r"\bdel\s+/f\s+/s\s+/q\s+c:\\windows",
    r"\bdiskpart\b",
    # ── POSIX ────────────────────────────────────────────────
    r":\(\)\{\s*:\s*\|\s*:\s*&\s*\}\s*;",              # Fork bomb
    r"\brm\s+-\w*[rf]\w*[rf]\w*\s+(?:--no-preserve-root\s+)?(?:/|/\*|~)(?:\s|$)",  # rm -rf / , /*, ~
    r"\brm\s+--recursive\s+--force\s+(?:/|~)(?:\s|$)",
    r"--no-preserve-root",
    r"\bmkfs(?:\.\w+)?\b",                              # format filesystem
    r"\bdd\b.*\bof=/dev/(?:sd|nvme|hd|mmcblk|disk)",    # dd to a raw disk
    r">\s*/dev/(?:sd|nvme|hd|mmcblk|disk)",             # redirect onto raw disk
    r"\bchmod\s+-R\s+0*7*\s+/(?:\s|$)",                 # chmod -R on root
]


def _is_safe_command(cmd: str) -> bool:
    """Check if command contains destructive system deletion commands."""
    cmd_lower = cmd.lower().strip()
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, cmd_lower):
            return False
    return True


def _strip_exec_banner(out: str) -> str:
    """execute_terminal_command prefixes a '[Exit code: N | Time: Ns]' line.
    Strip it so composed fields (git branch/status/log) aren't polluted by the
    banner. Error strings (which don't carry the banner) are returned as-is."""
    out = out or ""
    if out.startswith("[Exit code:"):
        parts = out.split("\n", 1)
        return parts[1].strip() if len(parts) > 1 else ""
    return out.strip()


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
        return f"Error: Python code execution timed out after {t_sec} seconds."
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

    branch = _strip_exec_banner(branch_out) or "(unknown)"
    status = _strip_exec_banner(status_out) or "(clean — no uncommitted changes)"
    log = _strip_exec_banner(log_out)
    return f"Git Branch: {branch}\n\nModified Files:\n{status}\n\nRecent Commits:\n{log}"


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
            content = m.get("content") or ""
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

    # host/user may originate from user input or MAG memory and are interpolated
    # into a shell command line — reject anything with shell metacharacters to
    # close a command-injection hole (e.g. host = "x; rm -rf ~").
    _SAFE = re.compile(r"^[A-Za-z0-9_.\-]+$")
    if not host or not _SAFE.match(host):
        return f"Error: refusing to connect — server host '{host}' contains unsafe characters."
    if not user or not _SAFE.match(user):
        return f"Error: refusing to connect — SSH username '{user}' contains unsafe characters."

    # CMD's `title` builtin only exists on Windows; on POSIX it aborts the
    # `&&` chain before ssh ever runs. Branch on the host platform.
    if IS_WINDOWS:
        ssh_cmd = f"title Ubuntu Server ({user}@{host}) && ssh {user}@{host}"
    else:
        ssh_cmd = f"ssh {user}@{host}"
    logger.info(f"[TerminalTool] Launching SSH session...")

    try:
        ok, msg = open_terminal(ssh_cmd)
        time.sleep(1.8)

        if pyautogui and password:
            # Enter password into the open SSH terminal
            pyautogui.write(password, interval=0.03)
            time.sleep(0.3)
            pyautogui.press("enter")
            logger.info(f"[TerminalTool] Sent saved password to SSH terminal for {user}@{host}")

        if not ok:
            return f"Opened terminal: {msg}"
        # We launched ssh in a detached terminal and (optionally) typed the saved
        # password blind — we cannot confirm the handshake succeeded from here, so
        # don't claim the connection is established.
        typed = " and entered the saved password" if (pyautogui and password) else ""
        return (f"Launched a terminal running 'ssh {user}@{host}'{typed}. "
                f"Check the terminal window to confirm the connection.")
    except Exception as e:
        logger.error(f"[TerminalTool] SSH connection failed: {e}")
        return f"Failed to connect to SSH server: {e}"
