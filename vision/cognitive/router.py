"""
Semantic Intent Classifier and Dynamic Tool Selection Router.
Selects only the top relevant tools for the user query, drastically reducing token usage
from ~5,000 tokens down to ~300 tokens and eliminating API rate limits.
"""

import re
from typing import List, Dict, Any, Set
from vision.logger import logger


DOMAIN_KEYWORD_MAP = {
    "hardware": {
        "keywords": ["volume", "sound", "audio", "mute", "unmute", "loud", "quiet", "brightness", "dim", "screen brightness", "lock", "lock screen", "lock pc", "lock workstation", "battery", "charge", "charging", "battery percentage", "power state", "hardware", "cpu usage", "ram usage", "system health", "hardware health", "disk usage", "free space"],
        "tools": ["set_volume", "increase_volume", "decrease_volume", "mute_volume", "unmute_volume", "get_volume_status", "set_brightness", "increase_brightness", "decrease_brightness", "get_brightness_status", "lock_screen", "lock_workstation", "get_battery_status", "get_hardware_health", "get_system_stats"]
    },
    "network": {
        "keywords": ["speedtest", "speed test", "internet speed", "download speed", "upload speed", "wifi", "wi-fi", "network", "signal", "ssid", "ping", "latency", "dns", "gateway", "ip address", "public ip", "connection speed"],
        "tools": ["test_internet_speed", "get_network_diagnostics", "ping_host"]
    },
    "window": {
        "keywords": ["window", "desktop", "minimize", "maximize", "restore", "snap", "close", "kill", "terminate", "switch to", "running apps", "show desktop"],
        "tools": ["show_desktop", "minimize_all_windows", "restore_windows", "close_application", "switch_to_window", "maximize_window", "snap_window", "list_running_applications"]
    },
    "input": {
        "keywords": ["write", "type", "note", "notepad", "draft", "shortcut", "press", "key", "save", "save note", "save document", "save it"],
        "tools": ["type_text_into_application", "press_keyboard_shortcut", "save_active_document", "create_or_write_file", "open_application"]
    },
    "whatsapp": {
        "keywords": [
            "whatsapp", "message", "msg", "chat", "send to", "text to", "contact",
            "send whatsapp", "draft message", "confirm send", "confirm message",
            "whatsapp templates", "send text"
        ],
        "tools": [
            "prepare_whatsapp_message", "confirm_and_send_whatsapp_draft",
            "get_pending_whatsapp_draft", "send_whatsapp_message",
            "get_quick_whatsapp_templates", "save_whatsapp_contact_alias"
        ]
    },
    "printer": {
        "keywords": ["print", "printer", "paper", "a4", "margin", "border", "copy", "copies", "pdf"],
        "tools": ["create_bordered_a4_document", "print_document", "create_and_print_bordered_document"]
    },
    "file": {
        "keywords": ["file", "folder", "directory", "downloads", "documents", "desktop", "desktop folder", "delete file", "move file", "rename", "organize", "organize downloads", "clean downloads", "organize desktop", "clean desktop", "tidy", "sort files", "save", "save file", "save in downloads", "save to"],
        "tools": ["organize_downloads", "organize_desktop", "organize_directory", "clean_empty_directories", "create_or_write_file", "list_files", "find_files", "open_file", "read_file_content", "rename_file", "move_file", "copy_file", "delete_file", "create_folder", "save_active_document"]
    },
    "web": {
        "keywords": ["weather", "temperature", "forecast", "search web", "browse", "internet", "google", "news", "online", "fetch"],
        "tools": ["search_web", "fetch_webpage_content", "get_weather_forecast"]
    },
    "system": {
        "keywords": ["open", "launch", "start", "time", "date", "clock", "cpu", "ram", "battery", "stats", "screen", "screenshot"],
        "tools": ["open_application", "get_current_time_and_date", "get_system_stats", "read_screen", "get_battery_status", "get_hardware_health"]
    },
    "memory": {
        "keywords": [
            "remember", "memory", "memories", "recall", "forget", "know about me", "details",
            "my details", "about me", "age", "born", "birthday", "who am i", "my name",
            "college", "address", "my address", "mother", "father", "friends", "cache", "stats",
            "list memories", "clear cache", "knowledge graph", "relationship", "relations",
            "connected to", "how is", "related to", "learn rule", "procedural rule", "past events", "history"
        ],
        "tools": [
            "remember_fact", "recall_memory", "forget_memory", "list_all_memories",
            "get_cache_stats", "clear_system_cache", "query_knowledge_graph",
            "add_entity_relation", "learn_user_rule", "list_procedural_rules", "search_past_events"
        ]
    },
    "briefing": {
        "keywords": [
            "morning briefing", "daily briefing", "briefing", "daily routine", "today briefing",
            "morning routine", "daily summary", "what is on my plate today", "quick status", "how does my day look"
        ],
        "tools": [
            "get_daily_morning_briefing", "get_quick_daily_status", "get_college_timetable",
            "get_mid_exam_schedule", "get_current_time_and_date"
        ]
    },
    "code_execution": {
        "keywords": [
            "run code", "execute code", "run java", "compile java", "run python", "run program",
            "run script", "compile", "javac", "g++", "gcc", "stdin", "give input", "fix error",
            "fix the error", "debug code", "code error", "exception", "traceback", "fix bug",
            "repair code", "java project", "run this code"
        ],
        "tools": [
            "run_code_with_input", "diagnose_and_fix_code_error", "compile_and_run_java_project",
            "execute_terminal_command", "run_python_code"
        ]
    },
    "media": {
        "keywords": [
            "play", "song", "music", "youtube", "video", "track", "audio",
            "fullscreen", "full screen", "forward", "rewind", "seek", "skip", "fast forward",
            "pause", "resume", "mute", "unmute", "comet", "comet browser", "vishwanath and sons"
        ],
        "tools": [
            "play_youtube_video", "play_media", "control_youtube_playback",
            "set_youtube_fullscreen", "seek_youtube_video", "open_application"
        ]
    },
    "email": {
        "keywords": [
            "email", "emails", "mail", "mails", "send mail", "compose", "college mails", "college mail",
            "check my college mails", "check college mails", "check college email", "check college emails",
            "outlook", "outlook mails", "outlook mail", "check my outlook", "check outlook", "unread mails",
            "unread emails", "inbox", "college inbox", "check my inbox", "move to bin", "move to the bin",
            "move them to the bin", "delete promotional mails", "confirm move", "clean inbox", "pending review"
        ],
        "tools": [
            "check_college_outlook_emails", "confirm_move_emails_to_bin", "get_pending_email_review",
            "send_email", "open_website"
        ]
    },
    "mobile": {
        "keywords": ["phone", "mobile", "android", "adb", "unlock phone"],
        "tools": ["connect_phone", "unlock_phone", "launch_mobile_app", "tap_phone_screen"]
    },
    "terminal": {
        "keywords": ["terminal", "command prompt", "cmd", "powershell", "execute command", "run command", "run terminal", "run script", "git status", "pip install", "npm install", "ssh to", "ssh server", "connect to server", "connect to ssh", "remote server"],
        "tools": ["connect_to_ssh_server", "execute_terminal_command", "run_python_code", "git_status_and_summary"]
    },
    "clipboard_translation": {
        "keywords": ["clipboard", "copied", "paste", "copy to clipboard", "translate", "telugu", "hindi", "tamil", "spanish", "translation", "in telugu", "in hindi", "in english"],
        "tools": ["read_clipboard", "write_to_clipboard", "translate_text"]
    },
    "browser": {
        "keywords": [
            "browser", "website", "open site", "github", "leetcode", "youtube", "gmail",
            "chatgpt", "google search", "search youtube", "download", "download file",
            "web page", "click", "click on", "fill form", "type on", "type in", "press enter",
            "scroll", "scroll down", "scroll up", "interactive elements", "inspect page",
            "browser screenshot", "page screenshot", "web browser", "browse", "navigate to",
            "close browser", "back", "forward", "webpage content", "hover", "select dropdown",
            "browser tabs", "switch tab", "browser task", "autonomous browse", "web agent"
        ],
        "tools": [
            "browser_autonomous_task", "browser_fill_form_and_login", "browser_open",
            "browser_navigate", "browser_click", "browser_type", "browser_hover",
            "browser_select_option", "browser_press_key", "browser_scroll",
            "browser_get_page_content", "browser_get_interactive_elements",
            "browser_take_screenshot", "browser_list_tabs", "browser_switch_tab",
            "browser_back", "browser_forward", "browser_close",
            "open_website", "search_youtube_videos", "search_google_web", "download_file_from_url"
        ]
    },
    "power_process": {
        "keywords": ["kill", "terminate", "force close", "kill process", "sleep", "sleep pc", "lock", "lock pc", "lock workstation", "lock screen", "workstation", "shutdown", "restart", "cancel shutdown", "recycle", "recycle bin", "empty bin", "bin", "trash", "clean trash"],
        "tools": ["kill_process_by_name", "lock_workstation", "lock_screen", "sleep_pc", "empty_recycle_bin", "shutdown_pc", "restart_pc", "cancel_shutdown"]
    },
    "archive": {
        "keywords": ["zip", "unzip", "compress", "extract", "tar", "archive", "compress folder", "extract zip"],
        "tools": ["compress_to_zip", "extract_zip_archive"]
    },
    "reminder": {
        "keywords": ["remind", "reminder", "remind me", "timer", "alarm", "countdown", "set timer", "set reminder", "cancel reminder", "cancel timer", "my reminders", "active reminders"],
        "tools": ["set_voice_reminder", "set_timer", "list_active_reminders", "cancel_reminder", "get_current_time_and_date"]
    },
    "interview": {
        "keywords": ["interview", "mock interview", "interview prep", "prepare for interview", "interview question", "interview practice", "evaluate answer", "end interview", "technical interview", "hr interview", "mock interview session"],
        "tools": ["start_mock_interview", "evaluate_interview_answer", "end_mock_interview"]
    },
    "multi_agent": {
        "keywords": ["autonomous goal", "multi-step", "decompose", "swarm", "research and write", "research and save", "research and email", "multi agent", "plan and execute", "plan task", "complex workflow", "execute goal", "upgrades", "new upgrades", "new features", "what can you do", "your capabilities", "what are your features"],
        "tools": ["execute_autonomous_multi_agent_goal", "get_autonomous_goal_status"]
    },
    "remote_server": {
        "keywords": [
            "server", "ubuntu", "ubuntu server", "hyderabad server", "kpr", "parking",
            "parking logs", "parking print", "kpr print", "server health", "check server",
            "clear logs", "clear parking logs", "restart kpr", "restart print server",
            "restart parking", "print server", "ssh", "ssh command", "remote command",
            "100.93.70.63", "kpr_print.log"
        ],
        "tools": [
            "check_ubuntu_server_health", "check_parking_logs", "clear_parking_logs",
            "restart_kpr_print_system", "ssh_execute_command", "open_interactive_ssh_terminal",
            "open_parking_logs_terminal"
        ]
    },
    "academic": {
        "keywords": [
            "timetable", "class", "classes", "schedule", "period", "lab", "assignment", "assignments",
            "homework", "deadline", "submission", "due", "next class", "today class", "today classes",
            "exam", "exams", "mid exam", "mid-1", "mid 1", "mid exams", "sessional", "dmdw", "atcd",
            "a.java", "advanced java", "fsd", "thub", "edc", "computer networks", "aditya college",
            "it section a", "room 221"
        ],
        "tools": [
            "get_college_timetable", "get_mid_exam_schedule", "get_next_upcoming_class",
            "add_college_assignment", "list_college_assignments", "mark_assignment_done",
            "get_current_time_and_date"
        ]
    },
    "task_tracker": {
        "keywords": [
            "task", "tasks", "task tracker", "tracker", "excel tracker", "task tracker excel",
            "todo", "todos", "to-do", "to do", "today task", "today tasks", "tasks today",
            "tasks listed", "what are the tasks", "what are my tasks", "list tasks", "my tasks",
            "complete task", "mark task", "check off task", "add task", "new task",
            "schedule task", "habit", "habits", "leetcode", "lead code", "leet code", "quidco",
            "dsa", "codechef", "geeksforgeeks", "gfg", "problem solving", "coding challenge",
            "productivity", "streak", "my streak", "coding streak", "leetcode streak",
            "open tracker", "open excel tracker", "sync excel", "excel sheet", "tasktracker"
        ],
        "tools": [
            "get_daily_tasks", "get_productivity_summary", "add_task", "complete_task",
            "log_leetcode_solved", "get_leetcode_stats", "generate_excel_tracker",
            "open_excel_tracker", "get_current_time_and_date"
        ]
    }
}

