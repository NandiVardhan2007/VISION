"""
Reminder, Alarm & Timer Automation Tools for VISION AI OS.
Allows VISION to schedule proactive voice reminders, alarms, and timers.
"""

from typing import Optional
from vision.tools.registry import tool
from vision.core.reminder_daemon import reminder_manager
from vision.logger import logger


@tool(name="set_voice_reminder", description="Set a scheduled voice reminder or alarm (e.g. 'in 20 minutes', 'at 5:30 PM', 'tomorrow at 9 AM').")
def set_voice_reminder(
    reminder_text: str,
    delay_minutes: Optional[float] = None,
    time_str: Optional[str] = None
) -> str:
    """
    Schedules a voice reminder that will ring and speak aloud over speakers when the scheduled time arrives.
    """
    if not reminder_text:
        return "Error: Reminder message text is required."

    try:
        res = reminder_manager.add_reminder(
            message=reminder_text,
            delay_minutes=delay_minutes,
            time_str=time_str,
            reminder_type="reminder"
        )
    except Exception as e:
        logger.error(f"[ReminderTool] Failed to schedule reminder: {e}")
        return f"Failed to schedule reminder: {e}"

    return (
        f"Reminder scheduled successfully!\n"
        f"• Message: '{res['message']}'\n"
        f"• Alert Time: {res['trigger_time']} (in {res['countdown']})\n"
        f"• ID: #{res['id']}"
    )


@tool(name="set_timer", description="Set a countdown timer with duration in minutes or seconds (e.g. '15 minutes', '45 seconds').")
def set_timer(
    duration_minutes: Optional[float] = None,
    duration_seconds: Optional[int] = None,
    timer_label: Optional[str] = "Timer"
) -> str:
    """Sets a countdown timer that will chime and speak when elapsed."""
    total_secs = 0
    if duration_seconds is not None:
        total_secs += int(duration_seconds)
    if duration_minutes is not None:
        total_secs += int(duration_minutes * 60)

    if total_secs <= 0:
        total_secs = 300 # Default 5 minutes

    label = timer_label or "Timer"
    try:
        res = reminder_manager.add_reminder(
            message=label,
            delay_seconds=total_secs,
            reminder_type="timer"
        )
    except Exception as e:
        logger.error(f"[ReminderTool] Failed to start timer: {e}")
        return f"Failed to start timer: {e}"

    return f"Timer for '{res['message']}' started! It will ring in {res['countdown']} (at {res['trigger_time']})."


@tool(name="list_active_reminders", description="List all pending voice reminders, alarms, and active countdown timers.")
def list_active_reminders() -> str:
    """Lists all active scheduled reminders with remaining countdown."""
    pending = reminder_manager.list_pending()
    if not pending:
        return "No active reminders or timers scheduled."

    lines = ["Active Reminders & Timers:"]
    for r in pending:
        icon = "⏳" if r["type"] == "timer" else "⏰"
        lines.append(f"• {icon} #{r['id']} [{r['type'].upper()}]: '{r['message']}' at {r['trigger_time']} (in {r['countdown']})")

    return "\n".join(lines)


@tool(name="cancel_reminder", description="Cancel a pending reminder or timer by its ID number or matching keyword.")
def cancel_reminder(
    reminder_id: Optional[int] = None,
    keyword: Optional[str] = None
) -> str:
    """Cancels a scheduled reminder or timer."""
    cancelled = reminder_manager.cancel(reminder_id=reminder_id, keyword=keyword)
    if not cancelled:
        return "No matching pending reminders found to cancel."

    names = [f"#{c['id']} ('{c['message']}')" for c in cancelled]
    return f"Cancelled reminder(s): {', '.join(names)}."
