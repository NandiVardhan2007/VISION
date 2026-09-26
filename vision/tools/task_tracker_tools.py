"""
VISION Task Tracker & Excel Dashboard LLM Tools.
Allows VISION to manage tasks, toggle completions, generate summaries, and synchronize Excel workbooks.
"""

import os
from typing import Optional
from vision.tools.registry import tool
from vision.memory.task_tracker_db import task_db
from vision.tools.excel_tracker_engine import excel_tracker
from vision.logger import logger
from vision.platform import open_path


@tool(
    name="add_task",
    description="Add a new task or habit to the VISION Task Tracker for a specific day and month. Category can be 'Coding', 'Fitness', 'Study', 'Work', 'Habits', 'Personal'. Priority can be 'High', 'Medium', 'Low'."
)
def add_task(title: str, day: Optional[int] = None, month: Optional[str] = None, category: str = "General", priority: str = "Medium") -> str:
    """Add a new task to the tracker."""
    try:
        task = task_db.add_task(
            title=title,
            day=day,
            month=month,
            category=category,
            priority=priority
        )
        excel_note = "Excel tracker updated."
        try:
            excel_tracker.generate_workbook(year=task["year"])
        except PermissionError:
            logger.warning("[TaskTrackerTool] Excel file is currently open in another app. Saved to database.")
            excel_note = "Excel tracker is open in another app, so only the database was updated."
        except Exception as _e:
            logger.warning(f"[TaskTrackerTool] Excel refresh skipped: {_e}")
            excel_note = "Excel tracker could not be refreshed (saved to the database)."
        return f"Successfully added task #{task['id']}: '{task['title']}' for {task['month']} {task['day']}, {task['year']} (Category: {task['category']}, Priority: {task['priority']}). {excel_note}"
    except Exception as e:
        logger.error(f"[TaskTrackerTool] Error adding task: {e}")
        return f"Failed to add task: {str(e)}"


@tool(
    name="complete_task",
    description="Mark a task as completed or uncompleted by task name/keyword or task ID. Updates both the database and the Excel dashboard."
)
def complete_task(task_name_or_id: str, completed: bool = True, day: Optional[int] = None, month: Optional[str] = None) -> str:
    """Mark a task completed/uncompleted."""
    try:
        task = None
        ident = str(task_name_or_id).strip() if task_name_or_id is not None else ""
        if ident.isdigit():
            task = task_db.toggle_task(int(ident), completed=completed)
            if not task:
                # A numeric string may actually be (part of) a task title rather
                # than an ID; fall back to name matching before giving up.
                task = task_db.complete_task_by_name(task_name=task_name_or_id, day=day, month=month, completed=completed)
        else:
            task = task_db.complete_task_by_name(task_name=task_name_or_id, day=day, month=month, completed=completed)

        if not task:
            return f"Could not find a task matching '{task_name_or_id}'."

        status_str = "COMPLETED ✅" if task["is_completed"] == 1 else "PENDING ⏳"
        excel_note = "Excel dashboard refreshed."
        try:
            excel_tracker.generate_workbook(year=task["year"])
        except PermissionError:
            logger.warning("[TaskTrackerTool] Excel file is currently open in another app. Saved to database.")
            excel_note = "Excel dashboard is open in another app, so only the database was updated."
        except Exception as _e:
            logger.warning(f"[TaskTrackerTool] Excel refresh skipped: {_e}")
            excel_note = "Excel dashboard could not be refreshed (saved to the database)."
        return f"Task #{task['id']} '{task['title']}' marked as {status_str} for {task['month']} {task['day']}. {excel_note}"
    except Exception as e:
        logger.error(f"[TaskTrackerTool] Error toggling task: {e}")
        return f"Failed to toggle task: {str(e)}"


@tool(
    name="get_daily_tasks",
    description="List all scheduled tasks, daily LeetCode coding habits, categories, priorities, and completion status for today or a specific day. ALWAYS call this when the user asks 'what are my tasks', 'tasks today', 'tasks listed today', 'what do I have to do today', or 'list my tasks'."
)
def get_daily_tasks(day: Optional[int] = None, month: Optional[str] = None) -> str:
    """Retrieve daily tasks for today or a chosen day."""
    try:
        summary = task_db.get_dashboard_summary(day=day, month=month)
        metrics = summary["day_metrics"]
        tasks = metrics["tasks"]

        if not tasks:
            return f"No tasks scheduled for {summary['selected_month']} {summary['selected_day']}, {summary['year']}."

        lines = [
            f"📋 Tasks for {summary['selected_month']} {summary['selected_day']}, {summary['year']}:",
            f"Progress: {metrics['completed']}/{metrics['total']} completed ({metrics['completion_rate']}%) | Streak: {summary['streak_days']} Days 🔥",
            "───────────────────────────────────────────"
        ]
        for t in tasks:
            icon = "✅" if t["is_completed"] == 1 else "⬜"
            lines.append(f"{icon} #{t['id']} [{t['category']} | {t['priority']}] {t['title']}")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[TaskTrackerTool] Error listing daily tasks: {e}")
        return f"Failed to fetch tasks: {str(e)}"