# Core fallback tools when general system intent is detected but ambiguous
CORE_DEFAULT_TOOLS = [
    "open_application", "get_current_time_and_date", "get_system_stats",
    "show_desktop", "close_application"
]

CONVERSATIONAL_EXACT = {
    "hi", "hello", "hey", "hey vision", "good morning", "good evening", "good night",
    "how are you", "who are you", "what about you", "thank you", "thanks", "bye",
    "goodbye", "see you", "i am his sister", "nice to meet you", "could you ask again",
    "could you ask again please", "ask again", "yes", "no", "yeah", "ok", "okay"
}


class IntentRouter:
    def route_tools(self, user_query: str, all_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter down all registered tool schemas to only the most relevant tools."""
        q_lower = user_query.lower().strip()
        
        # 1. Pure conversational greetings / casual phrases don't need tools.
        # Match on whole leading tokens, NOT startswith: "hey lock pc" / "hi mute
        # volume" begin with a greeting word but are real commands and must keep
        # their tools. Multi-word greetings are covered by CONVERSATIONAL_EXACT.
        tokens = q_lower.split()
        first_tok = tokens[0] if tokens else ""
        _GREETING_WORDS = {"hi", "hello", "hey", "bye", "hola", "yo", "sup", "goodbye", "thanks"}
        if q_lower in CONVERSATIONAL_EXACT or (len(tokens) <= 2 and first_tok in _GREETING_WORDS):
            logger.debug(f"[Router] Conversational query detected -> 0 tools for query: '{user_query[:35]}...'")
            return []

        matched_tool_names: Set[str] = set()

        for domain, info in DOMAIN_KEYWORD_MAP.items():
            for kw in info["keywords"]:
                kw_l = kw.lower()
                # A trailing/leading \b next to a non-word char (e.g. "g++")
                # can never match; only apply the boundary on alphanumeric edges.
                left = r"\b" if kw_l[:1].isalnum() else ""
                right = r"\b" if kw_l[-1:].isalnum() else ""
                if re.search(rf"{left}{re.escape(kw_l)}{right}", q_lower):
                    matched_tool_names.update(info["tools"])
                    break

        # If no specific domain matched, check if query contains any action intent
        action_intent_words = ["open", "close", "launch", "run", "start", "show", "time", "date", "battery", "stats"]
        has_action_intent = any(w in q_lower.split() for w in action_intent_words)

        if not matched_tool_names:
            if has_action_intent:
                matched_tool_names.update(CORE_DEFAULT_TOOLS)
            else:
                # Casual social chat / dialogue with no action intent: pass no tools
                return []

        # Filter schema dicts
        schema_map = {
            t.get("function", {}).get("name"): t
            for t in all_tools if t.get("function", {}).get("name")
        }

        selected_schemas = [
            schema_map[name]
            for name in matched_tool_names
            if name in schema_map
        ]

        logger.debug(f"[Router] Filtered {len(all_tools)} tools -> {len(selected_schemas)} relevant tools for query: '{user_query[:35]}...'")
        return selected_schemas


router = IntentRouter()
