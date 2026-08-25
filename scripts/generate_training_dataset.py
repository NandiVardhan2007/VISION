"""
Comprehensive Training Dataset Generator for VISION.
Generates multi-domain, multi-turn, and single-turn tool calling datasets in standard
OpenAI Function Calling / ChatML format covering all registered tools in VISION.
"""

import sys
import json
import random
from pathlib import Path
from typing import List, Dict, Any

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vision.tools import *  # noqa: F401,F403 — registers all tools on import
from vision.tools.registry import tool_registry
from vision.constants import DEFAULT_SYSTEM_PROMPT

DATASETS_DIR = PROJECT_ROOT / "data" / "datasets"
DATASETS_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42

# Common human conversational variations
GREETINGS_NEGATIVE_PROMPTS = [
    ("Hey Vision, how are you doing today?", "I'm doing great and fully operational! How can I assist you right now?"),
    ("Good morning Vision!", "Good morning, Nandu! I hope you have a productive day ahead. What's on your agenda?"),
    ("Who created you and what is your purpose?", "I am VISION, an autonomous multimodal AI operating system designed for ultra-low latency voice interaction, desktop automation, and intelligent task management."),
    ("Tell me a funny joke about programming.", "Why do programmers prefer dark mode? Because light attracts bugs!"),
    ("Can you explain how Voice Activity Detection works?", "Voice Activity Detection (VAD) analyzes continuous audio streams in real-time to detect the presence or absence of human speech, separating actual voice from background noise using neural networks or energy thresholds."),
    ("What is the difference between TCP and UDP?", "TCP is a connection-oriented protocol that guarantees packet delivery and ordering through handshakes, whereas UDP is connectionless and prioritized for ultra-low latency streaming without retransmission overhead."),
    ("Thank you Vision, that helped a lot.", "You're very welcome! Let me know whenever you need anything else."),
    ("Tell me about quantum computing in simple terms.", "Quantum computing uses quantum bits (qubits) that can exist in superpositions of 0 and 1 simultaneously, allowing them to solve certain complex mathematical and cryptographic problems exponentially faster than classical computers."),
]

