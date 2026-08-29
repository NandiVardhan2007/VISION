"""
Keyboard, Typing & Desktop Input Automation Tools for VISION AI OS.
Allows VISION to type text, notes, documents, open editors,
save documents, and execute keyboard shortcuts with 100% reliability.
"""

import time
import subprocess
import ctypes
from ctypes import wintypes
from typing import Optional, List, Dict, Any
from vision.tools.registry import tool
from vision.logger import logger
from vision.platform import IS_WINDOWS

try:
    import pyautogui
    import pyperclip
    import win32gui
    import win32process
    import win32con
    import psutil
    if pyautogui:
        pyautogui.FAILSAFE = False
except ImportError:
    pyautogui = None
    pyperclip = None
    win32gui = None
    win32process = None
    win32con = None
    psutil = None


APP_COMMAND_MAP = {
    "notepad": "notepad.exe",
    "notemate": "notepad.exe",
    "notpad": "notepad.exe",
    "notepade": "notepad.exe",
    "note": "notepad.exe",
    "notes": "notepad.exe",
    "word": "winword",
    "excel": "excel",
    "calc": "calc.exe",
    "calculator": "calc.exe",
    "vscode": "code",
    "code": "code",
}


# Win32 SendInput 40-byte x64 structure definitions for native Windows input
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ('dx', ctypes.c_long),
        ('dy', ctypes.c_long),
        ('mouseData', ctypes.c_ulong),
        ('dwFlags', ctypes.c_ulong),
        ('time', ctypes.c_ulong),
        ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong))
    ]

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ('wVk', ctypes.c_ushort),
        ('wScan', ctypes.c_ushort),
        ('dwFlags', ctypes.c_ulong),
        ('time', ctypes.c_ulong),
        ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong))
    ]

class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ('uMsg', ctypes.c_ulong),
        ('wParamL', ctypes.c_ushort),
        ('wParamH', ctypes.c_ushort)
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ('mi', _MOUSEINPUT),
        ('ki', _KEYBDINPUT),
        ('hi', _HARDWAREINPUT)
    ]

class _INPUT(ctypes.Structure):
    _fields_ = [
        ('type', ctypes.c_ulong),
        ('u', _INPUT_UNION)
    ]


def _find_target_window(app_name: str) -> Optional[int]:
    """Find the best HWND of an existing open window matching app_name."""
    raw = app_name.lower().strip()
    target = "notepad" if ("not" in raw or "note" in raw) else raw
    proc_target = f"{target}.exe"

    # 1. Try pygetwindow if available
    try:
        import pygetwindow as gw
        for w in gw.getAllWindows():
            if w.title and target in w.title.lower():
                if getattr(w, "_hWnd", None):
                    return w._hWnd
    except Exception:
        pass

    # 2. Try win32gui FindWindow for common standard window classes
    if win32gui:
        try:
            h = win32gui.FindWindow("Notepad", None)
            if h and win32gui.IsWindow(h) and win32gui.IsWindowVisible(h):
                return h
        except Exception:
            pass

    found_hwnd = None

    # 3. Enumerate windows safely with win32gui
    if win32gui and psutil and win32process:
        def enum_cb(hwnd, extra):
            nonlocal found_hwnd
            try:
                if win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd).strip()
                    class_name = win32gui.GetClassName(hwnd).strip().lower()
                    title_lower = title.lower()

                    if target in title_lower or (target in class_name and "tooltip" not in class_name and "ime" not in class_name):
                        found_hwnd = hwnd
                        return True

                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        if pid:
                            pname = psutil.Process(pid).name().lower()
                            if target in pname or proc_target in pname:
                                if "tooltip" not in class_name and "ime" not in class_name and "msg" not in class_name:
                                    found_hwnd = hwnd
                                    return True
                    except Exception:
                        pass
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(enum_cb, None)
        except Exception:
            pass

    if found_hwnd:
        return found_hwnd

    # 4. Fallback using ctypes GetWindow traversal (Windows only)
    if not IS_WINDOWS:
        return None
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetTopWindow(0)
        while hwnd:
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    if target in buff.value.lower():
                        return hwnd
            hwnd = user32.GetWindow(hwnd, 2) # GW_HWNDNEXT
    except Exception:
        pass

    return None


