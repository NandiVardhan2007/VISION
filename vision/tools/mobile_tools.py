"""
Android Mobile Control automation tools via wireless ADB.
"""

import re
import shlex
import subprocess
from vision.tools.registry import tool
from vision.config import config
from vision.logger import logger


def _adb_base() -> list:
    """ADB executable + device selector as an argv list (handles spaced paths)."""
    return [config.ADB_PATH, "-s", f"{config.VISION_PHONE_IP}:{config.VISION_PHONE_PORT}"]


def _run_adb_cmd(cmd: str, timeout: int = 10) -> str:
    # Use argv list form (shell=False): a shell=True f-string breaks when
    # ADB_PATH contains spaces (e.g. 'C:\\Program Files\\platform-tools\\adb.exe')
    # and is an injection risk. shlex.split keeps multi-word text arguments intact.
    full_cmd = _adb_base() + shlex.split(cmd, posix=False)
    try:
        res = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
        if res.returncode != 0 and not res.stdout.strip():
            err = (res.stderr or "").strip()
            return f"ADB Error (exit {res.returncode}): {err[:200]}" if err else f"ADB Error (exit {res.returncode})"
        return res.stdout.strip() or "Success"
    except FileNotFoundError:
        logger.error(f"[MobileTool] ADB binary not found at '{config.ADB_PATH}'. Set ADB_PATH in .env.")
        return f"Error: ADB not found at '{config.ADB_PATH}'. Install platform-tools or set ADB_PATH."
    except subprocess.TimeoutExpired:
        return f"ADB Error: command timed out after {timeout}s"
    except Exception as e:
        return f"ADB Error: {e}"


@tool(name="connect_phone", description="Connect to the wireless Android phone via ADB.")
def connect_phone() -> str:
    """Connect to phone ADB over Wi-Fi."""
    cmd = [config.ADB_PATH, "connect", f"{config.VISION_PHONE_IP}:{config.VISION_PHONE_PORT}"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        out = (res.stdout or "").strip()
        if "connected" in out.lower():
            return out
        err = (res.stderr or "").strip()
        return out or err or "No response from device (is wireless debugging on?)"
    except FileNotFoundError:
        logger.error(f"[MobileTool] ADB binary not found at '{config.ADB_PATH}'. Set ADB_PATH in .env.")
        return f"Error: ADB not found at '{config.ADB_PATH}'. Install platform-tools or set ADB_PATH."
    except Exception as e:
        return f"ADB Error: {e}"


@tool(name="unlock_phone", description="Wake up and unlock the connected Android phone.")
def unlock_phone() -> str:
    """Wake screen and enter unlock pattern/swipe."""
    # KEYCODE_WAKEUP (224) only ever turns the screen ON. keyevent 26 is
    # KEYCODE_POWER, which TOGGLES — so if the screen was already awake it would
    # switch it off. Surface ADB failures instead of always claiming success.
    wake = _run_adb_cmd("shell input keyevent 224")
    if wake.startswith("Error") or wake.startswith("ADB Error"):
        return f"Failed to wake phone: {wake}"
    swipe = _run_adb_cmd("shell input swipe 500 1500 500 500 300")
    if swipe.startswith("Error") or swipe.startswith("ADB Error"):
        return f"Woke phone but unlock swipe failed: {swipe}"
    return "Sent unlock sequence to mobile device."


@tool(name="launch_mobile_app", description="Launch an app package on the Android phone.")
def launch_mobile_app(package_name: str) -> str:
    """Launch app on phone."""
    # Host-side is argv-safe, but `adb shell` re-joins the tokens and runs them
    # in the PHONE's shell, so metacharacters in package_name (e.g.
    # "com.x; reboot") would execute on the device. Restrict to valid package
    # characters before sending.
    if not package_name or not re.match(r'^[A-Za-z0-9._]+$', package_name):
        return f"Error: invalid package name {package_name!r}."
    return _run_adb_cmd(f"shell monkey -p {package_name} -c android.intent.category.LAUNCHER 1")


@tool(name="tap_phone_screen", description="Tap specific (x, y) coordinates on the Android phone screen.")
def tap_phone_screen(x: int, y: int) -> str:
    """Tap coordinates on mobile screen."""
    # Coerce to int: the LLM often passes coordinates as strings, and feeding a
    # non-numeric/negative value straight into the `input tap` command line would
    # either error obscurely or inject an extra token. Validate before sending.
    try:
        xi, yi = int(x), int(y)
    except (TypeError, ValueError):
        return f"Error: tap coordinates must be integers, got x={x!r}, y={y!r}."
    if xi < 0 or yi < 0:
        return f"Error: tap coordinates must be non-negative, got ({xi}, {yi})."
    return _run_adb_cmd(f"shell input tap {xi} {yi}")
