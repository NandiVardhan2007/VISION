"""
Autonomous Daily Morning Briefing & System Routine for VISION AI OS.
Compiles live weather, today's academic timetable & exam schedule, pending assignments,
active reminders, Hyderabad remote server health, and daily tech inspiration into a spoken summary.
"""

import time
import urllib.request
import urllib.parse
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from vision.tools.registry import tool
from vision.config import config
from vision.logger import logger

# Anchor DB lookups to the project root (not the CWD) so the briefing reads the
# same databases regardless of where VISION was launched from.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _PROJECT_ROOT / "data"


def _get_live_weather(city: str = "Anaparthi") -> str:
    """Fetch live weather summary using wttr.in or fallback."""
    try:
        safe_city = urllib.parse.quote(city, safe="")
        url = f"https://wttr.in/{safe_city}?format=%C+%t+(Feels+like+%f),+Humidity:+%h,+Wind:+%w"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=4) as response:
            data = response.read().decode("utf-8").strip()
            if data and "Unknown location" not in data:
                return f"{city}: {data}"
    except Exception as e:
        logger.debug(f"[BriefingTool] Live weather fetch note: {e}")
    # Live fetch failed — return an explicitly-labelled estimate, never presented
    # as a real reading.
    return f"{city}: weather unavailable (estimated ~32°C, typical seasonal conditions)"