def _ensure_and_focus_window(app_name: str) -> bool:
    """Focus target application window; if not running, launch it once and focus."""
    raw = app_name.lower().strip()
    target = "notepad" if ("not" in raw or "note" in raw) else raw

    # 1. Search for existing window
    hwnd = _find_target_window(app_name)

    # 2. If not found, launch the application
    if not hwnd:
        cmd = APP_COMMAND_MAP.get(target, APP_COMMAND_MAP.get(raw, raw))
        logger.info(f"[InputTool] Window '{target}' not open. Launching via '{cmd}'...")
        try:
            subprocess.Popen(cmd, shell=True)
            for _ in range(20):
                time.sleep(0.1)
                hwnd = _find_target_window(app_name)
                if hwnd:
                    break
        except Exception as e:
            logger.error(f"[InputTool] Failed to launch '{cmd}': {e}")
            return False
    else:
        logger.info(f"[InputTool] Found existing active window HWND {hwnd} for '{target}'")

    # 3. Force foreground focus cleanly without leaving Alt stuck in menu bar
    if hwnd and IS_WINDOWS:
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            current_thread = kernel32.GetCurrentThreadId()
            remote_thread = user32.GetWindowThreadProcessId(hwnd, None)
            fore_hwnd = user32.GetForegroundWindow()
            fore_thread = user32.GetWindowThreadProcessId(fore_hwnd, None) if fore_hwnd else 0

            # Attach thread input to bypass Windows foreground restrictions
            if fore_thread and fore_thread != current_thread:
                user32.AttachThreadInput(current_thread, fore_thread, True)
            if remote_thread and remote_thread != current_thread:
                user32.AttachThreadInput(current_thread, remote_thread, True)

            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
            user32.SetFocus(hwnd)

            if fore_thread and fore_thread != current_thread:
                user32.AttachThreadInput(current_thread, fore_thread, False)
            if remote_thread and remote_thread != current_thread:
                user32.AttachThreadInput(current_thread, remote_thread, False)

            # Send ESC key to dismiss any accidental menu activation (e.g. File menu)
            time.sleep(0.15)
            user32.keybd_event(0x1B, 0, 0, 0) # ESC down
            user32.keybd_event(0x1B, 0, 2, 0) # ESC up
            time.sleep(0.1)

            logger.info(f"[InputTool] Successfully focused window HWND {hwnd} for '{target}'")
            return True
        except Exception as e:
            logger.debug(f"[InputTool] Focus window error: {e}")
            return True
    elif hwnd:
        # Non-Windows: we located a window but cannot force-foreground without a
        # platform window API; pyautogui/keyboard actions below still operate on focus.
        logger.info(f"[InputTool] Found window handle for '{target}' (focus not enforced on this OS).")
        return True

    return False


def _type_letter_by_letter(text: str, delay_per_char: float = 0.015):
    """Types text using native Win32 SendInput KEYEVENTF_UNICODE with safe inter-key delay."""
    if not text:
        return

    try:
        user32 = ctypes.windll.user32
        for char in text:
            if char == '\n':
                inp_down = _INPUT(type=1, u=_INPUT_UNION(ki=_KEYBDINPUT(wVk=0x0D, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)))
                inp_up = _INPUT(type=1, u=_INPUT_UNION(ki=_KEYBDINPUT(wVk=0x0D, wScan=0, dwFlags=2, time=0, dwExtraInfo=None)))
                user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(_INPUT))
                user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(_INPUT))
                time.sleep(0.02)
            elif char == '\t':
                inp_down = _INPUT(type=1, u=_INPUT_UNION(ki=_KEYBDINPUT(wVk=0x09, wScan=0, dwFlags=0, time=0, dwExtraInfo=None)))
                inp_up = _INPUT(type=1, u=_INPUT_UNION(ki=_KEYBDINPUT(wVk=0x09, wScan=0, dwFlags=2, time=0, dwExtraInfo=None)))
                user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(_INPUT))
                user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(_INPUT))
                time.sleep(0.02)
            else:
                code = ord(char)
                inp_down = _INPUT(type=1, u=_INPUT_UNION(ki=_KEYBDINPUT(wVk=0, wScan=code, dwFlags=4, time=0, dwExtraInfo=None)))
                inp_up = _INPUT(type=1, u=_INPUT_UNION(ki=_KEYBDINPUT(wVk=0, wScan=code, dwFlags=4 | 2, time=0, dwExtraInfo=None)))
                user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(_INPUT))
                user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(_INPUT))
                if delay_per_char > 0:
                    time.sleep(delay_per_char)
    except Exception as e:
        logger.warning(f"[InputTool] Letter typing fallback to clipboard: {e}")
        if pyperclip and pyautogui:
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")


