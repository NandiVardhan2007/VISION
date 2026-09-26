"""
Test suite for WhatsApp automation tools and interactive voice messenger.
"""

from unittest.mock import patch, MagicMock
from vision.tools.whatsapp_tools import (
    send_whatsapp_message,
    prepare_whatsapp_message,
    confirm_and_send_whatsapp_draft,
    get_pending_whatsapp_draft,
    get_quick_whatsapp_templates,
    save_whatsapp_contact_alias,
    _resolve_contact_from_memory
)
from vision.tools.registry import tool_registry


def test_whatsapp_tools_registered():
    expected = [
        "send_whatsapp_message",
        "prepare_whatsapp_message",
        "confirm_and_send_whatsapp_draft",
        "get_pending_whatsapp_draft",
        "get_quick_whatsapp_templates",
        "save_whatsapp_contact_alias"
    ]
    for t in expected:
        assert t in tool_registry._tools, f"Tool '{t}' was not registered"


def test_whatsapp_tool_validation():
    res = send_whatsapp_message("", "")
    assert "Error" in res

    prep_err = prepare_whatsapp_message("", "")
    assert "Error" in prep_err


def test_whatsapp_alias_tool():
    res = save_whatsapp_contact_alias("Bro", "Brother (College)")
    assert "Saved WhatsApp contact in memory" in res


def test_whatsapp_templates():
    templates = get_quick_whatsapp_templates()
    assert "leaving_college" in templates
    assert "in_class" in templates


@patch("vision.tools.whatsapp_tools.pyautogui")
@patch("vision.tools.whatsapp_tools.open_url")
@patch("vision.tools.whatsapp_tools.launch_target")
def test_whatsapp_interactive_confirmation_flow(mock_launch, mock_open_url, mock_pyautogui):
    # 1. Prepare draft
    draft_res = prepare_whatsapp_message(
        contact_or_number="Amma",
        message="I am starting from college now.",
        require_confirmation=True
    )
    assert "WhatsApp Message Draft for Amma" in draft_res
    assert "I am starting from college now." in draft_res
    assert "Shall I send this message now" in draft_res

    # 2. View pending draft
    pending = get_pending_whatsapp_draft()
    assert "Amma" in pending
    assert "starting from college" in pending

    # 3. Confirm and dispatch
    with patch("vision.tools.whatsapp_tools._focus_whatsapp_window", return_value=True):
        send_res = confirm_and_send_whatsapp_draft()
        assert "Successfully sent WhatsApp message" in send_res or "Opened WhatsApp" in send_res
        # Dispatch now goes through the cross-platform launcher (whatsapp:// URI)
        # or the web fallback, never webbrowser directly.
        assert mock_launch.called or mock_open_url.called

    # 4. Pending draft should now be cleared
    assert get_pending_whatsapp_draft() == "No pending WhatsApp message drafts."
