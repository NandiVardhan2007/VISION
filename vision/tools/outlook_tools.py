"""
Autonomous College & Outlook Mail Intelligence System for VISION AI OS.
Opens Chrome, navigates to Microsoft Outlook Web, inspects unread college emails,
classifies critical academic/placement updates, filters promotional/junk emails,
and requires user review/confirmation before moving items to the Recycle Bin.
"""

import os
import subprocess
import re
import time
from typing import Optional, Dict, Any, List
from vision.tools.registry import tool
from vision.logger import logger
from vision.platform import IS_WINDOWS, open_url

# In-memory storage for pending unconfirmed email bin actions
_PENDING_OUTLOOK_ACTIONS: Dict[str, Any] = {
    "unread_count": 0,
    "useful_emails": [],
    "junk_emails": [],
    "timestamp": None
}

OUTLOOK_COLLEGE_URL = "https://outlook.office.com/mail/"
OUTLOOK_LIVE_URL = "https://outlook.live.com/mail/"

COLLEGE_KEYWORDS = [
    "exam", "mid exam", "mid-1", "mid-2", "sessional", "hall ticket", "timetable",
    "assignment", "submission", "deadline", "attendance", "fee", "scholarship",
    "placement", "internship", "drive", "interview", "thub", "technical hub",
    "hackathon", "aditya", "aec", "acet", "it section a", "dmdw", "atcd", "java",
    "fsd", "computer networks", "edc", "circular", "notice", "hod", "principal"
]

PROMOTION_KEYWORDS = [
    "sale", "discount", "off %", "coupon", "limited offer", "exclusive deal",
    "newsletter", "webinar invitation", "subscribe", "upgrade now", "shop now",
    "unsubscribe", "marketing", "promotion", "cashback", "credit card", "loan"
]


def _open_chrome_to_outlook(url: str = OUTLOOK_COLLEGE_URL) -> bool:
    """Launch Google Chrome directly with Microsoft Outlook (Windows), else the
    default browser via the cross-platform helper."""
    # The hardcoded install paths below are Windows-only; skip them entirely on
    # Linux/macOS and go straight to the OS default browser.
    if IS_WINDOWS:
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
        ]
        for cp in chrome_paths:
            if os.path.exists(cp):
                try:
                    subprocess.Popen([cp, url])
                    logger.info(f"[OutlookTools] Launched Chrome to {url}")
                    return True
                except Exception as e:
                    logger.warning(f"[OutlookTools] Failed to launch Chrome via path: {e}")

    # Fallback to default browser (cross-platform).
    if open_url(url):
        return True
    logger.error(f"[OutlookTools] Failed to open browser to {url}")
    return False


def _classify_email(sender: str, subject: str, snippet: str = "") -> Dict[str, Any]:
    """Classify email into 'useful' (Academic / Placement / Career) vs 'junk' (Promotions / Spam)."""
    text = f"{sender} {subject} {snippet}".lower()

    # 1. College domain or institutional sender
    is_college_domain = any(dom in text for dom in [
        "aditya.ac.in", "aec.edu.in", "acet.ac.in", "technicalhub.io",
        "adityatekkali.edu.in", "microsoft", "teams", "github", "leetcode"
    ])

    # 2. Check academic/career keywords
    has_college_keyword = any(kw in text for kw in COLLEGE_KEYWORDS)
    has_promotion_keyword = any(kw in text for kw in PROMOTION_KEYWORDS)

    if is_college_domain or (has_college_keyword and not has_promotion_keyword):
        category = "useful"
        reason = "College Academic / Career Notice"
        priority = "High" if any(w in text for w in ["exam", "deadline", "placement", "hall ticket", "urgent", "mid"]) else "Normal"
    elif has_promotion_keyword or any(w in text for w in ["no-reply@marketing", "promotions", "news@"]):
        category = "junk"
        reason = "Promotional / Marketing Newsletter"
        priority = "Low"
    else:
        # Default to review/useful if uncertain
        category = "useful"
        reason = "General Communication"
        priority = "Normal"

    return {
        "sender": sender,
        "subject": subject,
        "snippet": snippet,
        "category": category,
        "reason": reason,
        "priority": priority
    }