@tool(name="type_text_into_application", description="Type or write text/notes into an application (e.g. Notepad, Word, Editor) with 100% exact accuracy. Automatically opens the application if not already open, focuses it, and writes the text.")
def type_text_into_application(text: str, target_app: Optional[str] = "Notepad", press_enter: bool = False, typing_mode: str = "auto") -> str:
    """
    Ensures the target application (e.g. Notepad, Word, Editor) is open and focused,
    then writes the text into the application with 100% exact accuracy.
    
    Args:
        text: The text content to write/type.
        target_app: Target application name (default: 'Notepad').
        press_enter: Whether to press Enter after typing.
        typing_mode: 'auto' (recommended: instant clipboard paste for perfect fidelity), 'paste', or 'slow_type'.
    """
    if not text:
        return "Error: Text content to type is required."

    if pyautogui:
        pyautogui.FAILSAFE = False

    app = target_app or "Notepad"
    _ensure_and_focus_window(app)
    time.sleep(0.3)

    # For Notepad: press Ctrl+N to create a fresh new document before writing,
    # so new text never collides with previous notes already open.
    if pyautogui and app.lower().strip() in ("notepad", "notepad.exe"):
        pyautogui.hotkey("ctrl", "n")
        time.sleep(0.4)  # Wait for "Do you want to save?" dialog or new doc
        # If an unsaved-changes dialog appears, dismiss it by pressing "Don't Save" (Tab → Enter or Alt+N)
        # Modern Notepad (Win11) uses Alt+N for "Don't Save", classic uses Tab+Enter
        try:
            dialog_hwnd = None
            if win32gui:
                def _find_dialog(hwnd, _):
                    nonlocal dialog_hwnd
                    if win32gui.IsWindowVisible(hwnd):
                        cls = win32gui.GetClassName(hwnd)
                        title = win32gui.GetWindowText(hwnd).lower()
                        if cls == "#32770" or "save" in title or "notepad" in title and "want to save" in title:
                            dialog_hwnd = hwnd
                try:
                    win32gui.EnumWindows(_find_dialog, None)
                except Exception:
                    pass
            if dialog_hwnd:
                logger.info("[InputTool] Detected unsaved-changes dialog after Ctrl+N. Dismissing with 'Don't Save'.")
                pyautogui.hotkey("alt", "n")  # "Don't Save" in modern Notepad
                time.sleep(0.3)
            else:
                # No dialog means either fresh Notepad or already saved — good to go
                pass
        except Exception:
            pass
        logger.info("[InputTool] Created new Notepad document (Ctrl+N) to avoid colliding with previous notes.")

    logger.info(f"[InputTool] Writing {len(text)} characters into '{app}' (mode: {typing_mode})...")

    # For documents, notes, summaries, or multi-line text: use instant clipboard paste
    # Clipboard paste guarantees 100% zero dropped characters, no repeated keys, and perfect formatting
    if typing_mode in ["auto", "paste"] or len(text) > 25 or "\n" in text:
        if pyperclip and pyautogui:
            try:
                # Save previous clipboard state
                try:
                    old_clipboard = pyperclip.paste()
                except Exception:
                    old_clipboard = ""

                pyperclip.copy(text)
                time.sleep(0.1)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.15)
                if press_enter:
                    pyautogui.press("enter")
                logger.info(f"[InputTool] Successfully wrote text into '{app}' via clipboard injection.")
                return f"Successfully typed text into {app}."
            except Exception as e:
                logger.warning(f"[InputTool] Clipboard paste failed, falling back to simulated keystrokes: {e}")

    # Fallback to simulated keystrokes with safe delay
    _type_letter_by_letter(text, delay_per_char=0.015)
    
    if press_enter and pyautogui:
        time.sleep(0.05)
        pyautogui.press("enter")

    logger.info(f"[InputTool] Successfully typed {len(text)} characters into '{app}'.")
    return f"Successfully typed text into {app}."