# Dedicated Hand-Crafted High-Quality Exemplars per tool domain
DOMAIN_SPECIFIC_TEMPLATES = {
    "academic": [
        ("What is my college timetable for today?", "get_college_timetable", {}),
        ("Show me the schedule for Wednesday", "get_college_timetable", {"day_name": "Wednesday"}),
        ("What is my next upcoming class?", "get_next_upcoming_class", {}),
        ("When is my next mid exam scheduled?", "get_mid_exam_schedule", {}),
        ("Add a new college assignment for Machine Learning due next Monday", "add_college_assignment", {"subject": "Machine Learning", "title": "Supervised Learning Lab Report", "due_date_time": "next Monday 5 PM"}),
        ("List all my pending college assignments", "list_college_assignments", {}),
        ("Mark assignment 1 as completed", "mark_assignment_done", {"assignment_id_or_title": "1"}),
    ],
    "hardware": [
        ("Set volume to 60 percent", "set_volume", {"level": 60}),
        ("Turn up the volume", "increase_volume", {"step": 10}),
        ("Lower the volume by 15 percent", "decrease_volume", {"step": 15}),
        ("Mute the audio", "mute_volume", {}),
        ("Unmute sound", "unmute_volume", {}),
        ("Check current volume level", "get_volume_status", {}),
        ("Set screen brightness to 75", "set_brightness", {"level": 75}),
        ("Increase brightness a bit", "increase_brightness", {"step": 10}),
        ("Dim the screen brightness", "decrease_brightness", {"step": 15}),
        ("Lock my workstation immediately", "lock_workstation", {}),
        ("What is my current battery status?", "get_battery_status", {}),
        ("Give me hardware health status", "get_hardware_health", {}),
    ],
    "network": [
        ("Run an internet speed test", "test_internet_speed", {}),
        ("Check network connection diagnostics", "get_network_diagnostics", {}),
        ("Ping 8.8.8.8 to check latency", "ping_host", {"host": "8.8.8.8"}),
        ("Ping google.com", "ping_host", {"host": "google.com", "count": 4}),
    ],
    "window": [
        ("Show my desktop", "show_desktop", {}),
        ("Minimize all open windows", "minimize_all_windows", {}),
        ("Restore all minimized windows", "restore_windows", {}),
        ("Snap this window to the left side", "snap_window", {"direction": "left"}),
        ("Maximize the current window", "maximize_window", {}),
        ("Switch to Chrome", "switch_to_window", {"app_name": "Chrome"}),
        ("List all running applications", "list_running_applications", {}),
        ("Close Notepad", "close_application", {"app_name": "notepad"}),
    ],
    "input": [
        ("Type 'Hello World' into the active window", "type_text_into_application", {"text": "Hello World"}),
        ("Press shortcut Ctrl+S to save", "press_keyboard_shortcut", {"shortcut": "ctrl+s"}),
        ("Save the active document", "save_active_document", {}),
    ],
    "system": [
        ("Open Chrome browser", "open_application", {"app_name": "chrome"}),
        ("Launch Visual Studio Code", "open_application", {"app_name": "code"}),
        ("What is the current time and date?", "get_current_time_and_date", {}),
        ("What are the system stats for CPU and RAM?", "get_system_stats", {}),
        ("Read what is on my screen right now", "read_screen", {}),
    ],
    "whatsapp": [
        ("Draft a WhatsApp message to Nani saying 'Hey, let's meet tomorrow at 10 AM'", "prepare_whatsapp_message", {"contact_or_number": "Nani", "message": "Hey, let's meet tomorrow at 10 AM"}),
        ("Confirm and send the pending WhatsApp draft", "confirm_and_send_whatsapp_draft", {}),
        ("Check if there are any pending WhatsApp drafts", "get_pending_whatsapp_draft", {}),
        ("Show me quick WhatsApp reply templates", "get_quick_whatsapp_templates", {}),
        ("Save WhatsApp contact alias for Mom with phone number +91999993210", "save_whatsapp_contact_alias", {"alias": "Mom", "saved_name": "+91999993210"}),
    ],
    "code_execution": [
        ("Run this python code: print('Training Vision Model')", "run_code_with_input", {"code_or_file_path": "print('Training Vision Model')", "language": "python"}),
        ("Diagnose and fix this error in app.py: IndexError: list index out of range", "diagnose_and_fix_code_error", {"file_path": "D:/Projects/app.py", "error_message": "IndexError: list index out of range"}),
        ("Compile and run Java project at D:/Projects/App", "compile_and_run_java_project", {"project_directory": "D:/Projects/App"}),
    ],
    "tasks_and_tracking": [
        ("Add a new task 'Complete Cloud Assignment' with priority high", "add_task", {"title": "Complete Cloud Assignment", "priority": "high", "category": "College"}),
        ("Mark task 3 as completed", "complete_task", {"task_name_or_id": "3"}),
        ("Show me my daily tasks for today", "get_daily_tasks", {}),
        ("Generate an Excel tracker report for my weekly progress", "generate_excel_tracker", {}),
        ("Open the task tracker Excel file", "open_excel_tracker", {}),
        ("Log today's LeetCode problem as solved", "log_leetcode_solved", {}),
        ("Show my LeetCode problem solving stats", "get_leetcode_stats", {}),
    ],
    "remote_server": [
        ("Run 'uptime' on Ubuntu server via SSH", "ssh_execute_command", {"command": "uptime"}),
        ("Check the health of my Ubuntu server", "check_ubuntu_server_health", {}),
        ("Check the KPR parking print system logs", "check_parking_logs", {"lines": 50, "open_terminal": False}),
        ("Clear old parking print logs on the server", "clear_parking_logs", {}),
        ("Restart the KPR printing service on the remote server", "restart_kpr_print_system", {}),
        ("Open an interactive SSH terminal session", "open_interactive_ssh_terminal", {}),
    ],
    "memory": [
        ("Remember that my mother's birthday is on October 14th", "remember_fact", {"fact": "My mother's birthday is on October 14th", "category": "family"}),
        ("What is my mother's birthday?", "recall_memory", {"query": "mother's birthday"}),
        ("List all stored memories about my family", "list_all_memories", {}),
        ("Query knowledge graph for connections with College", "query_knowledge_graph", {"entity_name": "College"}),
        ("Show cache memory statistics", "get_cache_stats", {}),
    ],
    "briefing": [
        ("Give me my morning briefing", "get_daily_morning_briefing", {}),
        ("Give me a quick status update on today's schedule and tasks", "get_quick_daily_status", {}),
    ],
    "reminders": [
        ("Set a voice reminder to submit the assignment at 5 PM", "set_voice_reminder", {"reminder_text": "Submit the assignment", "time_str": "17:00"}),
        ("Set a timer for 15 minutes", "set_timer", {"duration_minutes": 15, "timer_label": "Tea Break"}),
        ("List all my active reminders", "list_active_reminders", {}),
        ("Cancel reminder with ID 2", "cancel_reminder", {"reminder_id": 2}),
    ],
    "files": [
        ("Organize my Downloads folder by file type", "organize_downloads", {}),
        ("Clean up and organize my Desktop", "organize_desktop", {}),
        ("Find files named notes in my Downloads", "find_files", {"name_query": "notes", "directory": "Downloads"}),
        ("Compress D:/College/Notes into a zip archive named notes.zip in Downloads", "compress_to_zip", {"source_path": "D:/College/Notes", "output_zip_name": "notes.zip", "destination_folder": "Downloads"}),
        ("Delete file D:/Temp/sample.txt", "delete_file", {"file_path": "D:/Temp/sample.txt"}),
    ]
}


