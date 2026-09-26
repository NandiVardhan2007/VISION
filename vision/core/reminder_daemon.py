"""
Autonomous Spoken Reminder & Alarm Daemon for VISION AI OS.
Maintains persistent scheduled reminders/timers in SQLite and runs an asynchronous background
daemon that plays chimes and proactively synthesizes and speaks alerts through Cartesia TTS.
"""

import os
import time
import sqlite3
import asyncio
import re
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Iterator
from vision.logger import logger
from vision.config import config
from vision.platform import play_chime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "reminders.db")


class ReminderManager:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        self._daemon_task: Optional[asyncio.Task] = None
        self._is_running = False

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection that commits/rolls back and always closes.

        The daemon opens a connection every couple of seconds; the previous
        ``with sqlite3.connect(...)`` idiom never closed them, leaking OS file
        handles over a long-running session and locking the DB file on Windows.
        """
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        # WAL + NORMAL sync: the daemon polls this DB every ~2s in an executor
        # thread while add/cancel tool calls write from other executor threads.
        # WAL lets readers and a writer coexist, cutting "database is locked".
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        try:
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
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    trigger_time_iso TEXT NOT NULL,
                    trigger_timestamp REAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    reminder_type TEXT DEFAULT 'reminder',
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_status_time ON reminders(status, trigger_timestamp)")
            conn.commit()

    def parse_time_offset(self, time_str: str) -> Optional[float]:
        """Parses natural time expressions into absolute epoch timestamps."""
        t_clean = time_str.lower().strip()
        now = datetime.now()

        # 1. Matches "in X seconds / minutes / hours"
        match_secs = re.search(r"in\s+(\d+)\s*(?:sec|second|seconds|s\b)", t_clean)
        if match_secs:
            return (now + timedelta(seconds=int(match_secs.group(1)))).timestamp()

        match_mins = re.search(r"in\s+(\d+(?:\.\d+)?)\s*(?:min|minute|minutes|m\b)", t_clean)
        if match_mins:
            return (now + timedelta(minutes=float(match_mins.group(1)))).timestamp()

        match_hrs = re.search(r"in\s+(\d+(?:\.\d+)?)\s*(?:hour|hours|hr|hrs|h\b)", t_clean)
        if match_hrs:
            return (now + timedelta(hours=float(match_hrs.group(1)))).timestamp()

        # 2. Matches clock times like "5:30 pm", "10:00 am", "17:30"
        match_time = re.search(r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t_clean)
        if match_time:
            hour = int(match_time.group(1))
            minute = int(match_time.group(2) or 0)
            ampm = match_time.group(3)
            
            if ampm:
                if ampm == "pm" and hour < 12:
                    hour += 12
                elif ampm == "am" and hour == 12:
                    hour = 0

            # Guard out-of-range values (e.g. a stray "at 25:70") — datetime.replace
            # raises ValueError on hour>23 / minute>59 and would crash the parser.
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None

            target_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target_dt <= now:
                # If time already passed today, schedule for tomorrow
                target_dt += timedelta(days=1)
            return target_dt.timestamp()

        return None

    def add_reminder(
        self,
        message: str,
        delay_seconds: Optional[int] = None,
        delay_minutes: Optional[float] = None,
        time_str: Optional[str] = None,
        reminder_type: str = "reminder"
    ) -> Dict[str, Any]:
        """Add a persistent scheduled reminder or countdown timer."""
        now = datetime.now()
        target_timestamp = None

        if delay_seconds is not None and delay_seconds > 0:
            target_timestamp = (now + timedelta(seconds=delay_seconds)).timestamp()
        elif delay_minutes is not None and delay_minutes > 0:
            target_timestamp = (now + timedelta(minutes=delay_minutes)).timestamp()
        elif time_str:
            target_timestamp = self.parse_time_offset(time_str)
            # Fail loudly on an unparseable explicit time instead of silently
            # scheduling +10 min and reporting success — "at 5:30 PM" that fails
            # to parse must not become a 10-minute reminder.
            if target_timestamp is None:
                raise ValueError(
                    f"Could not understand the time '{time_str}'. "
                    f"Try 'in 20 minutes' or 'at 5:30 PM'."
                )

        if not target_timestamp:
            # No time given at all — default to 10 minutes.
            target_timestamp = (now + timedelta(minutes=10)).timestamp()

        target_dt = datetime.fromtimestamp(target_timestamp)
        target_iso = target_dt.isoformat()
        created_iso = now.isoformat()

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO reminders (message, trigger_time_iso, trigger_timestamp, status, reminder_type, created_at)
                VALUES (?, ?, ?, 'pending', ?, ?)
            """, (message, target_iso, target_timestamp, reminder_type, created_iso))
            reminder_id = cursor.lastrowid
            conn.commit()

        remaining_secs = max(0, round(target_timestamp - time.time()))
        mins, secs = divmod(remaining_secs, 60)
        hours, mins = divmod(mins, 60)
        
        countdown_str = f"{mins}m {secs}s" if hours == 0 else f"{hours}h {mins}m"
        logger.info(f"[ReminderManager] Created {reminder_type} #{reminder_id}: '{message}' in {countdown_str} ({target_dt.strftime('%I:%M %p')})")

        return {
            "id": reminder_id,
            "message": message,
            "trigger_time": target_dt.strftime("%I:%M %p"),
            "countdown": countdown_str,
            "reminder_type": reminder_type
        }

    def list_pending(self) -> List[Dict[str, Any]]:
        """List all active, uncompleted reminders and countdown timers."""
        now_ts = time.time()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, message, trigger_time_iso, trigger_timestamp, reminder_type
                FROM reminders
                WHERE status = 'pending'
                ORDER BY trigger_timestamp ASC
            """)
            rows = cursor.fetchall()

        results = []
        for r in rows:
            rem_id, msg, dt_iso, trig_ts, r_type = r
            rem_secs = max(0, int(trig_ts - now_ts))
            mins, secs = divmod(rem_secs, 60)
            hours, mins = divmod(mins, 60)
            cd_str = f"{mins}m {secs}s" if hours == 0 else f"{hours}h {mins}m"
            dt_obj = datetime.fromisoformat(dt_iso)

            results.append({
                "id": rem_id,
                "message": msg,
                "trigger_time": dt_obj.strftime("%I:%M %p"),
                "countdown": cd_str,
                "type": r_type
            })
        return results

    def cancel(self, reminder_id: Optional[int] = None, keyword: Optional[str] = None) -> List[Dict[str, Any]]:
        """Cancel one or more pending reminders."""
        cancelled = []
        rows = []
        with self._connect() as conn:
            cursor = conn.cursor()
            if reminder_id is not None:
                cursor.execute("SELECT id, message FROM reminders WHERE id = ? AND status = 'pending'", (reminder_id,))
                rows = cursor.fetchall()
                cursor.execute("UPDATE reminders SET status = 'cancelled' WHERE id = ?", (reminder_id,))
            elif keyword:
                # Whole-word match, cancel by explicit id — a substring
                # `message LIKE '%keyword%'` sweep would cancel every partially
                # matching pending reminder (e.g. "call" hitting "recall the...").
                cursor.execute("SELECT id, message FROM reminders WHERE status = 'pending'")
                rows = [
                    r for r in cursor.fetchall()
                    if re.search(rf"\b{re.escape(keyword)}\b", r[1] or "", re.IGNORECASE)
                ]
                if rows:
                    ids = [r[0] for r in rows]
                    placeholders = ",".join(["?"] * len(ids))
                    cursor.execute(
                        f"UPDATE reminders SET status = 'cancelled' WHERE id IN ({placeholders})", ids
                    )
            else:
                # Neither id nor keyword given: cancel nothing rather than
                # destructively guessing the most-recent reminder.
                rows = []
            conn.commit()

        for r in rows:
            cancelled.append({"id": r[0], "message": r[1]})
            logger.info(f"[ReminderManager] Cancelled reminder #{r[0]}: '{r[1]}'")

        return cancelled

    def check_and_get_due_reminders(self) -> List[Dict[str, Any]]:
        """Fetch and mark all due reminders as completed."""
        now_ts = time.time()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, message, reminder_type
                FROM reminders
                WHERE status = 'pending' AND trigger_timestamp <= ?
            """, (now_ts,))
            due_rows = cursor.fetchall()

            if due_rows:
                ids = [r[0] for r in due_rows]
                cursor.execute(f"UPDATE reminders SET status = 'completed' WHERE id IN ({','.join(['?']*len(ids))})", ids)
                conn.commit()

        return [{"id": r[0], "message": r[1], "type": r[2]} for r in due_rows]

    def clean_stale_offline_reminders(self):
        """Mark any overdue reminders/timers from past sessions as expired so they don't trigger unexpectedly on startup."""
        now_ts = time.time()
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE reminders
                    SET status = 'expired'
                    WHERE status = 'pending' AND trigger_timestamp < ?
                """, (now_ts - 5,))
                expired_count = cursor.rowcount
                conn.commit()
                if expired_count > 0:
                    logger.info(f"[ReminderDaemon] Cleaned {expired_count} stale reminder(s) from past sessions.")
        except Exception as e:
            logger.error(f"[ReminderDaemon] Error cleaning stale reminders: {e}")

    # ── Background Daemon Runner ────────────────────────────────

    async def start_daemon(self, speech_callback=None):
        """Start background polling daemon for autonomous spoken alerts."""
        if self._is_running:
            return
        self._is_running = True
        self.clean_stale_offline_reminders()
        logger.info("[ReminderDaemon] Autonomous Spoken Reminder & Alarm Daemon active.")

        while self._is_running:
            try:
                # Offload the synchronous SQLite poll to a thread so a slow disk
                # or a locked DB never stalls the shared event loop.
                loop = asyncio.get_running_loop()
                due_list = await loop.run_in_executor(None, self.check_and_get_due_reminders)
                for item in due_list:
                    rem_id = item["id"]
                    msg = item["message"]
                    r_type = item["type"]

                    logger.info(f"[ReminderDaemon] 🔔 TRIGGERED {r_type.upper()} #{rem_id}: '{msg}'")

                    # 1. Play alert chime (in executor to avoid blocking event loop)
                    try:
                        loop = asyncio.get_running_loop()
                        def _play_chime():
                            play_chime(
                                frequencies=[1046, 1318, 1568],
                                durations_ms=[120, 120, 250],
                            )
                        await loop.run_in_executor(None, _play_chime)
                    except Exception:
                        pass

                    # 2. Synthesize and speak proactive reminder
                    if r_type == "timer":
                        alert_speech = f"Nandu, your timer for {msg} has finished!"
                    else:
                        alert_speech = f"Nandu, this is your reminder: {msg}!"

                    if speech_callback:
                        try:
                            await speech_callback(alert_speech)
                        except Exception as e:
                            logger.error(f"[ReminderDaemon] Voice playback error: {e}")

            except Exception as e:
                logger.debug(f"[ReminderDaemon] Loop error: {e}")

            await asyncio.sleep(2.0)

    def stop_daemon(self):
        self._is_running = False


reminder_manager = ReminderManager()