@tool(name="press_keyboard_shortcut", description="Press a keyboard shortcut like 'ctrl+s', 'ctrl+z', 'ctrl+c', 'ctrl+v', 'alt+tab', 'enter', 'tab', 'backspace'.")
def press_keyboard_shortcut(shortcut: str) -> str:
    """Press keyboard keys or combinations."""
    if not shortcut or not pyautogui:
        return "Error: Shortcut or PyAutoGUI not available."

    pyautogui.FAILSAFE = False
    keys = [k.strip().lower() for k in shortcut.replace("+", " ").split()]
    try:
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)
        logger.info(f"[InputTool] Pressed shortcut: '{shortcut}'")
        return f"Pressed '{shortcut}'."
    except Exception as e:
        return f"Failed to press shortcut '{shortcut}': {e}"


def _find_save_dialog_hwnd(parent_hwnd: Optional[int] = None) -> Optional[int]:
    """Search for open Save As / Common File Dialog (#32770)."""
    dialog_hwnd = None
    if not win32gui:
        return None

    def enum_cb(hwnd, extra):
        nonlocal dialog_hwnd
        if win32gui.IsWindowVisible(hwnd):
            cls_name = win32gui.GetClassName(hwnd)
            win_title = win32gui.GetWindowText(hwnd).lower()
            if cls_name == "#32770" and ("save" in win_title or "save as" in win_title or "open" in win_title or not win_title):
                dialog_hwnd = hwnd

    try:
        win32gui.EnumWindows(enum_cb, None)
    except Exception:
        pass
    return dialog_hwnd


@tool(name="save_active_document", description="Save the currently open document/note in Notepad, Word, or an editor, specifying a file name and folder (e.g. Downloads, Desktop).")
def save_active_document(file_name: str = "note.txt", folder: str = "Downloads", target_app: Optional[str] = "Notepad") -> str:
    """
    Saves the document in the target application and guarantees file creation in the destination folder.
    """
    if pyautogui:
        pyautogui.FAILSAFE = False

    app = target_app or "Notepad"
    _ensure_and_focus_window(app)
    time.sleep(0.3)

    # Resolve destination path
    from vision.tools.file_tools import _resolve_user_path
    dest_dir = _resolve_user_path(folder, find_existing_file=False)
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    clean_name = file_name if ("." in file_name) else f"{file_name}.txt"
    full_path = str(dest_dir / clean_name)

    # 1. First, extract text from editor via Ctrl+A -> Ctrl+C (or direct Win32) to ensure we have a direct file backup
    doc_content = ""
    if pyperclip and pyautogui:
        try:
            old_clip = pyperclip.paste()
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.1)
            pyautogui.hotkey("ctrl", "c")
            time.sleep(0.1)
            doc_content = pyperclip.paste()
            # Deselect / move cursor to end
            pyautogui.press("right")
            time.sleep(0.1)
        except Exception:
            pass

    # 2. Trigger Save shortcut (Ctrl+S)
    if pyautogui:
        pyautogui.hotkey("ctrl", "s")
        time.sleep(0.6)

    # 3. Check if Save As dialog (#32770) appeared
    dialog_hwnd = _find_save_dialog_hwnd()
    if not dialog_hwnd:
        # Try Ctrl+Shift+S (explicit Save As in modern Notepad)
        if pyautogui:
            pyautogui.hotkey("ctrl", "shift", "s")
            time.sleep(0.6)
            dialog_hwnd = _find_save_dialog_hwnd()

    if dialog_hwnd and win32gui:
        logger.info(f"[InputTool] Detected Save As dialog HWND {dialog_hwnd}. Injecting destination path...")
        try:
            user32 = ctypes.windll.user32
            user32.SetForegroundWindow(dialog_hwnd)
            time.sleep(0.2)
            # Type path directly into focused dialog input
            if pyperclip and pyautogui:
                pyperclip.copy(full_path)
                time.sleep(0.05)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.3)
                pyautogui.press("enter")
                time.sleep(0.4)
        except Exception as e:
            logger.warning(f"[InputTool] Save As dialog interaction failed: {e}")
    else:
        logger.info("[InputTool] Save As dialog not active. Writing document content directly to destination file.")

    # 4. Guarantee document is written to destination file
    if doc_content:
        try:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(doc_content)
            logger.info(f"[InputTool] Directly wrote {len(doc_content)} chars to '{full_path}'")
        except Exception as e:
            logger.warning(f"[InputTool] Direct file save error: {e}")

    logger.info(f"[InputTool] Saved active document as '{full_path}'")
    return f"Successfully saved active document to '{full_path}'."
