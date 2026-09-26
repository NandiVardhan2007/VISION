"""
Academic Schedule, Classroom Timetable & Mid-1 Exam Manager for VISION AI OS.
Tailored for Nandu: B.Tech III IT Section A, Room No. 221, Aditya College of Engineering and Technology (Surampalem).
"""

import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from vision.tools.registry import tool
from vision.logger import logger

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "academic.db")

# Official Class Timetable (III IT A, Room 221, R23 Regulation)
OFFICIAL_TIMETABLE = [
    # Monday
    ("Monday", 1, "DMDW (Data Warehousing & Data Mining)", "09:30", "10:20", "Room 221"),
    ("Monday", 2, "FSD I LAB-4 (Full Stack Development I)", "10:20", "11:10", "Lab-4 (KR)"),
    ("Monday", 3, "FSD I LAB-4 (Full Stack Development I)", "11:10", "12:00", "Lab-4 (KR)"),
    ("Monday", 4, "FSD I LAB-4 (Full Stack Development I)", "12:00", "12:50", "Lab-4 (KR)"),
    ("Monday", 5, "🍱 Lunch Break", "12:50", "13:50", "Campus"),
    ("Monday", 6, "THUB Placement Readiness (DSA Training)", "13:50", "14:40", "THUB"),
    ("Monday", 7, "THUB Placement Readiness (DSA Training)", "14:40", "15:30", "THUB"),
    ("Monday", 8, "THUB Placement Readiness (DSA Training)", "15:30", "16:10", "THUB"),

    # Tuesday
    ("Tuesday", 1, "DMDW (Data Warehousing & Data Mining)", "09:30", "10:20", "Room 221"),
    ("Tuesday", 2, "ATCD (Automata Theory & Compiler Design)", "10:20", "11:10", "Room 221"),
    ("Tuesday", 3, "DMDW (Data Warehousing & Data Mining)", "11:10", "12:00", "Room 221"),
    ("Tuesday", 4, "A.JAVA (Advanced Java)", "12:00", "12:50", "Room 221"),
    ("Tuesday", 5, "🍱 Lunch Break", "12:50", "13:50", "Campus"),
    ("Tuesday", 6, "THUB Placement Readiness (DSA Training)", "13:50", "14:40", "THUB"),
    ("Tuesday", 7, "THUB Placement Readiness (DSA Training)", "14:40", "15:30", "THUB"),
    ("Tuesday", 8, "THUB Placement Readiness (DSA Training)", "15:30", "16:10", "THUB"),

    # Wednesday
    ("Wednesday", 1, "CN (Computer Networks - NSK)", "09:30", "10:20", "Room 221"),
    ("Wednesday", 2, "EDC (Entrepreneurship Development & Creation)", "10:20", "11:10", "Room 221"),
    ("Wednesday", 3, "A.JAVA (Advanced Java)", "11:10", "12:00", "Room 221"),
    ("Wednesday", 4, "ATCD (Automata Theory & Compiler Design)", "12:00", "12:50", "Room 221"),
    ("Wednesday", 5, "🍱 Lunch Break", "12:50", "13:50", "Campus"),
    ("Wednesday", 6, "THUB Full Stack (Spring Boot Training)", "13:50", "14:40", "THUB"),
    ("Wednesday", 7, "THUB Full Stack (Spring Boot Training)", "14:40", "15:30", "THUB"),
    ("Wednesday", 8, "THUB Full Stack (Spring Boot Training)", "15:30", "16:10", "THUB"),

    # Thursday
    ("Thursday", 1, "CRT Training Class (Campus Recruitment Training)", "09:30", "10:20", "Room 221"),
    ("Thursday", 2, "CRT Training Class (Campus Recruitment Training)", "10:20", "11:10", "Room 221"),
    ("Thursday", 3, "CRT Training Class (Campus Recruitment Training)", "11:10", "12:00", "Room 221"),
    ("Thursday", 4, "A.JAVA (Advanced Java)", "12:00", "12:50", "Room 221"),
    ("Thursday", 5, "🍱 Lunch Break", "12:50", "13:50", "Campus"),
    ("Thursday", 6, "THUB Full Stack (Spring Boot Training)", "13:50", "14:40", "THUB"),
    ("Thursday", 7, "THUB Full Stack (Spring Boot Training)", "14:40", "15:30", "THUB"),
    ("Thursday", 8, "THUB Full Stack (Spring Boot Training)", "15:30", "16:10", "THUB"),

    # Friday
    ("Friday", 1, "EDC (Entrepreneurship Development & Creation)", "09:30", "10:20", "Room 221"),
    ("Friday", 2, "CN LAB-4 (Computer Networks Lab - NSK)", "10:20", "11:10", "Lab-4"),
    ("Friday", 3, "CN LAB-4 (Computer Networks Lab - NSK)", "11:10", "12:00", "Lab-4"),
    ("Friday", 4, "CN LAB-4 (Computer Networks Lab - NSK)", "12:00", "12:50", "Lab-4"),
    ("Friday", 5, "🍱 Lunch Break", "12:50", "13:50", "Campus"),
    ("Friday", 6, "THUB Full Stack (Spring Boot Training)", "13:50", "14:40", "THUB"),
    ("Friday", 7, "THUB Full Stack (Spring Boot Training)", "14:40", "15:30", "THUB"),
    ("Friday", 8, "THUB Full Stack (Spring Boot Training)", "15:30", "16:10", "THUB"),

    # Saturday
    ("Saturday", 1, "CRT Training Class (Campus Recruitment Training)", "09:30", "10:20", "Room 221"),
    ("Saturday", 2, "CRT Training Class (Campus Recruitment Training)", "10:20", "11:10", "Room 221"),
    ("Saturday", 3, "CRT Training Class (Campus Recruitment Training)", "11:10", "12:00", "Room 221"),
    ("Saturday", 4, "CRT Training Class (Campus Recruitment Training)", "12:00", "12:50", "Room 221"),
    ("Saturday", 5, "🍱 Lunch Break", "12:50", "13:50", "Campus"),
    ("Saturday", 6, "THUB Full Stack (Spring Boot Training)", "13:50", "14:40", "THUB"),
    ("Saturday", 7, "THUB Full Stack (Spring Boot Training)", "14:40", "15:30", "THUB"),
    ("Saturday", 8, "THUB Full Stack (Spring Boot Training)", "15:30", "16:10", "THUB"),
]

