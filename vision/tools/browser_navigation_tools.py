"""
Browser & Web Navigation Tools for VISION AI OS.
Allows VISION to open websites, search YouTube/Google, and download files directly.
"""

import os
import re
import webbrowser
import urllib.parse
from pathlib import Path
from typing import Optional
from vision.tools.registry import tool
from vision.logger import logger
from vision.tools.file_tools import _resolve_user_path

try:
    import requests
except Exception:
    # requests drags in urllib3 / charset_normalizer (compiled speedups); a
    # broken/mismatched install can raise beyond ImportError at import time.
    requests = None

# A dotted token is only treated as a bare hostname when it looks like a real
# domain: dot-separated labels ending in an alphabetic TLD of 2+ letters
# (optionally followed by a port/path/query). This keeps things like "3.14" or
# "v2.0" out of the URL branch so they fall through to a web search instead.
_DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}(?:[:/?#].*)?$",
    re.IGNORECASE,
)

KNOWN_SITES_MAP = {
    "github": "https://github.com",
    "leetcode": "https://leetcode.com",
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "chatgpt": "https://chat.openai.com",
    "google": "https://www.google.com",
    "aditya": "https://aec.edu.in",
    "aditya college": "https://acet.ac.in",
    "whatsapp web": "https://web.whatsapp.com",
    "reddit": "https://reddit.com",
    "linkedin": "https://linkedin.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "netflix": "https://netflix.com",
    "spotify": "https://open.spotify.com",
}


@tool(name="open_website", description="Open a website in the default web browser by site name (e.g. GitHub, LeetCode, YouTube, Gmail, Aditya College) or full URL.")
def open_website(site_or_url: str) -> str:
    """Opens a website URL or named portal in the user's browser."""
    if not site_or_url:
        return "Error: Site name or URL is required."

    target = site_or_url.strip().lower()

    # 1. Check known shortcuts
    if target in KNOWN_SITES_MAP:
        url = KNOWN_SITES_MAP[target]
    elif target.startswith("http://") or target.startswith("https://"):
        url = site_or_url.strip()
    elif _DOMAIN_RE.match(target):
        url = f"https://{target}"
    else:
        # Fallback to Google Search
        url = f"https://www.google.com/search?q={urllib.parse.quote(site_or_url)}"

    logger.info(f"[BrowserTool] Opening website: '{url}'...")
    try:
        if "youtube" in target or "youtube.com" in url:
            from vision.tools.media_tools import _open_url_in_comet_or_browser
            used_comet = _open_url_in_comet_or_browser(url)
            browser_name = "Comet Browser" if used_comet else "your default browser"
            return f"Opened {url} in {browser_name}."

        # webbrowser.open() returns False when it can't locate/launch a browser
        # (e.g. a headless Linux host) — don't claim success unconditionally.
        if webbrowser.open(url):
            return f"Opened {url} in your web browser."
        return f"Could not open a browser for {url} (no usable browser found on this system)."
    except Exception as e:
        logger.error(f"[BrowserTool] Failed to open browser: {e}")
        return f"Failed to open website '{url}': {e}"


@tool(name="search_youtube_videos", description="Search YouTube for videos, tutorials, music, or topics and open the search results in Comet Browser.")
def search_youtube_videos(query: str) -> str:
    """Searches YouTube and plays the video in Comet browser."""
    if not query:
        return "Error: Search query is required."
    from vision.tools.media_tools import play_youtube_video
    return play_youtube_video(query=query)


@tool(name="search_google_web", description="Open a Google Search in the browser for any query, question, or research.")
def search_google_web(query: str) -> str:
    """Searches Google and opens the search page in browser."""
    if not query:
        return "Error: Search query is required."

    url = f"https://www.google.com/search?q={urllib.parse.quote(query.strip())}"
    logger.info(f"[BrowserTool] Searching Google: '{query}'")
    try:
        if webbrowser.open(url):
            return f"Opened Google search for '{query}'."
        return "Could not open a browser for the Google search (no usable browser found on this system)."
    except Exception as e:
        return f"Failed to open Google search: {e}"


@tool(name="download_file_from_url", description="Download a file, image, or document from a URL directly into Downloads or a specified folder.")
def download_file_from_url(url: str, destination_folder: str = "Downloads", file_name: Optional[str] = None) -> str:
    """Downloads a file over HTTP/HTTPS to local disk."""
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return "Error: A valid HTTP/HTTPS URL is required."

    dest_dir = _resolve_user_path(destination_folder, find_existing_file=False)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Determine file name. Strip any directory components so a crafted
    # file_name (or URL path) like "../../etc/passwd" or "C:\\Windows\\x"
    # can't escape the destination folder (path traversal).
    if file_name:
        fname = os.path.basename(file_name.replace("\\", "/")) or "downloaded_file.bin"
    else:
        parsed = urllib.parse.urlparse(url)
        fname = os.path.basename(parsed.path) or "downloaded_file.bin"

    out_path = dest_dir / fname
    logger.info(f"[BrowserTool] Downloading '{url}' -> '{out_path}'...")

    if requests is None:
        return "Error: the 'requests' package is not installed; file download is unavailable."

    try:
        with requests.get(url, stream=True, timeout=20) as resp:
            resp.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

        file_size_kb = round(out_path.stat().st_size / 1024, 1)
        logger.info(f"[BrowserTool] Downloaded '{fname}' ({file_size_kb} KB)")
        return f"Successfully downloaded '{fname}' ({file_size_kb} KB) to '{out_path}'."
    except Exception as e:
        logger.error(f"[BrowserTool] Download failed: {e}")
        return f"Failed to download file: {e}"
