"""
WhatsApp & Instant Messaging Automation Tools for VISION AI OS.
Supports interactive voice message drafting with confirmation, automatic contact & phone resolution
from MAG memory, quick reply templates, direct phone URI dispatching, and fallback search automation.
"""

import time
import urllib.parse
import re
from typing import Optional, Dict, Any, List
from vision.tools.registry import tool
from vision.memory.mag_engine import mag_engine
from vision.logger import logger
from vision.platform import launch_target, open_url

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.1
except Exception:
    # pyautogui can raise more than ImportError at import time on a headless /
    # no-DISPLAY host — don't let that crash the whole module.
    pyautogui = None
try:
    import pyperclip
except Exception:
    pyperclip = None
try:
    import pygetwindow as gw
except Exception:
    # pygetwindow raises NotImplementedError (not ImportError) on Linux with no
    # backend; a bare `except ImportError` would let it kill module import.
    gw = None


# In-memory storage for pending unconfirmed WhatsApp message drafts
_PENDING_WHATSAPP_DRAFT: Optional[Dict[str, str]] = None


QUICK_WHATSAPP_TEMPLATES = {
    "leaving_college": "I am starting from college now, will reach home in a bit.",
    "in_class": "I am in class right now, will call you back as soon as it's over.",
    "dsa_training": "Currently in THUB Placement / DSA training session, will get back to you shortly.",
    "reaching_soon": "On the way, reaching in about 15-20 minutes.",
    "need_notes": "Hey, could you please share today's class notes / assignment details?",
    "running_late": "Running slightly late due to traffic, will reach soon.",
}


def _record_whatsapp_event(description: str, msg: str) -> None:
    """Best-effort episodic logging of a sent message; never fails the send."""
    try:
        mag_engine.record_event(
            event_type="whatsapp_message_sent",
            description=description,
            metadata=f"Message: {msg[:100]}"
        )
    except Exception as e:
        logger.debug(f"[WhatsAppTool] Event record note: {e}")


def _focus_whatsapp_window() -> bool:
    """Find and activate an open WhatsApp window if present."""
    if not gw:
        return False
    try:
        windows = gw.getWindowsWithTitle("WhatsApp")
        if windows:
            win = windows[0]
            if win.isMinimized:
                win.restore()
            win.activate()
            time.sleep(0.6)
            return True
    except Exception as e:
        logger.debug(f"[WhatsAppTool] Window activation note: {e}")
    return False


def _resolve_contact_from_memory(target: str) -> str:
    """
    Check MAG memory for any stored phone numbers or exact contact aliases.
    If a phone number is found, returns the clean digits.
    """
    clean_target = target.strip()
    if not clean_target:
        return clean_target

    # 1. Use high-precision MAG contact number resolver
    try:
        phone_num = mag_engine.get_contact_number(clean_target)
    except Exception as e:
        logger.debug(f"[WhatsAppTool] Contact number resolve note: {e}")
        phone_num = None
    if phone_num:
        logger.info(f"[WhatsAppTool] Resolved '{clean_target}' to phone number '{phone_num}' from MAG memory.")
        return phone_num

    # 2. Check for contact alias in memory
    try:
        alias_mems = mag_engine.search_memories(f"whatsapp contact {clean_target}", limit=3)
        for m in alias_mems:
            content = m.get("content", "")
            match = re.search(rf"contact\s+(?:for\s+)?{re.escape(clean_target)}\s+is\s+(.+)", content, re.IGNORECASE)
            if match:
                resolved = match.group(1).strip()
                logger.info(f"[WhatsAppTool] Resolved alias '{clean_target}' -> '{resolved}' from MAG memory.")
                return resolved
    except Exception as e:
        logger.debug(f"[WhatsAppTool] Memory resolution check note: {e}")

    return clean_target


