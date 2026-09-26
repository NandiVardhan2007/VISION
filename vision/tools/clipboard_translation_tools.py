"""
Smart Clipboard & Live Language Translation Tools for VISION AI OS.
Allows VISION to read/write clipboard contents and translate text across languages (Telugu, Hindi, English, etc.).
"""

import urllib.parse
from typing import Optional
from vision.tools.registry import tool
from vision.logger import logger

try:
    import requests
except Exception:
    # A partially-installed requests (broken urllib3/charset_normalizer) can
    # raise beyond ImportError at import time; don't let that kill this module.
    requests = None

try:
    import pyperclip
except Exception:
    pyperclip = None


LANGUAGE_CODE_MAP = {
    "telugu": "te",
    "hindi": "hi",
    "english": "en",
    "tamil": "ta",
    "kannada": "kn",
    "malayalam": "ml",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "japanese": "ja",
    "chinese": "zh",
    "arabic": "ar",
    "russian": "ru",
    "bengali": "bn",
    "marathi": "mr",
}


@tool(name="read_clipboard", description="Read and return the text currently copied to the system clipboard.")
def read_clipboard() -> str:
    """Read current text from the clipboard."""
    if not pyperclip:
        return "Error: Pyperclip module not available."

    try:
        content = pyperclip.paste()
        if not content or not content.strip():
            return "The clipboard is currently empty."
        logger.info(f"[ClipboardTool] Read {len(content)} chars from clipboard.")
        return f"Clipboard Content:\n{content.strip()}"
    except Exception as e:
        logger.error(f"[ClipboardTool] Failed to read clipboard: {e}")
        return f"Error reading clipboard: {e}"


@tool(name="write_to_clipboard", description="Copy text to the system clipboard.")
def write_to_clipboard(text: str) -> str:
    """Copy text into clipboard."""
    if not pyperclip:
        return "Error: Pyperclip module not available."

    if not text:
        return "Error: Text to copy cannot be empty."

    try:
        pyperclip.copy(text)
        logger.info(f"[ClipboardTool] Copied {len(text)} characters to clipboard.")
        return f"Successfully copied to clipboard: '{text[:80]}...'" if len(text) > 80 else f"Successfully copied to clipboard: '{text}'"
    except Exception as e:
        logger.error(f"[ClipboardTool] Failed to write clipboard: {e}")
        return f"Error writing to clipboard: {e}"


@tool(name="translate_text", description="Translate text into another language like Telugu, Hindi, English, Tamil, Spanish, French, etc.")
def translate_text(text: str, target_language: str = "Telugu") -> str:
    """
    Translates text to the target language (e.g. Telugu, Hindi, English) using fast Google Translate API.
    """
    if not text or not text.strip():
        return "Error: Text to translate is required."

    target_lang_clean = target_language.lower().strip()
    target_code = LANGUAGE_CODE_MAP.get(target_lang_clean, target_lang_clean)

    logger.info(f"[TranslationTool] Translating text to '{target_language}' ({target_code})...")

    if requests is None:
        return "Error: the 'requests' package is not installed; translation is unavailable."

    # Google Translate web endpoint (single request, no fallback chain).
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_code}&dt=t&q={urllib.parse.quote(text)}"
        resp = requests.get(url, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            translated_segments = [item[0] for item in data[0] if item and item[0]]
            translated_text = "".join(translated_segments)
            logger.info(f"[TranslationTool] Translation successful: '{translated_text[:60]}...'")
            return f"Translated to {target_language.title()}:\n{translated_text}"
        logger.warning(f"[TranslationTool] Translator returned HTTP {resp.status_code} for '{target_code}'.")
    except Exception as e:
        logger.warning(f"[TranslationTool] Translator request failed: {e}")

    return f"Unable to complete translation at this time for '{text}'."
