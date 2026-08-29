"""
Test suite for Terminal and Developer Execution Tools.
"""

from vision.tools.terminal_tools import execute_terminal_command, run_python_code, git_status_and_summary, connect_to_ssh_server, _is_safe_command
from vision.tools.registry import tool_registry


def test_terminal_tools_registered():
    assert "execute_terminal_command" in tool_registry._tools
    assert "run_python_code" in tool_registry._tools
    assert "git_status_and_summary" in tool_registry._tools
    assert "connect_to_ssh_server" in tool_registry._tools


def test_command_execution():
    # Use a shell-agnostic command: echo works in both PowerShell (Windows) and
    # the default POSIX shell (Linux/macOS).
    res = execute_terminal_command("echo 'Hello VISION Developer'", timeout_seconds="30")
    assert "Hello VISION Developer" in res
    assert "Exit code: 0" in res


def test_python_code_execution():
    res = run_python_code("print(10 + 25)", timeout_seconds="20")
    assert "35" in res
    assert "Exit code: 0" in res


def test_safety_filter():
    assert _is_safe_command("dir") is True
    assert _is_safe_command("format c:") is False
    assert _is_safe_command("rmdir /s /q c:\\windows") is False