@tool(
    name="prepare_whatsapp_message",
    description="Draft and preview a WhatsApp message to a contact (Amma, Sister, Friends) with voice confirmation before sending."
)
def prepare_whatsapp_message(contact_or_number: str, message: str, require_confirmation: bool = True) -> str:
    """
    Drafts a WhatsApp message and presents a clear confirmation prompt before sending.
    """
    global _PENDING_WHATSAPP_DRAFT
    if not contact_or_number or not message:
        return "Error: Contact name/number and message text are required."

    raw_contact = contact_or_number.strip()
    msg = message.strip()

    # Check if user requested a template key (e.g. template="leaving_college")
    if msg.lower() in QUICK_WHATSAPP_TEMPLATES:
        msg = QUICK_WHATSAPP_TEMPLATES[msg.lower()]

    resolved = _resolve_contact_from_memory(raw_contact)
    is_num = bool(re.search(r"\d{8,}", resolved))

    _PENDING_WHATSAPP_DRAFT = {
        "contact": raw_contact,
        "resolved_target": resolved,
        "is_phone_number": is_num,
        "message": msg,
        "timestamp": time.time()
    }

    logger.info(f"[WhatsAppTool] Prepared pending draft for '{raw_contact}' ({resolved}): '{msg}'")

    if not require_confirmation:
        return send_whatsapp_message(contact_or_number=raw_contact, message=msg)

    target_display = f"{raw_contact} ({resolved})" if is_num and raw_contact != resolved else raw_contact
    return (
        f"📝 WhatsApp Message Draft for {target_display}:\n"
        f"💬 \"{msg}\"\n\n"
        f"👉 Shall I send this message now, Nandu? (Say 'Yes, send it' or 'Confirm' to dispatch)."
    )


@tool(
    name="confirm_and_send_whatsapp_draft",
    description="Confirm and immediately send the currently pending WhatsApp message draft."
)
def confirm_and_send_whatsapp_draft() -> str:
    """Dispatches the pending WhatsApp draft."""
    global _PENDING_WHATSAPP_DRAFT
    if not _PENDING_WHATSAPP_DRAFT:
        return "There is no pending WhatsApp message draft to send. Please specify a message first."

    draft = _PENDING_WHATSAPP_DRAFT
    _PENDING_WHATSAPP_DRAFT = None

    return send_whatsapp_message(
        contact_or_number=draft["contact"],
        message=draft["message"]
    )


@tool(
    name="get_pending_whatsapp_draft",
    description="Inspect or view the current pending unconfirmed WhatsApp draft."
)
def get_pending_whatsapp_draft() -> str:
    """View active pending draft."""
    if not _PENDING_WHATSAPP_DRAFT:
        return "No pending WhatsApp message drafts."

    d = _PENDING_WHATSAPP_DRAFT
    return f"Active Pending Draft to {d['contact']}:\n\"{d['message']}\""