@tool(
    name="get_productivity_summary",
    description="Get the overall productivity statistics, monthly completion rate, category breakdown, and current streak."
)
def get_productivity_summary(month: Optional[str] = None) -> str:
    """Get the full dashboard productivity overview."""
    try:
        summary = task_db.get_dashboard_summary(month=month)
        m_metrics = summary["month_metrics"]
        cats = m_metrics["category_breakdown"]

        lines = [
            f"📊 Productivity Summary for {summary['selected_month']} {summary['year']}:",
            f"• Total Tasks: {m_metrics['total']}",
            f"• Completed: {m_metrics['completed']} | Pending: {m_metrics['pending']}",
            f"• Monthly Success Rate: {m_metrics['completion_rate']}%",
            f"• Current Daily Streak: {summary['streak_days']} Consecutive Days 🔥",
            "\n📂 Category Breakdown:"
        ]
        for cat_name, cat_data in cats.items():
            rate = round((cat_data['completed'] / cat_data['total'] * 100) if cat_data['total'] > 0 else 0, 1)
            lines.append(f"  - {cat_name}: {cat_data['completed']}/{cat_data['total']} ({rate}%)")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[TaskTrackerTool] Error fetching summary: {e}")
        return f"Failed to get productivity summary: {str(e)}"


@tool(
    name="generate_excel_tracker",
    description="Regenerate and synchronize the colorful Excel Task Tracker spreadsheet workbook (.xlsx) with embedded Pie charts and KPI cards."
)
def generate_excel_tracker() -> str:
    """Generate or update the Excel workbook file."""
    try:
        path = excel_tracker.generate_workbook()
        return f"Excel Task Tracker successfully updated and saved at: {path}"
    except PermissionError:
        return f"Excel file '{excel_tracker.filepath}' is currently open in Excel. Please close it if you wish to overwrite."
    except Exception as e:
        logger.error(f"[TaskTrackerTool] Error generating excel tracker: {e}")
        return f"Failed to generate Excel tracker: {str(e)}"


@tool(
    name="open_excel_tracker",
    description="Open the VISION Task Tracker Excel spreadsheet (.xlsx) directly on your screen in Microsoft Excel or your default spreadsheet application."
)
def open_excel_tracker() -> str:
    """Open the generated Excel file on Windows."""
    try:
        path = excel_tracker.filepath
        try:
            excel_tracker.generate_workbook()
        except PermissionError:
            # File is already open in Excel, just proceed to open/focus it
            pass
        if os.path.exists(path):
            ok, msg = open_path(path)
            if ok:
                return f"Opening '{os.path.basename(path)}' in your spreadsheet app..."
            return f"Failed to open '{os.path.basename(path)}': {msg}"
        ok, msg = open_path(str(path))
        return f"Opening Task Tracker spreadsheet '{path}' on your screen." if ok else f"Failed to open spreadsheet: {msg}"
    except Exception as e:
        logger.error(f"[TaskTrackerTool] Error opening excel tracker: {e}")
        return f"Failed to open Excel tracker: {str(e)}"


@tool(
    name="log_leetcode_solved",
    description="Mark today's (or a specific day's) mandatory LeetCode / Coding problem as completed, increment your coding streak, and update the Excel tracker."
)
def log_leetcode_solved(day: Optional[int] = None, month: Optional[str] = None) -> str:
    """Mark daily LeetCode coding problem as completed."""
    try:
        curr = task_db.get_current_date_info()
        day = day or curr["day"]
        month_name = month or curr["month"]
        year = curr["year"]

        day_tasks = task_db.get_tasks_for_day(day=day, month=month_name, year=year)
        leetcode_task = next((t for t in day_tasks if "leetcode" in (t["title"] or "").lower()), None)

        if not leetcode_task:
            # Create and complete it
            new_task = task_db.add_task(
                title="Daily LeetCode Problem Solving (LeetCode / CodeChef / GFG)",
                day=day,
                month=month_name,
                year=year,
                category="Coding",
                priority="High"
            )
            task_db.toggle_task(new_task["id"], completed=True)
        else:
            task_db.toggle_task(leetcode_task["id"], completed=True)

        try:
            excel_tracker.generate_workbook()
        except PermissionError:
            pass
        except Exception as _e:
            logger.warning(f"[TaskTrackerTool] Excel refresh skipped: {_e}")

        streak = task_db.calculate_leetcode_streak(year=year)
        return f"🔥 Awesome job! Daily LeetCode problem marked as SOLVED for {month_name} {day}, {year}. Your Coding Streak is now **{streak} Day{'s' if streak != 1 else ''}**! 🚀 Keep the momentum going!"
    except Exception as e:
        logger.error(f"[TaskTrackerTool] Error logging LeetCode solved: {e}")
        return f"Failed to log LeetCode completion: {str(e)}"


@tool(
    name="get_leetcode_stats",
    description="Check your current LeetCode streak, total problems solved this month, and daily coding habit consistency."
)
def get_leetcode_stats() -> str:
    """Get coding and LeetCode habit statistics."""
    try:
        summary = task_db.get_dashboard_summary()
        lc = summary["leetcode_metrics"]
        return (
            f"🔥 **LeetCode & Problem Solving Stats:**\n"
            f"- **Current Streak:** {lc['streak']} Days 🔥\n"
            f"- **Today's Status:** {'✅ Solved' if lc['today_done'] else '⏳ Pending (Go solve at least 1 problem!)'}\n"
            f"- **Solved This Month:** {lc['month_solved']} / {lc['monthly_target']} Days\n"
            f"- **Platforms:** LeetCode, CodeChef, GeeksforGeeks"
        )
    except Exception as e:
        logger.error(f"[TaskTrackerTool] Error getting LeetCode stats: {e}")
        return f"Failed to get LeetCode stats: {str(e)}"