# Mid-1 (I Sessional Examinations) August 2026
MID_1_EXAMS = [
    ("2026-08-18", "Tuesday", "Computer Networks", "231CS5T02", "Theory", "10:00 AM – 12:00 Noon"),
    ("2026-08-19", "Wednesday", "Automata Theory & Compiler Design", "231IT5T02", "Theory", "10:00 AM – 12:00 Noon"),
    ("2026-08-20", "Thursday", "Data Warehousing & Data Mining", "231IT5E02", "Professional Elective-I", "10:00 AM – 12:00 Noon"),
    ("2026-08-21", "Friday", "Entrepreneurship Development & Venture Creation", "231CE5O01", "Open Elective-I", "10:00 AM – 12:00 Noon"),
    ("2026-08-22", "Saturday", "Advanced Java", "231IT5T01", "Theory", "10:00 AM – 12:00 Noon"),
]


class AcademicManager:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self):
        """Yield a sqlite connection that commits on success, rolls back on
        error, and is ALWAYS closed. A bare `with sqlite3.connect() as conn`
        commits but never closes the handle — on Windows that leaves the .db
        file locked (WinError 32). timeout=15 + WAL let executor-thread tool
        calls read/write concurrently without 'database is locked'."""
        conn = sqlite3.connect(self.db_path, timeout=15)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS timetable (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    day_of_week TEXT NOT NULL,
                    period INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    location TEXT DEFAULT 'Room 221'
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,
                    title TEXT NOT NULL,
                    due_date_time TEXT NOT NULL,
                    due_timestamp REAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    description TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mid_exams (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exam_date TEXT NOT NULL,
                    day_of_week TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    code TEXT NOT NULL,
                    exam_type TEXT NOT NULL,
                    timing TEXT NOT NULL
                )
            """)
            conn.commit()

            # Always sync official timetable
            cursor.execute("DELETE FROM timetable")
            cursor.executemany(
                "INSERT INTO timetable (day_of_week, period, subject, start_time, end_time, location) VALUES (?, ?, ?, ?, ?, ?)",
                OFFICIAL_TIMETABLE
            )

            # Always sync Mid-1 exams
            cursor.execute("DELETE FROM mid_exams")
            cursor.executemany(
                "INSERT INTO mid_exams (exam_date, day_of_week, subject, code, exam_type, timing) VALUES (?, ?, ?, ?, ?, ?)",
                MID_1_EXAMS
            )
            conn.commit()
            logger.info("[AcademicManager] Synced official III IT A timetable and Mid-1 exam schedule.")

    def get_schedule_for_day(self, day_name: Optional[str] = None) -> List[Dict[str, Any]]:
        target_day = day_name.capitalize() if day_name else datetime.now().strftime("%A")
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM timetable WHERE day_of_week = ? ORDER BY start_time ASC", (target_day,))
            return [dict(row) for row in cursor.fetchall()]

    def get_mid_exams(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mid_exams ORDER BY exam_date ASC")
            return [dict(row) for row in cursor.fetchall()]

    def _parse_due_to_timestamp(self, due_str: str) -> float:
        """Convert an assignment due string into an absolute epoch timestamp.

        Tries explicit calendar-date formats first (e.g. '25-12-2026',
        '2026-12-25', '25 Dec 2026'), because the natural-language
        ``reminder_manager.parse_time_offset`` only understands *offsets* and
        clock times — feeding it a day number like '25' makes it try
        ``now.replace(hour=25)`` and raise ValueError. Falls back to
        parse_time_offset for phrases like 'in 2 days'/'5:30 pm', and finally
        defaults to 24h out.
        """
        s = (due_str or "").strip()
        date_formats = (
            "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d",
            "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M",
            "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y",
            "%d %b", "%d %B",
        )
        for fmt in date_formats:
            try:
                dt = datetime.strptime(s, fmt)
                if "%Y" not in fmt:  # year-less format: assume current year
                    dt = dt.replace(year=datetime.now().year)
                return dt.timestamp()
            except ValueError:
                continue

        try:
            from vision.core.reminder_daemon import reminder_manager
            ts = reminder_manager.parse_time_offset(s)
            if ts:
                return ts
        except Exception as e:
            logger.debug(f"[Academic] Due-date offset parse failed for '{s}': {e}")

        return time.time() + 86400

    def add_assignment(self, subject: str, title: str, due_str: str, description: Optional[str] = None) -> Dict[str, Any]:
        from vision.core.reminder_daemon import reminder_manager
        due_timestamp = self._parse_due_to_timestamp(due_str)
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO assignments (subject, title, due_date_time, due_timestamp, status, description, created_at) VALUES (?, ?, ?, ?, 'pending', ?, ?)",
                (subject, title, due_str, due_timestamp, description or "", created_at)
            )
            assign_id = cursor.lastrowid
            conn.commit()

        # Schedule the reminder from the resolved absolute timestamp rather than
        # re-parsing due_str (add_reminder's time_str path shares the same
        # offset-only limitation), so calendar-dated assignments fire correctly.
        delay = max(1, int(due_timestamp - time.time()))
        reminder_manager.add_reminder(
            message=f"Assignment Deadline: {subject} - '{title}' is due!",
            delay_seconds=delay,
            reminder_type="assignment"
        )

        return {
            "id": assign_id,
            "subject": subject,
            "title": title,
            "due_date_time": due_str,
            "status": "pending"
        }

    def list_assignments(self, status: str = "pending") -> List[Dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if status == "all":
                cursor.execute("SELECT * FROM assignments ORDER BY due_timestamp ASC")
            else:
                cursor.execute("SELECT * FROM assignments WHERE status = ? ORDER BY due_timestamp ASC", (status,))
            return [dict(row) for row in cursor.fetchall()]

    def mark_completed(self, ident: str) -> bool:
        with self._connect() as conn:
            cursor = conn.cursor()
            if ident.isdigit():
                cursor.execute("UPDATE assignments SET status = 'completed' WHERE id = ?", (int(ident),))
                conn.commit()
                return cursor.rowcount > 0
            # Non-numeric identifier: match by title without over-completing. A bare
            # `LIKE '%ident%'` UPDATE silently marks EVERY assignment containing the
            # text (e.g. "essay" completes all essays). Prefer an exact (case-
            # insensitive) title match; only fall back to a substring search when it
            # resolves to exactly one assignment, otherwise refuse as ambiguous.
            cursor.execute("SELECT id FROM assignments WHERE lower(title) = lower(?)", (ident,))
            ids = [row[0] for row in cursor.fetchall()]
            if not ids:
                safe = ident.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                cursor.execute(
                    "SELECT id FROM assignments WHERE title LIKE ? ESCAPE '\\'", (f"%{safe}%",)
                )
                ids = [row[0] for row in cursor.fetchall()]
                if len(ids) != 1:
                    # 0 → no match; >1 → ambiguous, don't complete the wrong ones.
                    return False
            placeholders = ",".join(["?"] * len(ids))
            cursor.execute(
                f"UPDATE assignments SET status = 'completed' WHERE id IN ({placeholders})", ids
            )
            conn.commit()
            return cursor.rowcount > 0


academic_manager = AcademicManager()


@tool(
    name="get_college_timetable",
    description="Get the daily classroom timetable, lab schedule, and THUB sessions for B.Tech III IT Section A (Room 221) at Aditya College of Engineering & Technology."
)
def get_college_timetable(day_name: Optional[str] = None) -> str:
    """
    Get the class timetable for today or a specified day of the week.
    """
    day = day_name.capitalize() if day_name else datetime.now().strftime("%A")
    classes = academic_manager.get_schedule_for_day(day)
    if not classes:
        return f"No classes scheduled for {day} (Holiday/Sunday), Nandu!"

    output = [f"📅 **III IT A Class Timetable (Room 221) - {day}**\n"]
    for c in classes:
        output.append(f"• **{c['start_time']} - {c['end_time']}**: {c['subject']} ({c['location']})")
    
    return "\n".join(output)


@tool(
    name="get_mid_exam_schedule",
    description="Get the complete Mid-1 (I Sessional Examinations) schedule for B.Tech V Semester (IT Branch, ACETR23) at Aditya College of Engineering & Technology."
)
def get_mid_exam_schedule() -> str:
    """
    Returns the B.Tech V Semester Mid-1 Examination timetable.
    """
    exams = academic_manager.get_mid_exams()
    output = [
        "📝 **B.Tech V Semester - Mid-1 (I Sessional) Exam Timetable (10:00 AM – 12:00 Noon):**\n"
    ]
    for e in exams:
        output.append(
            f"• **{e['exam_date']} ({e['day_of_week']})**: **{e['subject']}** (Code: `{e['code']}`, Type: {e['exam_type']})"
        )
    return "\n".join(output)


@tool(
    name="get_next_upcoming_class",
    description="Get the very next upcoming class, lab, THUB session, or Mid-1 exam for today."
)
def get_next_upcoming_class() -> str:
    """
    Finds the next scheduled class or exam starting today.
    """
    now = datetime.now()
    now_str = now.strftime("%H:%M")
    today_date = now.strftime("%Y-%m-%d")
    today = now.strftime("%A")

    # 1. Check if there is a Mid-1 exam today
    exams = academic_manager.get_mid_exams()
    for e in exams:
        if e['exam_date'] == today_date:
            return f"🔥 **MID-1 EXAM TODAY!**\n**Subject**: {e['subject']} (Code: `{e['code']}`)\n**Time**: 10:00 AM – 12:00 Noon\nGood luck with your preparation, Nandu!"

    # 2. Check regular timetable
    classes = academic_manager.get_schedule_for_day(today)
    for c in classes:
        if c['start_time'] > now_str:
            return f"Your next session today is **{c['subject']}** starting at **{c['start_time']}** ({c['location']})."

    return f"You have finished all scheduled classes/sessions for today ({today}), Nandu!"


@tool(
    name="add_college_assignment",
    description="Add an academic assignment deadline or project submission with automatic spoken reminder scheduling."
)
def add_college_assignment(subject: str, title: str, due_date_time: str, description: Optional[str] = None) -> str:
    res = academic_manager.add_assignment(subject=subject, title=title, due_str=due_date_time, description=description)
    return f"Successfully added assignment #{res['id']} for **{subject}**: '{title}' (Due: {due_date_time}). Voice reminder scheduled!"


@tool(
    name="list_college_assignments",
    description="List all upcoming or pending college assignments, project submissions, and due dates."
)
def list_college_assignments(status: str = "pending") -> str:
    assignments = academic_manager.list_assignments(status=status)
    if not assignments:
        return "No pending assignments! You're all caught up, Nandu!"

    lines = ["📚 **Upcoming Academic Assignments & Deadlines:**\n"]
    for a in assignments:
        due_dt = datetime.fromtimestamp(a['due_timestamp']).strftime('%b %d, %I:%M %p')
        lines.append(f"- **[#{a['id']}] {a['subject']}**: {a['title']} (Due: {a['due_date_time']} ~ {due_dt}) - *{a['status'].upper()}*")

    return "\n".join(lines)


@tool(
    name="mark_assignment_done",
    description="Mark an assignment as completed by its ID or title."
)
def mark_assignment_done(assignment_id_or_title: str) -> str:
    success = academic_manager.mark_completed(assignment_id_or_title)
    if success:
        return f"Awesome, Nandu! Marked assignment '{assignment_id_or_title}' as completed."
    return f"Could not find assignment matching '{assignment_id_or_title}'."


async def start_academic_daemon(speech_callback=None):
    """
    Monitors class timetable, THUB sessions, and Mid-1 exams, proactively speaking alerts.
    """
    import asyncio
    notified_events = set()
    logger.info("[AcademicDaemon] Proactive Class, THUB & Mid-1 Exam Watchdog active.")

    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            today_name = now.strftime("%A")

            # 1. Check Mid-1 Exams today (Speak morning reminder at 8:30 AM)
            exam_key = f"exam_{today_str}"
            if exam_key not in notified_events:
                exams = academic_manager.get_mid_exams()
                for e in exams:
                    if e['exam_date'] == today_str:
                        if now.hour == 8 and now.minute >= 30:
                            notified_events.add(exam_key)
                            msg = f"Good morning Nandu! Reminder: You have your Mid-1 exam today for {e['subject']} from 10:00 AM to 12:00 Noon. All the best bro!"
                            logger.info(f"[AcademicDaemon] 📝 Spoken Mid-1 Exam Alert: {msg}")
                            if speech_callback:
                                await speech_callback(msg)

            # 2. Check regular periods & THUB sessions (Alert 15 mins prior)
            classes = academic_manager.get_schedule_for_day(today_name)
            for c in classes:
                class_key = f"{today_str}_{c['id']}"
                if class_key in notified_events:
                    continue

                class_hour, class_min = map(int, c['start_time'].split(":"))
                class_dt = now.replace(hour=class_hour, minute=class_min, second=0, microsecond=0)
                lead_dt = class_dt - timedelta(minutes=15)

                if lead_dt <= now < class_dt:
                    notified_events.add(class_key)
                    alert = f"Nandu, reminder: Your {c['subject']} period begins in 15 minutes at {c['start_time']} in {c['location']}."
                    logger.info(f"[AcademicDaemon] 🎓 Proactive class alert: {alert}")
                    if speech_callback:
                        await speech_callback(alert)
        except Exception as e:
            logger.debug(f"[AcademicDaemon] Watchdog loop error: {e}")
        await asyncio.sleep(30)