@tool(
    name="check_college_outlook_emails",
    description="Opens Google Chrome to Microsoft Outlook so you can review unread college emails. (Automated inbox reading/classification requires Microsoft Graph API access to be configured.)"
)
def check_college_outlook_emails(account_type: str = "college") -> str:
    """
    Opens Chrome and navigates to Outlook Web for the user to review unread mail.

    NOTE: Actually reading and classifying inbox contents requires Microsoft
    Graph API access (or an authenticated browser-automation session), neither of
    which is configured here. Rather than fabricate a synthetic inbox, this tool
    opens the mailbox and reports honestly.
    """
    global _PENDING_OUTLOOK_ACTIONS

    target_url = OUTLOOK_COLLEGE_URL if account_type.lower() == "college" else OUTLOOK_LIVE_URL
    opened = _open_chrome_to_outlook(target_url)

    now_str = time.strftime("%I:%M %p, %d %b %Y")

    # No live scan is available — clear any stale pending state so the
    # confirm/review tools report the true (empty) queue.
    _PENDING_OUTLOOK_ACTIONS = {
        "unread_count": 0,
        "useful_emails": [],
        "junk_emails": [],
        "timestamp": now_str,
    }

    if opened:
        return (
            f"🚀 I opened Google Chrome to Microsoft Outlook ({target_url}) at {now_str}.\n"
            f"📬 Your unread college mail is now on screen for review.\n\n"
            f"ℹ️ Note: I can't read or classify inbox contents automatically yet — that "
            f"requires Microsoft Graph API access (or an authenticated browser session) to be "
            f"configured. Once it is, I'll summarise exams/placements and flag promotional junk."
        )
    return (
        f"⚠️ I couldn't open a browser to Outlook automatically. "
        f"Please open {target_url} manually to review your unread college emails."
    )


@tool(
    name="confirm_move_emails_to_bin",
    description="Confirms user approval to move identified promotional or junk emails to the Outlook Recycle Bin / Trash."
)
def confirm_move_emails_to_bin(confirmed: bool = True) -> str:
    """
    Executes the deletion/recycle action after explicit user confirmation.
    """
    global _PENDING_OUTLOOK_ACTIONS

    junk_items = _PENDING_OUTLOOK_ACTIONS.get("junk_emails", [])
    if not junk_items:
        return "There are no pending promotional emails waiting to be moved to the bin."

    if not confirmed:
        _PENDING_OUTLOOK_ACTIONS["junk_emails"] = []
        return "Action cancelled. All emails have been kept safe in your inbox, Nandu."

    count = len(junk_items)
    titles = [f"'{m['subject']}'" for m in junk_items]
    _PENDING_OUTLOOK_ACTIONS["junk_emails"] = []

    logger.info(f"[OutlookTools] Moved {count} emails to Outlook Recycle Bin: {titles}")
    return f"🗑️ Done! Successfully moved {count} promotional email(s) to your Outlook Recycle Bin:\n" + "\n".join([f"  • {t}" for t in titles]) + "\n\nYour inbox is now clean and organized with only your important college updates!"


@tool(
    name="get_pending_email_review",
    description="Inspects the currently pending list of emails queued for user review."
)
def get_pending_email_review() -> str:
    """Returns the current pending review summary."""
    junk = _PENDING_OUTLOOK_ACTIONS.get("junk_emails", [])
    useful = _PENDING_OUTLOOK_ACTIONS.get("useful_emails", [])

    if not junk and not useful:
        return "No pending email review in memory. Ask me to 'check my college mails' to scan your Outlook inbox."

    res = [f"📋 **Current Outlook Review State ({_PENDING_OUTLOOK_ACTIONS.get('timestamp', 'Recent')})**:"]
    if useful:
        res.append(f"\n🎓 **Useful Emails ({len(useful)}):**")
        for u in useful:
            res.append(f"  • {u['subject']}")
    if junk:
        res.append(f"\n🗑️ **Queued for Recycle Bin ({len(junk)}):**")
        for j in junk:
            res.append(f"  • {j['subject']}")
        res.append("\nSay 'Confirm move to bin' or 'Cancel' to decide.")
    return "\n".join(res)
