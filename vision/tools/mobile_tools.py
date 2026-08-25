"""
Android Mobile Control automation tools via wireless ADB.
"""

import subprocess
from vision.tools.registry import tool
from vision.config import config
from vision.logger import logger


def _run_adb_cmd(cmd: str, timeout: int = 10) -> str:
    full_cmd = f"{config.ADB_PATH} -s {config.VISION_PHONE_IP}:{config.VISION_PHONE_PORT} {cmd}"
    try:
        res = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=timeout)
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
    cmd = f"{config.ADB_PATH} connect {config.VISION_PHONE_IP}:{config.VISION_PHONE_PORT}"
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
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
    _run_adb_cmd("shell input keyevent 26")
    _run_adb_cmd("shell input swipe 500 1500 500 500 300")
    return "Sent unlock sequence to mobile device."


@tool(name="launch_mobile_app", description="Launch an app package on the Android phone.")
def launch_mobile_app(package_name: str) -> str:
    """Launch app on phone."""
    return _run_adb_cmd(f"shell monkey -p {package_name} -c android.intent.category.LAUNCHER 1")


@tool(name="tap_phone_screen", description="Tap specific (x, y) coordinates on the Android phone screen.")
def tap_phone_screen(x: int, y: int) -> str:
    """Tap coordinates on mobile screen."""
    return _run_adb_cmd(f"shell input tap {x} {y}")