@tool(
    name="send_whatsapp_message",
    description="Send a WhatsApp message immediately by contact name (auto-resolved from memory) or direct phone number."
)
def send_whatsapp_message(contact_or_number: str, message: str) -> str:
    """
    Open WhatsApp and send the message to the contact or phone number.
    Automatically resolves stored phone numbers or aliases from MAG memory.
    """
    if not contact_or_number or not message:
        return "Error: Contact name/number and message are required."

    raw_input = contact_or_number.strip()
    msg = message.strip()

    # Resolve contact name from MAG long-term memory (e.g. "Amma" -> "9505864289")
    resolved_target = _resolve_contact_from_memory(raw_input)

    # Check if target is a phone number
    clean_digits = re.sub(r"[^\d]", "", resolved_target)
    is_phone_number = len(clean_digits) >= 10 and (
        resolved_target.startswith("+")
        or clean_digits == resolved_target
        or bool(re.match(r"^[\+\d\s\-\(\)]+$", resolved_target.strip()))
    )

    # Direct 100% Precision Phone Protocol Dispatch
    if is_phone_number:
        if len(clean_digits) == 10:
            clean_digits = "91" + clean_digits

        logger.info(f"[WhatsAppTool] Direct WhatsApp dispatch to +{clean_digits} (Target: '{raw_input}')...")
        encoded_msg = urllib.parse.quote(msg)
        whatsapp_uri = f"whatsapp://send?phone={clean_digits}&text={encoded_msg}"

        try:
            # launch_target handles the whatsapp:// URI scheme cross-platform
            # (cmd /c start on Windows, xdg-open on Linux, open on macOS) — plain
            # webbrowser.open doesn't reliably dispatch custom URI schemes on POSIX.
            launch_target(whatsapp_uri)
            time.sleep(2.0)
            _focus_whatsapp_window()
            time.sleep(0.8)
            if pyautogui:
                pyautogui.press("enter")
            # Record episodic event only AFTER a successful dispatch so a failed
            # send is never logged as sent.
            _record_whatsapp_event(
                f"Sent WhatsApp message to {raw_input} (+{clean_digits})", msg
            )
            logger.info(f"[WhatsAppTool] Dispatched WhatsApp message to {raw_input} (+{clean_digits}) (delivery unconfirmed): '{msg}'")
            # We opened WhatsApp and (only when pyautogui is present) pressed enter,
            # but cannot confirm the message actually left the device — on a headless
            # host enter is never pressed. Don't claim a guaranteed "sent".
            return f"Opened WhatsApp and attempted to send your message to {raw_input} (+{clean_digits}): '{msg}'. Please glance at the chat to confirm it went through."
        except Exception as e:
            logger.warning(f"[WhatsAppTool] Desktop protocol failed, opening Web: {e}")
            web_url = f"https://web.whatsapp.com/send?phone={clean_digits}&text={encoded_msg}"
            open_url(web_url)
            return f"Opened WhatsApp Web for {raw_input} (+{clean_digits}) with your message."

    # Name-Based WhatsApp Desktop Search Fallback
    target_name = resolved_target
    logger.info(f"[WhatsAppTool] Searching WhatsApp Desktop for contact '{target_name}'...")

    has_focus = _focus_whatsapp_window()
    if not has_focus:
        launch_target("whatsapp://")
        time.sleep(2.5)
        _focus_whatsapp_window()

    if not pyautogui or not pyperclip:
        return f"Opened WhatsApp for '{target_name}'. Please press enter to send."

    time.sleep(0.8)

    # Reset any existing open chats or search state
    pyautogui.press("esc")
    time.sleep(0.2)
    pyautogui.press("esc")
    time.sleep(0.3)

    # Focus search bar
    pyautogui.hotkey("ctrl", "f")
    time.sleep(0.5)

    # Clear previous search
    pyautogui.hotkey("ctrl", "a")
    pyautogui.press("backspace")
    time.sleep(0.2)

    # Type/paste contact name
    pyperclip.copy(target_name)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(1.2)

    # Select top search match
    pyautogui.press("enter")
    time.sleep(0.8)

    # Paste and send message
    pyperclip.copy(msg)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.4)
    pyautogui.press("enter")

    logger.info(f"[WhatsAppTool] Dispatched message to '{target_name}' (delivery unconfirmed): '{msg}'")
    _record_whatsapp_event(f"Sent WhatsApp message to {target_name}", msg)
    # Name-based search picks WhatsApp's top match and presses enter blindly; we
    # can't verify the right chat got it, so don't claim a guaranteed "sent".
    return f"Opened WhatsApp and attempted to send your message to '{target_name}': '{msg}'. Please confirm the right chat received it, as I can't verify delivery."


@tool(
    name="get_quick_whatsapp_templates",
    description="List quick WhatsApp template messages (e.g. leaving college, in class, reaching soon, need notes)."
)
def get_quick_whatsapp_templates() -> str:
    """List available quick templates."""
    lines = ["📋 Quick WhatsApp Response Templates:"]
    for k, v in QUICK_WHATSAPP_TEMPLATES.items():
        lines.append(f"• [{k}]: \"{v}\"")
    return "\n".join(lines)


@tool(
    name="save_whatsapp_contact_alias",
    description="Save a contact name mapping or phone number in memory (e.g. alias='Amma', saved_name='9505864289')."
)
def save_whatsapp_contact_alias(alias: str, saved_name: str) -> str:
    """Save a contact name mapping or phone number in MAG memory."""
    clean_alias = alias.strip()
    clean_val = saved_name.strip()
    if not clean_alias or not clean_val:
        return "Error: Alias and target name/number are required."

    digits = re.sub(r"[^\d]", "", clean_val)
    if len(digits) >= 10:
        fact = f"{clean_alias} phone number is {clean_val}"
    else:
        fact = f"WhatsApp contact for {clean_alias} is {clean_val}"

    mag_engine.remember(fact, category="contact", tags="whatsapp,contact,phone")
    return f"Saved WhatsApp contact in memory: '{clean_alias}' -> '{clean_val}'."
