"""
Tool smoke-test harness: calls every registered tool with safe auto-filled args.
Each call is hard-timeout-guarded (async via wait_for, sync via thread+timeout).
Writes incremental results to data/tool_audit_results.json so progress survives.

DANGEROUS TOOLS ARE SKIPPED, NEVER EXECUTED. Run with --dry-run to list what
would run without executing anything.

Usage: python scripts/audit_tools.py [timeout_per_tool] [--dry-run]
"""

import asyncio
import concurrent.futures
import inspect
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vision.tools import *  # noqa: F401,F403 — registers all tools
from vision.tools.registry import tool_registry

RESULTS_PATH = PROJECT_ROOT / "data" / "tool_audit_results.json"

# Tools with destructive / disruptive real-world side effects that must NOT be
# auto-executed by this harness. They are reported as SKIPPED, not failures.
SKIP_TOOLS = {
    # Security / power state (EXACT names as registered!)
    "lock_workstation", "lock_screen", "sleep_computer", "sleep_pc",
    "hibernate_computer", "restart_computer", "restart_pc", "shutdown_computer",
    "shutdown_pc", "log_off_user", "cancel_shutdown",
    # Process killing
    "kill_process_by_name",
    # Data mutation on real files
    "delete_file", "delete_folder", "empty_recycle_bin", "organize_downloads",
    "organize_desktop", "compress_to_zip", "extract_zip",
    # Remote server mutation
    "clear_parking_logs", "restart_kpr_print_system",
    # Phone-side side effects
    "unlock_phone",
    # Types into whatever window the USER currently has focused
    "type_text_into_application", "press_keyboard_shortcut", "save_active_document",
    # Drives real WhatsApp Desktop UI with pyautogui (can SEND messages)
    "send_whatsapp_message", "confirm_and_send_whatsapp_draft",
    # Sends real jobs to the physical printer
    "print_document", "create_and_print_bordered_document",
    # Real outbound communication / remote execution (look benign, act live)
    "send_email", "ssh_execute_command", "connect_to_ssh_server",
    "check_parking_logs", "open_parking_logs_terminal",
    "download_file_from_url", "fetch_webpage_content", "open_website",
    "check_college_outlook_emails",
    # Sends media keystrokes to the foreground window
    "control_youtube_playback", "seek_youtube_video",
    # LLM-cost-heavy autonomous agents (slow, spend tokens)
    "browser_autonomous_task", "execute_autonomous_multi_agent_goal",
    # Opens blocking interactive sessions
    "open_interactive_ssh_terminal",
}

# Backstop: any tool whose name matches these patterns is skipped even if not
# listed above (lesson learned: restart_pc vs restart_computer naming drift).
import re as _re

RISKY_NAME_PATTERN = _re.compile(
    r"restart|shut_?down|hibernate|log_?off|reboot|kill_|format_|erase|wipe"
    r"|factory_reset|uninstall",
    _re.I,
)


def is_risky(tool_name: str) -> bool:
    return tool_name in SKIP_TOOLS or bool(RISKY_NAME_PATTERN.search(tool_name))


def sample_value(p_spec: dict, name: str):
    t = p_spec.get("type", "string")
    if t in ("integer", "number"):
        return 5
    if t == "boolean":
        return False
    if t == "array":
        return []
    if t == "object":
        return {}
    return f"test_{name}"


def run_sync_with_timeout(func, kwargs, timeout, pool):
    future = pool.submit(func, **kwargs)
    return future.result(timeout=timeout)


async def main(per_tool_timeout: float, dry_run: bool = False):
    schemas = {s["function"]["name"]: s for s in tool_registry.get_all_schemas()}
    tools = dict(tool_registry._tools)

    ok, failed, skipped = [], {}, []

    if dry_run:
        print("==== DRY RUN — nothing will be executed ====")
        for name in sorted(tools):
            tag = "SKIP (destructive)" if is_risky(name) else "WOULD RUN"
            print(f"  {tag:22s} {name}")
        would = sum(1 for n in tools if not is_risky(n))
        print(f"\n{would} tools would run, {len(tools) - would} skipped. Use --yes to execute.")
        return

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    for i, (name, func) in enumerate(sorted(tools.items()), 1):
        if is_risky(name):
            skipped.append(name)
            print(f"[{i}/{len(tools)}] SKIP {name} (destructive)", flush=True)
            continue
        props = schemas.get(name, {}).get("function", {}).get("parameters", {}).get("properties", {})
        required = schemas.get(name, {}).get("function", {}).get("parameters", {}).get("required", [])
        kwargs = {r: sample_value(props.get(r, {}), r) for r in required}
        try:
            if inspect.iscoroutinefunction(func):
                await asyncio.wait_for(func(**kwargs), timeout=per_tool_timeout)
            else:
                # NOTE: a timed-out sync tool keeps running in its worker thread
                # (threads cannot be killed) — another reason risky tools must be
                # in SKIP_TOOLS rather than trusted to the timeout.
                await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(
                        None,
                        lambda f=func, k=kwargs: run_sync_with_timeout(f, k, per_tool_timeout * 4, pool),
                    ),
                    timeout=per_tool_timeout,
                )
            ok.append(name)
            print(f"[{i}/{len(tools)}] OK   {name}", flush=True)
        except concurrent.futures.TimeoutError:
            failed.setdefault(f"TimeoutError (>{per_tool_timeout}s)", []).append(name)
            print(f"[{i}/{len(tools)}] TIME {name}", flush=True)
        except asyncio.TimeoutError:
            failed.setdefault(f"TimeoutError (>{per_tool_timeout}s)", []).append(name)
            print(f"[{i}/{len(tools)}] TIME {name}", flush=True)
        except Exception as e:
            key = f"{type(e).__name__}: {str(e)[:140]}"
            failed.setdefault(key, []).append(name)
            print(f"[{i}/{len(tools)}] FAIL {name} :: {key[:80]}", flush=True)

        RESULTS_PATH.write_text(
            json.dumps({"ok": ok, "failed": failed}, indent=1), encoding="utf-8"
        )

    print("\n==== AUDIT SUMMARY ====")
    print(f"OK: {len(ok)} | FAILED: {sum(len(v) for v in failed.values())}")
    for err, names in sorted(failed.items(), key=lambda kv: -len(kv[1])):
        print(f"\n[{len(names)}] {err}")
        print("   ", ", ".join(names))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = {a for a in sys.argv[1:] if a.startswith("-")}
    timeout = float(args[0]) if args else 8.0
    # Execution requires an explicit opt-in flag — default is dry-run so the
    # harness can never again fire real-world side effects by accident.
    dry_run = "--yes" not in flags
    asyncio.run(main(timeout, dry_run=dry_run))