# Multi-turn conversation trajectories: sequences of (user_utterance, tool_name, args).
# Module-level so tests and validators can introspect them.
MULTI_TURN_CHAINS = [
    [
        ("Check what's on my screen", "read_screen", {}),
        ("Diagnose and fix the code error in app.py", "diagnose_and_fix_code_error", {"file_path": "D:/Projects/app.py", "error_message": "NullPointer"}),
        ("Run the python script", "run_code_with_input", {"code_or_file_path": "print('hello')", "language": "python"})
    ],
    [
        ("What classes do I have today?", "get_college_timetable", {}),
        ("Add an assignment for Cloud Computing due tomorrow", "add_college_assignment", {"subject": "Cloud Computing", "title": "AWS Lab", "due_date_time": "tomorrow 5pm"}),
        ("Set a reminder to complete the Cloud assignment at 7 PM", "set_voice_reminder", {"reminder_text": "Complete Cloud AWS Lab assignment", "time_str": "19:00"})
    ],
    [
        ("Draft a WhatsApp message to Sai saying 'Are you coming to college today?'", "prepare_whatsapp_message", {"contact_or_number": "Sai", "message": "Are you coming to college today?"}),
        ("Yes, confirm and send it", "confirm_and_send_whatsapp_draft", {})
    ],
    [
        ("Check how my Ubuntu server is performing", "check_ubuntu_server_health", {}),
        ("Run systemctl status nginx on the server", "ssh_execute_command", {"command": "systemctl status nginx"})
    ]
]


def build_tool_call_message(tool_name: str, arguments: Dict[str, Any], call_id: str = "call_01") -> Dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": tool_name,
            "arguments": json.dumps(arguments)
        }
    }


def validate_args_against_schema(tool_name: str, args: Dict[str, Any], schema_map: Dict[str, Any]) -> List[str]:
    """Returns a list of schema violations for the given arguments. Empty list = valid."""
    errors: List[str] = []
    if tool_name not in schema_map:
        return [f"Unknown tool '{tool_name}'."]
    fn = schema_map[tool_name]["function"]
    params = fn.get("parameters", {})
    props: Dict[str, Any] = params.get("properties", {})
    required = params.get("required", [])

    # Extra keys not in the schema
    for key in args:
        if key not in props:
            errors.append(f"Unexpected argument '{key}' for '{tool_name}'.")

    type_checkers = {
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: (isinstance(v, (int, float)) and not isinstance(v, bool)),
        "boolean": lambda v: isinstance(v, bool),
        "array": lambda v: isinstance(v, list),
        "object": lambda v: isinstance(v, dict),
    }

    for req in required:
        if req not in args:
            errors.append(f"Missing required param '{req}' for '{tool_name}'.")
            continue
        expected_type = props.get(req, {}).get("type", "string")
        checker = type_checkers.get(expected_type)
        if checker and not checker(args[req]):
            errors.append(f"Param '{req}' for '{tool_name}' should be {expected_type}, got {type(args[req]).__name__}.")
    return errors


def sanitize_tool_args(tool_name: str, args: Dict[str, Any], schema_map: Dict[str, Any]) -> Dict[str, Any]:
    """Auto-heals missing required parameters with plausible typed values."""
    if tool_name not in schema_map:
        return args
    fn = schema_map[tool_name]["function"]
    props = fn.get("parameters", {}).get("properties", {})
    required = fn.get("parameters", {}).get("required", [])

    clean = {k: v for k, v in args.items() if k in props}
    for req in required:
        if req in clean:
            continue
        prop_type = props.get(req, {}).get("type", "string")
        if prop_type == "string":
            clean[req] = f"sample_{req}"
        elif prop_type in ["integer", "number"]:
            clean[req] = 50
        elif prop_type == "boolean":
            clean[req] = True
        elif prop_type == "array":
            clean[req] = ["sample_item"]
        else:
            clean[req] = {}
    return clean


