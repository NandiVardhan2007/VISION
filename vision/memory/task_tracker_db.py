"""
VISION Task Tracker Database Layer.
Provides persistent storage, streak tracking, category analytics, and daily/monthly queries.
"""

import sqlite3
import os
import re
import calendar
from contextlib import contextmanager
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Iterator
from vision.logger import logger

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "task_tracker.sqlite")


class TaskTrackerDB:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_conn(self) -> Iterator[sqlite3.Connection]:
        """Yield a WAL-mode connection that commits/rolls back and always closes.

        Closing is required on Windows so the .sqlite file (and its -wal/-shm
        sidecars) are not held open, which otherwise causes WinError 32 on
        cleanup and blocks other writers.
        """
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'General',
                    priority TEXT NOT NULL DEFAULT 'Medium',
                    year INTEGER NOT NULL,
                    month TEXT NOT NULL,
                    month_num INTEGER NOT NULL,
                    day INTEGER NOT NULL,
                    is_completed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_date ON tasks(year, month_num, day)
            """)
            conn.commit()

    @staticmethod
    def get_current_date_info():
        now = datetime.now()
        months = ["January", "February", "March", "April", "May", "June", 
                  "July", "August", "September", "October", "November", "December"]
        return {
            "year": now.year,
            "month": months[now.month - 1],
            "month_num": now.month,
            "day": now.day
        }

    def add_task(self, title: str, day: Optional[int] = None, month: Optional[str] = None, 
                 year: Optional[int] = None, category: str = "General", priority: str = "Medium") -> Dict[str, Any]:
        curr = self.get_current_date_info()
        year = year or curr["year"]
        
        months = ["January", "February", "March", "April", "May", "June", 
                  "July", "August", "September", "October", "November", "December"]
        
        if month:
            month_clean = month.capitalize()
            if month_clean in months:
                month_name = month_clean
                month_num = months.index(month_clean) + 1
            elif month.isdigit() and 1 <= int(month) <= 12:
                month_num = int(month)
                month_name = months[month_num - 1]
            else:
                month_name = curr["month"]
                month_num = curr["month_num"]
        else:
            month_name = curr["month"]
            month_num = curr["month_num"]

        day = day or curr["day"]
        created_at = datetime.now().isoformat()

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tasks (title, category, priority, year, month, month_num, day, is_completed, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """, (title.strip(), category.capitalize(), priority.capitalize(), year, month_name, month_num, day, created_at))
            task_id = cursor.lastrowid
            conn.commit()

        logger.info(f"[TaskTrackerDB] Added task #{task_id}: '{title}' for {month_name} {day}, {year}")
        return self.get_task_by_id(task_id)

    def get_task_by_id(self, task_id: int) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row:
                return dict(row)
        return None

    def toggle_task(self, task_id: int, completed: Optional[bool] = None) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT is_completed FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                return None
            
            if completed is None:
                new_status = 0 if row["is_completed"] == 1 else 1
            else:
                new_status = 1 if completed else 0

            completed_at = datetime.now().isoformat() if new_status == 1 else None
            conn.execute("""
                UPDATE tasks 
                SET is_completed = ?, completed_at = ?
                WHERE id = ?
            """, (new_status, completed_at, task_id))
            conn.commit()

        logger.info(f"[TaskTrackerDB] Toggled task #{task_id} to completed={new_status}")
        return self.get_task_by_id(task_id)

    def complete_task_by_name(self, task_name: str, day: Optional[int] = None, month: Optional[str] = None, completed: bool = True) -> Optional[Dict[str, Any]]:
        curr = self.get_current_date_info()
        day = day or curr["day"]
        name = (task_name or "").lower().strip()
        if not name:
            return None
        like = f"%{name}%"

        def _rank(title: str) -> int:
            # 3 = exact title, 2 = whole-word hit, 1 = loose substring (the LIKE
            # filter already guarantees at least a substring match).
            t = (title or "").lower().strip()
            if t == name:
                return 3
            if re.search(rf"\b{re.escape(name)}\b", t):
                return 2
            return 1

        def _best(rows) -> Optional[int]:
            # Rank rows, then within the top rank prefer the most recently created
            # (highest id). Only auto-pick when it is an exact-title match or the
            # top rank is unambiguous; otherwise refuse to guess and complete the
            # wrong task (the old code always toggled an arbitrary LIKE row).
            if not rows:
                return None
            scored = sorted(((r["id"], _rank(r["title"])) for r in rows),
                            key=lambda x: (x[1], x[0]), reverse=True)
            top_rank = scored[0][1]
            top_ids = [rid for rid, rk in scored if rk == top_rank]
            if top_rank == 3 or len(top_ids) == 1:
                return top_ids[0]
            return None

        matched_id = None
        with self._get_conn() as conn:
            cursor = conn.cursor()
            # 1) Prefer tasks on the requested day (+ month, when given).
            query = "SELECT id, title FROM tasks WHERE LOWER(title) LIKE ? AND day = ?"
            params: List[Any] = [like, day]
            if month:
                query += " AND (LOWER(month) = ? OR month_num = ?)"
                params.extend([month.lower(), int(month) if month.isdigit() else 0])
            matched_id = _best(cursor.execute(query, params).fetchall())

            # 2) Fallback: search every day when nothing usable was found in scope.
            if matched_id is None:
                rows = cursor.execute(
                    "SELECT id, title FROM tasks WHERE LOWER(title) LIKE ?", (like,)
                ).fetchall()
                matched_id = _best(rows)

        if matched_id is not None:
            return self.toggle_task(matched_id, completed=completed)
        return None

    def delete_task(self, task_id: int) -> bool:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_tasks_for_day(self, day: Optional[int] = None, month: Optional[str] = None, year: Optional[int] = None) -> List[Dict[str, Any]]:
        curr = self.get_current_date_info()
        year = year or curr["year"]
        day = day or curr["day"]
        month_num = curr["month_num"]
        if month:
            months = ["January", "February", "March", "April", "May", "June", 
                      "July", "August", "September", "October", "November", "December"]
            if month.capitalize() in months:
                month_num = months.index(month.capitalize()) + 1
            elif month.isdigit():
                month_num = int(month)

        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM tasks 
                WHERE year = ? AND month_num = ? AND day = ?
                ORDER BY is_completed ASC, priority DESC, id ASC
            """, (year, month_num, day)).fetchall()
            return [dict(r) for r in rows]

    def ensure_daily_leetcode_tasks(self, year: Optional[int] = None, month_num: Optional[int] = None):
        """Ensure every day in the target month(s) has the Daily LeetCode habit scheduled.

        Uses one bulk existence query + one executemany instead of a
        SELECT-then-INSERT per day (previously up to ~730 queries per call).
        """
        curr = self.get_current_date_info()
        year = year or curr["year"]
        months = ["January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December"]
        leetcode_title = "Daily LeetCode Problem Solving (LeetCode / CodeChef / GFG)"

        target_months = [month_num] if month_num else list(range(1, 13))
        created_at = datetime.now().isoformat()

        with self._get_conn() as conn:
            cursor = conn.cursor()
            # Fetch the days that already have a LeetCode task in one query.
            if month_num:
                existing_rows = cursor.execute("""
                    SELECT month_num, day FROM tasks
                    WHERE year = ? AND month_num = ? AND LOWER(title) LIKE '%leetcode%'
                """, (year, month_num)).fetchall()
            else:
                existing_rows = cursor.execute("""
                    SELECT month_num, day FROM tasks
                    WHERE year = ? AND LOWER(title) LIKE '%leetcode%'
                """, (year,)).fetchall()
            existing = {(r["month_num"], r["day"]) for r in existing_rows}

            to_insert = []
            for m in target_months:
                m_name = months[m - 1]
                # Use the real day count for the month/year (not a blind 1..31)
                # so we never seed impossible dates like Feb 30 or Apr 31.
                days_in_month = calendar.monthrange(year, m)[1]
                for d in range(1, days_in_month + 1):
                    if (m, d) not in existing:
                        to_insert.append((leetcode_title, year, m_name, m, d, created_at))

            if to_insert:
                cursor.executemany("""
                    INSERT INTO tasks (title, category, priority, year, month, month_num, day, is_completed, created_at)
                    VALUES (?, 'Coding', 'High', ?, ?, ?, ?, 0, ?)
                """, to_insert)
            conn.commit()

    def get_tasks_for_month(self, month: Optional[str] = None, year: Optional[int] = None) -> List[Dict[str, Any]]:
        curr = self.get_current_date_info()
        year = year or curr["year"]
        month_num = curr["month_num"]
        if month:
            months = ["January", "February", "March", "April", "May", "June", 
                      "July", "August", "September", "October", "November", "December"]
            if month.capitalize() in months:
                month_num = months.index(month.capitalize()) + 1
            elif month.isdigit():
                month_num = int(month)

        self.ensure_daily_leetcode_tasks(year=year, month_num=month_num)

        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM tasks 
                WHERE year = ? AND month_num = ?
                ORDER BY day ASC, priority DESC, is_completed ASC, id ASC
            """, (year, month_num)).fetchall()
            return [dict(r) for r in rows]

    def get_all_tasks(self, year: Optional[int] = None) -> List[Dict[str, Any]]:
        curr = self.get_current_date_info()
        year = year or curr["year"]
        self.ensure_daily_leetcode_tasks(year=year)
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM tasks WHERE year = ? ORDER BY month_num ASC, day ASC, id ASC", (year,)).fetchall()
            return [dict(r) for r in rows]

    def calculate_streak(self, year: Optional[int] = None) -> int:
        """Calculate continuous consecutive completed days up to today.

        Aggregates all days in a single query, then walks backwards in Python
        instead of issuing one query per day (previously up to 365 queries).
        """
        today = date.today()
        streak = 0

        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT year, month_num, day,
                       COUNT(*) AS total, SUM(is_completed) AS completed
                FROM tasks
                GROUP BY year, month_num, day
            """).fetchall()

        by_day = {
            (r["year"], r["month_num"], r["day"]): (r["total"] or 0, r["completed"] or 0)
            for r in rows
        }

        for i in range(365):
            check_date = date.fromordinal(today.toordinal() - i)
            total, completed = by_day.get((check_date.year, check_date.month, check_date.day), (0, 0))

            if total > 0:
                if completed == total:
                    streak += 1
                else:
                    if i == 0:
                        continue
                    break
            else:
                if i == 0:
                    continue
                break
        return streak

    def calculate_leetcode_streak(self, year: Optional[int] = None) -> int:
        """Calculate consecutive days where the daily LeetCode task was solved.

        Single aggregate query + Python walk (was one query per day).
        """
        today = date.today()
        streak = 0

        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT year, month_num, day, MAX(is_completed) AS done
                FROM tasks
                WHERE LOWER(title) LIKE '%leetcode%'
                GROUP BY year, month_num, day
            """).fetchall()

        by_day = {(r["year"], r["month_num"], r["day"]): r["done"] for r in rows}

        for i in range(365):
            check_date = date.fromordinal(today.toordinal() - i)
            key = (check_date.year, check_date.month, check_date.day)
            if key in by_day:
                if by_day[key] == 1:
                    streak += 1
                else:
                    if i == 0:
                        # Today hasn't been solved yet, don't break streak
                        continue
                    break
            else:
                if i == 0:
                    continue
                break
        return streak

    def get_dashboard_summary(self, day: Optional[int] = None, month: Optional[str] = None, year: Optional[int] = None) -> Dict[str, Any]:
        curr = self.get_current_date_info()
        day = day or curr["day"]
        month_name = month or curr["month"]
        year = year or curr["year"]
        
        day_tasks = self.get_tasks_for_day(day=day, month=month_name, year=year)
        month_tasks = self.get_tasks_for_month(month=month_name, year=year)

        day_total = len(day_tasks)
        day_completed = sum(1 for t in day_tasks if t["is_completed"] == 1)
        day_pending = day_total - day_completed
        day_rate = round((day_completed / day_total * 100) if day_total > 0 else 0, 1)

        month_total = len(month_tasks)
        month_completed = sum(1 for t in month_tasks if t["is_completed"] == 1)
        month_pending = month_total - month_completed
        month_rate = round((month_completed / month_total * 100) if month_total > 0 else 0, 1)

        categories = {}
        days_map = {d: {"day": d, "total": 0, "completed": 0, "pending": 0, "completion_rate": 0.0, "tasks": []} for d in range(1, 32)}
        
        for t in month_tasks:
            cat = t["category"] or "General"
            if cat not in categories:
                categories[cat] = {"total": 0, "completed": 0}
            categories[cat]["total"] += 1
            if t["is_completed"] == 1:
                categories[cat]["completed"] += 1

            t_day = t["day"]
            if 1 <= t_day <= 31:
                days_map[t_day]["tasks"].append(t)
                days_map[t_day]["total"] += 1
                if t["is_completed"] == 1:
                    days_map[t_day]["completed"] += 1

        for d, d_data in days_map.items():
            d_data["pending"] = d_data["total"] - d_data["completed"]
            d_data["completion_rate"] = round((d_data["completed"] / d_data["total"] * 100) if d_data["total"] > 0 else 0, 1)

        streak = self.calculate_streak(year=year)
        leetcode_streak = self.calculate_leetcode_streak(year=year)
        leetcode_today_done = any(t["is_completed"] == 1 and "leetcode" in (t["title"] or "").lower() for t in day_tasks)
        leetcode_month_done = sum(1 for t in month_tasks if t["is_completed"] == 1 and "leetcode" in (t["title"] or "").lower())

        return {
            "selected_day": day,
            "selected_month": month_name,
            "year": year,
            "today_info": curr,
            "day_metrics": {
                "total": day_total,
                "completed": day_completed,
                "pending": day_pending,
                "completion_rate": day_rate,
                "tasks": day_tasks
            },
            "month_metrics": {
                "total": month_total,
                "completed": month_completed,
                "pending": month_pending,
                "completion_rate": month_rate,
                "category_breakdown": categories,
                "days_breakdown": days_map
            },
            "leetcode_metrics": {
                "streak": leetcode_streak,
                "today_done": leetcode_today_done,
                "month_solved": leetcode_month_done,
                "monthly_target": len(days_map)
            },
            "streak_days": streak,
            "productivity_score": month_rate
        }


# Singleton database instance
task_db = TaskTrackerDB()