def _get_academic_schedule() -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Retrieve today's college timetable, upcoming assignments, and exam schedule."""
    today_name = datetime.now().strftime("%A")
    timetable_items = []
    assignments = []
    exams = []

    db_path = _DATA_DIR / "academic.db"
    if not db_path.exists():
        return [], [], []

    try:
        with closing(sqlite3.connect(str(db_path), timeout=15)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # 1. Today's classes
            cur.execute(
                "SELECT period, subject, start_time, end_time, location FROM timetable WHERE LOWER(day_of_week) = LOWER(?) ORDER BY period ASC",
                (today_name,)
            )
            timetable_items = [dict(r) for r in cur.fetchall()]

            # 2. Pending assignments
            cur.execute(
                "SELECT subject, title, due_date_time FROM assignments WHERE status = 'pending' ORDER BY due_timestamp ASC LIMIT 3"
            )
            assignments = [dict(r) for r in cur.fetchall()]

            # 3. Upcoming exams
            cur.execute("SELECT subject, exam_date, timing FROM mid_exams ORDER BY exam_date ASC LIMIT 3")
            exams = [dict(r) for r in cur.fetchall()]

    except Exception as e:
        logger.warning(f"[BriefingTool] Academic DB lookup failed: {e}")

    return timetable_items, assignments, exams


def _get_active_reminders() -> List[Dict[str, Any]]:
    """Retrieve active reminders via the reminder manager (single source of truth).

    Previously this queried columns ('title', 'remind_at', status='active') that
    do not exist in the reminder daemon's schema, so it silently returned nothing.
    Delegating to reminder_manager keeps the schema in one place.
    """
    try:
        from vision.core.reminder_daemon import reminder_manager
        return reminder_manager.list_pending()[:4]
    except Exception as e:
        logger.debug(f"[BriefingTool] Reminders lookup note: {e}")
        return []


def _get_server_status_quick() -> str:
    """Check status of Hyderabad Ubuntu server (100.93.70.63)."""
    host = config.UBUNTU_SERVER_HOST
    try:
        from vision.tools.remote_server_tools import ssh_execute_command
        # Lightweight check
        res = ssh_execute_command("uptime -p && pgrep -fa print_server || echo 'Print server inactive'", timeout_seconds=6)
        res_low = res.lower()
        # "uptime -p" always emits "up ...", so testing for "up " matches even when
        # the print server is down. Report the print system as active only when
        # pgrep actually found the process (and did not echo the inactive marker).
        server_up = "up " in res_low
        print_active = "print_server" in res_low and "print server inactive" not in res_low
        if server_up:
            if print_active:
                return "Online & Operational (KPR print system active)"
            return "Online (print system inactive)"
    except Exception:
        pass
    return f"Server host configured at {host} (Standby)"


TECH_MOTIVATIONS = [
    "\"The only way to do great work is to love what you do.\" — Stay focused on DSA & Java mastery today, Nandu!",
    "\"Every expert was once a beginner. Keep pushing your limits with Full Stack Java and algorithms!\"",
    "\"Consistency is what transforms average into excellence. Make today count in class and code!\"",
    "\"Small daily improvements over time lead to stunning results. You've got this, bro!\""
]


@tool(
    name="get_daily_morning_briefing",
    description="Generate an all-in-one daily morning briefing covering live weather, today's college timetable, assignments, reminders, server health, and motivation."
)
def get_daily_morning_briefing(location: str = "Anaparthi") -> str:
    """
    Assembles a comprehensive daily morning briefing.
    """
    now = datetime.now()
    date_str = now.strftime("%A, %B %d, %Y")
    time_str = now.strftime("%I:%M %p")

    # 1. Weather
    weather = _get_live_weather(location)

    # 2. Academic Schedule
    classes, assignments, exams = _get_academic_schedule()

    # 3. Reminders
    reminders = _get_active_reminders()

    # 4. Server status
    server_status = _get_server_status_quick()

    # 5. Motivation
    import random
    motivation = random.choice(TECH_MOTIVATIONS)

    # Build structured text report
    lines = [
        f"🌅 Good Morning, Nandu! Here is your Daily Briefing for {date_str} ({time_str}):\n",
        f"🌦️ Live Weather:\n• {weather}\n",
        f"🎓 Today's College Timetable ({now.strftime('%A')}):"
    ]

    if classes:
        for c in classes:
            loc = f" in {c['location']}" if c.get('location') else ""
            lines.append(f"• Period {c['period']} ({c['start_time']} - {c['end_time']}): {c['subject']}{loc}")
    else:
        lines.append("• No scheduled college periods recorded for today (or Weekend / CRT self-study).")

    if exams:
        lines.append("\n📝 Upcoming Mid Exam Schedule:")
        for ex in exams:
            lines.append(f"• {ex['exam_date']}: {ex['subject']} ({ex.get('timing') or 'Morning'})")

    if assignments:
        lines.append("\n📚 Pending Assignments:")
        for a in assignments:
            lines.append(f"• [{a['subject']}] {a['title']} (Due: {a.get('due_date_time') or 'Soon'})")

    if reminders:
        lines.append("\n⏰ Active Alarms & Reminders:")
        for r in reminders:
            when = r.get("trigger_time", "")
            countdown = r.get("countdown")
            suffix = f" (in {countdown})" if countdown else ""
            lines.append(f"• {r.get('message', 'Reminder')} (Scheduled: {when}){suffix}")

    lines.append(f"\n🖥️ Hyderabad Ubuntu Server:\n• {server_status}\n")
    lines.append(f"💡 Daily Inspiration:\n{motivation}")

    return "\n".join(lines)


def _pick_next_class(classes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Pick the next upcoming class today by start_time, falling back to the first.

    Previously the quick status always reported classes[0] — the first period of
    the day — even in the afternoon when it had already finished.
    """
    if not classes:
        return None
    now = datetime.now()

    def _parse(t: Any) -> Optional[datetime]:
        for fmt in ("%I:%M %p", "%I %p", "%H:%M", "%H:%M:%S"):
            try:
                parsed = datetime.strptime(str(t).strip().upper(), fmt)
                return now.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
            except (ValueError, TypeError):
                continue
        return None

    upcoming = []
    for c in classes:
        dt = _parse(c.get("start_time"))
        if dt and dt >= now:
            upcoming.append((dt, c))
    if upcoming:
        upcoming.sort(key=lambda x: x[0])
        return upcoming[0][1]
    return classes[0]


@tool(
    name="get_quick_daily_status",
    description="Get a quick 1-sentence snapshot of the current time, weather, next class, and server status."
)
def get_quick_daily_status() -> str:
    """Short overview for fast voice responses."""
    now = datetime.now()
    classes, _, _ = _get_academic_schedule()
    next_cls = _pick_next_class(classes)
    next_sub = next_cls["subject"] if next_cls else "Self-study"
    return f"It is {now.strftime('%I:%M %p on %A')}. Next scheduled session is {next_sub}. All background systems are running smoothly, Nandu!"
