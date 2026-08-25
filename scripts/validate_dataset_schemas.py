"""
Dataset Schema and Argument Integrity Validator.
Audits all generated JSONL datasets against the live VISION ToolRegistry schemas.
Checks required params, declared types, and unexpected extra arguments.
"""

import sys
import json
from pathlib import Path
from typing import Dict, Any, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vision.tools import *  # noqa: F401,F403 — registers all tools on import
from vision.tools.registry import tool_registry

DATASETS_DIR = PROJECT_ROOT / "data" / "datasets"

TYPE_CHECKERS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def validate_file(filepath: Path, schema_map: Dict[str, Any]) -> Dict[str, Any]:
    stats = {
        "file": filepath.name,
        "total_records": 0,
        "valid_records": 0,
        "invalid_records": 0,
        "tool_call_records": 0,
        "zero_tool_records": 0,
        "tools_covered": set(),
        "errors": []
    }

    if not filepath.exists():
        stats["errors"].append(f"File {filepath} does not exist.")
        return stats

    with open(filepath, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            stats["total_records"] += 1
            line = line.strip()
            if not line:
                stats["invalid_records"] += 1
                stats["errors"].append(f"Line {idx}: Blank line.")
                continue

            try:
                record = json.loads(line)
            except Exception as e:
                stats["invalid_records"] += 1
                stats["errors"].append(f"Line {idx}: JSON parse error: {e}")
                continue

            messages = record.get("messages", [])
            if not messages:
                stats["invalid_records"] += 1
                stats["errors"].append(f"Line {idx}: Missing messages array.")
                continue

            has_tool_call = False
            record_valid = True

            def fail(msg: str):
                nonlocal record_valid
                record_valid = False
                stats["errors"].append(msg)

            for msg in messages:
                role = msg.get("role")
                if not role:
                    fail(f"Line {idx}: Message missing role.")
                    break

                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    has_tool_call = True
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        t_name = fn.get("name")
                        raw_args = fn.get("arguments")

                        if not t_name or t_name not in schema_map:
                            fail(f"Line {idx}: Unknown tool '{t_name}'.")
                            continue

                        stats["tools_covered"].add(t_name)

                        # Validate JSON args
                        try:
                            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        except Exception as ex:
                            fail(f"Line {idx}: Malformed arguments for '{t_name}': {ex}")
                            continue

                        if not isinstance(args, dict):
                            fail(f"Line {idx}: Arguments for '{t_name}' must be an object.")
                            continue

                        expected_schema = schema_map[t_name]["function"]
                        params = expected_schema.get("parameters", {})
                        props: Dict[str, Any] = params.get("properties", {})
                        req_params = params.get("required", [])

                        # Unexpected extra keys
                        for key in args:
                            if key not in props:
                                fail(f"Line {idx}: Unexpected argument '{key}' for tool '{t_name}'.")

                        # Required + type checks
                        for req in req_params:
                            if req not in args:
                                fail(f"Line {idx}: Missing required param '{req}' for tool '{t_name}'.")
                                continue
                            expected_type = props.get(req, {}).get("type", "string")
                            checker = TYPE_CHECKERS.get(expected_type)
                            if checker and not checker(args[req]):
                                fail(
                                    f"Line {idx}: Param '{req}' for '{t_name}' should be "
                                    f"{expected_type}, got {type(args[req]).__name__}."
                                )

            if has_tool_call:
                stats["tool_call_records"] += 1
            else:
                stats["zero_tool_records"] += 1

            if record_valid:
                stats["valid_records"] += 1
            else:
                stats["invalid_records"] += 1

    return stats


def main():
    print("==================================================")
    print("      VISION Dataset Schema & Quality Audit       ")
    print("==================================================")

    all_schemas = tool_registry.get_all_schemas()
    schema_map = {s["function"]["name"]: s for s in all_schemas}
    print(f"[*] Loaded {len(schema_map)} active schemas from registry.")

    files = [
        DATASETS_DIR / "train_tool_calls.jsonl",
        DATASETS_DIR / "val_tool_calls.jsonl",
        DATASETS_DIR / "test_tool_calls.jsonl"
    ]

    all_covered = set()
    total_valid = 0
    total_invalid = 0

    for file in files:
        stats = validate_file(file, schema_map)
        all_covered.update(stats["tools_covered"])
        total_valid += stats["valid_records"]
        total_invalid += stats["invalid_records"]

        total = stats["total_records"]
        pct = f"{(stats['valid_records'] / total) * 100:.1f}%" if total else "n/a"
        print(f"\n[Audit] {stats['file']}:")
        print(f"  - Total Records:      {total}")
        print(f"  - Valid Schema Match: {stats['valid_records']} ({pct})")
        print(f"  - Tool Calls:         {stats['tool_call_records']}")
        print(f"  - Zero-Tool Prompts:  {stats['zero_tool_records']}")
        print(f"  - Distinct Tools:     {len(stats['tools_covered'])}")

        if stats["errors"]:
            print(f"  [!] Errors Encountered ({len(stats['errors'])}):")
            for err in stats["errors"][:5]:
                print(f"      * {err}")

    grand_total = total_valid + total_invalid
    pass_pct = f"{(total_valid / grand_total) * 100:.2f}%" if grand_total else "n/a (no records found)"
    denom = len(schema_map) or 1
    print("\n==================================================")
    print(f"[SUMMARY] Total Tool Coverage: {len(all_covered)} / {len(schema_map)} registered tools ({(len(all_covered)/denom)*100:.1f}%)")
    print(f"[SUMMARY] Overall Dataset Health: {total_valid} valid, {total_invalid} invalid ({pass_pct})")
    print("==================================================")

    if total_invalid:
        sys.exit(1)


if __name__ == "__main__":
    main()
