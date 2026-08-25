"""
Media and YouTube Playback Automation Tools for VISION AI.
Provides intelligent YouTube searching, automatic playback via the Comet Browser / taskbar shortcuts,
and hotkey playback controls (full-screen, 10s/30s seek forwarding, rewinding, pause/play, volume).
"""

import os
import re
import time
import urllib.parse
import subprocess
import webbrowser
from pathlib import Path
from typing import Optional
from vision.tools.registry import tool
from vision.logger import logger

try:
    import pyautogui
except ImportError:
    pyautogui = None


def _get_comet_browser_path() -> Optional[str]:
    """Locate the Comet browser executable or taskbar shortcut on the system."""
    candidates = [
        r"C:\Program Files\Perplexity\Comet\Application\comet.exe",
        r"C:\Program Files (x86)\Perplexity\Comet\Application\comet.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Perplexity\Comet\Application\comet.exe"),
        os.path.expandvars(r"%APPDATA%\Microsoft\Internet Explorer\Quick Launch\Comet.lnk"),
        os.path.expandvars(r"%APPDATA%\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar\YouTube.lnk"),
        os.path.expandvars(r"%APPDATA%\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar\Comet.lnk"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def _open_url_in_comet_or_browser(url: str) -> bool:
    """Launch a URL preferentially in Comet browser, falling back to default web browser."""
    comet_path = _get_comet_browser_path()
    if comet_path:
        try:
            if comet_path.lower().endswith(".exe"):
                subprocess.Popen([comet_path, url])
                logger.info(f"[MediaTools] Launched URL in Comet Browser ({comet_path}): '{url}'")
                return True
            elif comet_path.lower().endswith(".lnk"):
                # Open shortcut or pass URL
                try:
                    subprocess.Popen([comet_path, url])
                    return True
                except Exception:
                    os.startfile(comet_path)
                    time.sleep(1.0)
                    webbrowser.open(url)
                    return True
        except Exception as e:
            logger.warning(f"[MediaTools] Could not launch Comet executable directly ({e}), falling back to webbrowser.")

    # Fallback to default system browser
    webbrowser.open(url)
    logger.info(f"[MediaTools] Opened URL in default browser: '{url}'")
    return False


def _extract_top_youtube_video_id(query: str) -> Optional[str]:
    """Scrape YouTube search results HTML to extract the top video ID for direct autoplay."""
    try:
        import urllib.request
        encoded = urllib.parse.quote(query)
        search_url = f"https://www.youtube.com/results?search_query={encoded}"
        req = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            vids = re.findall(r'/watch\?v=([a-zA-Z0-9_-]{11})', html)
            if vids:
                return vids[0]
    except Exception as e:
        logger.debug(f"[MediaTools] Top YouTube video extraction note: {e}")
    return None


@tool(
    name="play_youtube_video",
    description="Search and play a video, song, music track, or tutorial on YouTube using the Comet Browser. Automatically resolves top video and launches direct autoplay playback."
)
def play_youtube_video(query: str, fullscreen: bool = False) -> str:
    """
    Searches YouTube and launches playback directly in Comet Browser.
    """
    if not query or not query.strip():
        return "Error: Please specify what song, video, or topic to play on YouTube."

    clean_query = query.strip()
    if clean_query.lower() in ("youtube", "open youtube", "home", "homepage"):
        play_url = "https://www.youtube.com"
    else:
        top_vid = _extract_top_youtube_video_id(clean_query)
        if top_vid:
            play_url = f"https://www.youtube.com/watch?v={top_vid}&autoplay=1"
            logger.info(f"[MediaTools] Found top video ID '{top_vid}' -> playing '{play_url}' directly in Comet Browser.")
        else:
            encoded = urllib.parse.quote(clean_query)
            play_url = f"https://www.youtube.com/results?search_query={encoded}"

    _open_url_in_comet_or_browser(play_url)

    # If full screen is requested immediately upon playback
    if fullscreen and pyautogui:
        time.sleep(2.5)
        pyautogui.press("f")
        logger.info("[MediaTools] Toggled YouTube full-screen on launch.")

    return f"Opened YouTube in Comet Browser and playing '{clean_query}'."


@tool(
    name="play_media",
    description="Search and play a video or music track on YouTube / Comet Browser."
)
def play_media(query: str) -> str:
    """Alias for play_youtube_video."""
    return play_youtube_video(query=query, fullscreen=False)


@tool(
    name="control_youtube_playback",
    description="Control active YouTube video playback: 'fullscreen', 'forward', 'rewind', 'pause', 'play', 'mute', 'unmute', 'next', 'speed_up', 'slow_down'. Supports custom seek duration (e.g. seconds=10 or seconds=30)."
)
def control_youtube_playback(action: str, seconds: int = 10) -> str:
    """
    Send hotkey media controls to the active YouTube player window.
    YouTube shortcuts:
    - 'f': Fullscreen toggle
    - 'l': Seek forward 10s (presses = seconds // 10)
    - 'j': Seek backward 10s (presses = seconds // 10)
    - 'k' or 'space': Play/Pause toggle
    - 'm': Mute/Unmute toggle
    - 'Shift+N': Next video
    - '>' (Shift+.): Speed up
    - '<' (Shift+,): Slow down
    - 'c': Subtitles/Captions
    """
    act = action.strip().lower()

    if not pyautogui:
        return f"Control action '{act}' noted (pyautogui not available in this environment)."

    # 1. Full Screen
    if act in ("fullscreen", "full_screen", "full screen", "maximize_video", "toggle_fullscreen"):
        pyautogui.press("f")
        logger.info("[MediaTools] YouTube action: Toggled Fullscreen ('f')")
        return "Set YouTube video to full screen."

    # 2. Seek Forward (10s, 30s, etc.)
    elif act in ("forward", "seek_forward", "skip_forward", "fast_forward"):
        presses = max(1, int(seconds) // 10)
        for _ in range(presses):
            pyautogui.press("l")
            time.sleep(0.05)
        actual_secs = presses * 10
        logger.info(f"[MediaTools] YouTube action: Forwarded {actual_secs}s ({presses} presses of 'l')")
        return f"Forwarded YouTube video by {actual_secs} seconds."

    # 3. Seek Backward / Rewind (10s, 30s, etc.)
    elif act in ("rewind", "seek_backward", "skip_backward", "backward", "back"):
        presses = max(1, int(seconds) // 10)
        for _ in range(presses):
            pyautogui.press("j")
            time.sleep(0.05)
        actual_secs = presses * 10
        logger.info(f"[MediaTools] YouTube action: Rewound {actual_secs}s ({presses} presses of 'j')")
        return f"Rewound YouTube video by {actual_secs} seconds."

    # 4. Play / Pause
    elif act in ("pause", "play", "toggle_play", "resume", "stop"):
        pyautogui.press("k")
        logger.info("[MediaTools] YouTube action: Toggled Play/Pause ('k')")
        return "Toggled play/pause on YouTube."

    # 5. Mute / Unmute
    elif act in ("mute", "unmute", "toggle_mute"):
        pyautogui.press("m")
        logger.info("[MediaTools] YouTube action: Toggled Mute ('m')")
        return "Toggled audio mute on YouTube."

    # 6. Next Video
    elif act in ("next", "next_video", "skip"):
        pyautogui.hotkey("shift", "n")
        logger.info("[MediaTools] YouTube action: Skipped to next video ('Shift+N')")
        return "Skipped to next video on YouTube."

    # 7. Speed Up / Slow Down
    elif act in ("speed_up", "faster"):
        pyautogui.hotkey("shift", ".")
        return "Increased playback speed."
    elif act in ("slow_down", "slower"):
        pyautogui.hotkey("shift", ",")
        return "Decreased playback speed."

    # 8. Subtitles
    elif act in ("subtitles", "captions", "cc"):
        pyautogui.press("c")
        return "Toggled subtitles on YouTube."

    # 9. Volume Up / Down
    elif act in ("volume_up", "louder"):
        for _ in range(3):
            pyautogui.press("up")
        return "Turned up YouTube volume."
    elif act in ("volume_down", "quieter"):
        for _ in range(3):
            pyautogui.press("down")
        return "Turned down YouTube volume."

    else:
        # Default fallback keypress
        pyautogui.press("k")
        return f"Executed YouTube playback command: {action}."


@tool(
    name="set_youtube_fullscreen",
    description="Toggle full-screen mode on the active YouTube video player."
)
def set_youtube_fullscreen() -> str:
    """Toggles full-screen mode on YouTube."""
    return control_youtube_playback(action="fullscreen")


@tool(
    name="seek_youtube_video",
    description="Seek forward or rewind backward on the current YouTube video by a specific number of seconds (e.g. 10s, 30s, 60s)."
)
def seek_youtube_video(direction: str = "forward", seconds: int = 10) -> str:
    """Seeks the video forward or backward by N seconds."""
    act = "forward" if "forw" in direction.lower() or "ahead" in direction.lower() else "rewind"
    return control_youtube_playback(action=act, seconds=seconds)