def synthesize_synthetic_dataset(num_samples: int = 5000, seed: int = SEED) -> List[Dict[str, Any]]:
    """Synthesizes a rich, diverse training dataset across all tools and categories."""
    rng = random.Random(seed)
    dataset: List[Dict[str, Any]] = []
    all_schemas = tool_registry.get_all_schemas()
    schema_map = {s["function"]["name"]: s for s in all_schemas}

    print(f"[*] Introspected {len(all_schemas)} total tools from registry.")

    def pick_distractors(exclude_names: set, count: int) -> List[Dict[str, Any]]:
        pool = [s for s in all_schemas if s["function"]["name"] not in exclude_names]
        return rng.sample(pool, min(count, len(pool)))

    skipped_templates = 0

    # 1. Add Hand-Crafted Exemplars (strictly validated — bad templates fail loudly)
    for domain, examples in DOMAIN_SPECIFIC_TEMPLATES.items():
        for user_prompt, tool_name, args in examples:
            if tool_name not in schema_map:
                print(f"[!] Skipping template: unknown tool '{tool_name}' ({domain}).")
                skipped_templates += 1
                continue
            clean_args = sanitize_tool_args(tool_name, args, schema_map)
            errors = validate_args_against_schema(tool_name, clean_args, schema_map)
            if errors:
                raise ValueError(
                    f"Hand-crafted template for '{tool_name}' violates schema: {errors}"
                    f" (prompt: {user_prompt!r})"
                )

            distractors = pick_distractors({tool_name}, 4)
            available_tools = [schema_map[tool_name]] + distractors
            rng.shuffle(available_tools)

            call_id = f"call_{tool_name}_{rng.randint(1000, 9999)}"
            record = {
                "messages": [
                    {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [build_tool_call_message(tool_name, clean_args, call_id)]
                    },
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": tool_name,
                        "content": json.dumps({"status": "success", "result": f"Executed {tool_name} successfully."})
                    },
                    {
                        "role": "assistant",
                        "content": f"I have executed {tool_name.replace('_', ' ')}."
                    }
                ],
                "tools": available_tools
            }
            dataset.append(record)

    # 2. Add Multi-Turn Trajectories
    multi_turn_chains = MULTI_TURN_CHAINS

    for chain in multi_turn_chains:
        messages: List[Dict[str, Any]] = [{"role": "system", "content": DEFAULT_SYSTEM_PROMPT}]
        active_tools: List[Dict[str, Any]] = []
        valid_chain = True
        for user_msg, t_name, t_args in chain:
            if t_name not in schema_map:
                print(f"[!] Dropping multi-turn chain step: unknown tool '{t_name}'.")
                valid_chain = False
                break
            active_tools.append(schema_map[t_name])
            clean_args = sanitize_tool_args(t_name, t_args, schema_map)
            errors = validate_args_against_schema(t_name, clean_args, schema_map)
            if errors:
                raise ValueError(f"Multi-turn template for '{t_name}' violates schema: {errors}")
            cid = f"call_{t_name}_{rng.randint(100, 999)}"
            messages.append({"role": "user", "content": user_msg})
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [build_tool_call_message(t_name, clean_args, cid)]
            })
            messages.append({
                "role": "tool",
                "tool_call_id": cid,
                "name": t_name,
                "content": json.dumps({"status": "success", "result": f"Completed {t_name}"})
            })
            messages.append({
                "role": "assistant",
                "content": f"Completed {t_name.replace('_', ' ')}."
            })

        if not valid_chain:
            continue

        exclude = {s["function"]["name"] for s in active_tools}
        distractors = pick_distractors(exclude, 3)
        all_avail = active_tools + distractors
        rng.shuffle(all_avail)
        dataset.append({
            "messages": messages,
            "tools": all_avail
        })

    # 3. Add Negative Examples (Pure Conversational QA -> Zero Tool Calls)
    for q, a in GREETINGS_NEGATIVE_PROMPTS:
        sample_tools = rng.sample(all_schemas, min(6, len(all_schemas)))
        dataset.append({
            "messages": [
                {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
                {"role": "user", "content": q},
                {"role": "assistant", "content": a}
            ],
            "tools": sample_tools
        })

    # 4. Automated Combinatorial Synthesizer for ALL Registered Tools
    print(f"[*] Generating combinatorial synthetic samples to reach target size {num_samples}...")
    variations_per_tool = max(25, num_samples // max(1, len(all_schemas)))

    for tool_name, schema in schema_map.items():
        fn = schema["function"]
        props = fn.get("parameters", {}).get("properties", {})
        required = fn.get("parameters", {}).get("required", [])

        for i in range(variations_per_tool):
            sample_args: Dict[str, Any] = {}
            for p_name, p_spec in props.items():
                p_type = p_spec.get("type", "string")
                if p_name in required or rng.random() > 0.35:
                    if p_type == "string":
                        if "path" in p_name or "file" in p_name or "directory" in p_name:
                            sample_args[p_name] = f"D:/VISION/data/{p_name}_{i}.txt"
                        elif "time" in p_name or "date" in p_name or "delay" in p_name:
                            sample_args[p_name] = "18:30"
                        elif "name" in p_name or "recipient" in p_name or "alias" in p_name:
                            sample_args[p_name] = rng.choice(["Nandu", "Kovvuri", "Sai", "College", "HOD", "Admin"])
                        elif "subject" in p_name:
                            sample_args[p_name] = rng.choice(["Cloud Computing", "Machine Learning", "Data Mining", "Cybersecurity"])
                        else:
                            sample_args[p_name] = f"val_{p_name}_{i}"
                    elif p_type in ["integer", "number"]:
                        if "level" in p_name or "volume" in p_name or "brightness" in p_name:
                            sample_args[p_name] = rng.choice([20, 50, 75, 80, 100])
                        elif "step" in p_name:
                            sample_args[p_name] = rng.choice([5, 10, 15, 20])
                        elif "id" in p_name or "count" in p_name or "lines" in p_name:
                            sample_args[p_name] = rng.randint(1, 20)
                        else:
                            sample_args[p_name] = rng.randint(1, 100)
                    elif p_type == "boolean":
                        sample_args[p_name] = rng.choice([True, False])
                    elif p_type == "array":
                        sample_args[p_name] = ["item_1", "item_2"]
                    else:
                        sample_args[p_name] = {}

            clean_args = sanitize_tool_args(tool_name, sample_args, schema_map)
            errors = validate_args_against_schema(tool_name, clean_args, schema_map)
            if errors:
                raise ValueError(f"Combinatorial synthesis produced invalid args for '{tool_name}': {errors}")

            clean_name = tool_name.replace("_", " ")
            if clean_args:
                arg_phrases = [f"{k} as {v}" for k, v in clean_args.items()]
                user_query = f"Please {clean_name} with {', '.join(arg_phrases)}."
            else:
                user_query = f"Execute {clean_name} for me."

            cid = f"call_{tool_name}_{i}"
            distractors = pick_distractors({tool_name}, 4)
            cand_tools = [schema] + distractors
            rng.shuffle(cand_tools)

            rec = {
                "messages": [
                    {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_query},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [build_tool_call_message(tool_name, clean_args, cid)]
                    },
                    {
                        "role": "tool",
                        "tool_call_id": cid,
                        "name": tool_name,
                        "content": json.dumps({"status": "success", "result": f"Executed {tool_name}"})
                    },
                    {
                        "role": "assistant",
                        "content": f"Successfully performed {clean_name}."
                    }
                ],
                "tools": cand_tools
            }
            dataset.append(rec)

    rng.shuffle(dataset)
    return dataset


def main():
    print("==================================================")
    print("      VISION Training Dataset Synthesizer         ")
    print("==================================================")

    dataset = synthesize_synthetic_dataset(num_samples=5000, seed=SEED)
    total_count = len(dataset)
    print(f"[*] Generated total of {total_count} validated conversational samples.")

    # 85% Train / 10% Val / 5% Test
    train_end = int(total_count * 0.85)
    val_end = int(total_count * 0.95)

    train_set = dataset[:train_end]
    val_set = dataset[train_end:val_end]
    test_set = dataset[val_end:]

    train_path = DATASETS_DIR / "train_tool_calls.jsonl"
    val_path = DATASETS_DIR / "val_tool_calls.jsonl"
    test_path = DATASETS_DIR / "test_tool_calls.jsonl"

    def write_jsonl(filepath: Path, items: List[Dict[str, Any]]):
        with open(filepath, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    write_jsonl(train_path, train_set)
    write_jsonl(val_path, val_set)
    write_jsonl(test_path, test_set)

    print(f"[OK] Successfully generated and exported datasets:")
    print(f"    - Train Split:      {len(train_set):>5} samples -> {train_path}")
    print(f"    - Validation Split: {len(val_set):>5} samples -> {val_path}")
    print(f"    - Benchmark Test:   {len(test_set):>5} samples -> {test_path}")
    print("==================================================")


if __name__ == "__main__":
    main()
