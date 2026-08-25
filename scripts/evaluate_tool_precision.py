"""
Tool Calling Benchmark Evaluation Suite for VISION.
Evaluates a model against the held-out test split (test_tool_calls.jsonl) measuring:
1. Tool Selection Recall (fraction of ground-truth tool prompts answered with the right tool)
2. Argument Schema Accuracy (required params present & typed correctly)
3. Zero-Shot False Positive Rate on Conversational Queries
4. Hallucination Rate (tool calls on prompts that expect none)
"""

import sys
import json
import time
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vision.tools import *  # noqa: F401,F403 — registers all tools on import
from vision.tools.registry import tool_registry
from vision.constants import DEFAULT_SYSTEM_PROMPT
from vision.cognitive.load_balancer import load_balancer

TEST_DATASET_FILE = PROJECT_ROOT / "data" / "datasets" / "test_tool_calls.jsonl"

TYPE_CHECKERS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def extract_ground_truth(messages: List[Dict[str, Any]]) -> List[Tuple[str, Dict[str, Any]]]:
    """Returns the (tool_name, args) sequence of expected calls in message order."""
    expected: List[Tuple[str, Dict[str, Any]]] = []
    for m in messages:
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments", {})
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except Exception:
                args = {}
            expected.append((fn.get("name"), args if isinstance(args, dict) else {}))
    return expected


def required_params_satisfied(tool_name: str, pred_args: Dict[str, Any], schema_map: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Checks that every required param is present and type-correct."""
    if tool_name not in schema_map:
        return False, [f"unknown tool '{tool_name}'"]
    fn = schema_map[tool_name]["function"]
    params = fn.get("parameters", {})
    props: Dict[str, Any] = params.get("properties", {})
    problems: List[str] = []
    for req in params.get("required", []):
        if req not in pred_args:
            problems.append(f"missing '{req}'")
            continue
        checker = TYPE_CHECKERS.get(props.get(req, {}).get("type", "string"))
        if checker and not checker(pred_args[req]):
            problems.append(f"'{req}' wrong type")
    return (not problems), problems


def grade_response(
    is_conversational_only: bool,
    expected_calls: List[Tuple[str, Dict[str, Any]]],
    pred_tool: Optional[str],
    pred_args: Dict[str, Any],
    schema_map: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Pure scoring function — no I/O, unit-testable.

    Returns {"status": PASS|WARN|FAIL, "detail": str} and the counters this
    response contributes.
    """
    if is_conversational_only:
        if not pred_tool:
            return {
                "status": "PASS",
                "detail": "Correctly answered conversationally without tool hallucination.",
                "zero_tool_pass": 1, "hallucination": 0, "tool_correct": 0, "args_correct": 0,
            }
        return {
            "status": "FAIL",
            "detail": f"Hallucinated tool '{pred_tool}' on conversational prompt.",
            "zero_tool_pass": 0, "hallucination": 1, "tool_correct": 0, "args_correct": 0,
        }

    expected_tool = expected_calls[0][0] if expected_calls else None
    if not expected_tool:
        # Malformed record — treat as failure rather than silently skipping.
        return {
            "status": "FAIL",
            "detail": "Record has no extractable ground truth tool call.",
            "zero_tool_pass": 0, "hallucination": 0, "tool_correct": 0, "args_correct": 0,
        }

    if pred_tool != expected_tool:
        return {
            "status": "FAIL",
            "detail": f"Expected '{expected_tool}', but got '{pred_tool}'.",
            "zero_tool_pass": 0, "hallucination": 0, "tool_correct": 0, "args_correct": 0,
        }

    correct_tool = 1
    args_ok, problems = required_params_satisfied(expected_tool, pred_args or {}, schema_map)
    if args_ok:
        return {
            "status": "PASS",
            "detail": f"Tool '{pred_tool}' selected with valid arguments.",
            "zero_tool_pass": 0, "hallucination": 0,
            "tool_correct": correct_tool, "args_correct": 1,
        }
    return {
        "status": "WARN",
        "detail": f"Tool '{pred_tool}' selected, but {', '.join(problems)}.",
        "zero_tool_pass": 0, "hallucination": 0,
        "tool_correct": correct_tool, "args_correct": 0,
    }


async def evaluate_benchmark(num_samples: int = 25):
    print("==================================================")
    print("   VISION Model Tool Calling Precision Benchmark  ")
    print("==================================================")

    if not TEST_DATASET_FILE.exists():
        print(f"[!] Test dataset {TEST_DATASET_FILE} not found. Run generate_training_dataset.py first.")
        return

    records: List[Dict[str, Any]] = []
    with open(TEST_DATASET_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line.strip()))

    eval_set = records[:num_samples]
    print(f"[*] Loaded {len(records)} test cases. Evaluating top {len(eval_set)} cases...")

    total_tested = 0
    errored = 0
    correct_tool_selections = 0
    correct_arguments = 0
    correct_zero_tool_conversations = 0
    hallucinations = 0
    total_zero_tool_prompts = 0
    total_tool_prompts = 0
    latencies: List[float] = []

    all_schemas = tool_registry.get_all_schemas()
    schema_map = {s["function"]["name"]: s for s in all_schemas}

    for idx, rec in enumerate(eval_set, start=1):
        messages = rec.get("messages", [])
        available_tools = rec.get("tools", [])

        expected_calls = extract_ground_truth(messages)
        is_conversational_only = not expected_calls

        # Extract user prompt (first user turn)
        user_prompt = ""
        for m in messages:
            if m.get("role") == "user":
                user_prompt = m.get("content") or ""
                break

        if is_conversational_only:
            is_conversational = True
        else:
            is_conversational = False

        total_tested += 1

        # Query model via Load Balancer — SAME system prompt used at training time
        prompt_messages = [
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

        t0 = time.time()
        elapsed_ms: Optional[float] = None
        res: Optional[Dict[str, Any]] = None
        try:
            res = await load_balancer.chat_completion(
                messages=prompt_messages,
                tools=available_tools if available_tools else None,
                temperature=0.0
            )
            elapsed_ms = (time.time() - t0) * 1000
            latencies.append(elapsed_ms)
        except Exception as e:
            # Provider errors count toward total_tested/errored but are excluded
            # from every metric denominator (tallies happen after this block).
            errored += 1
            print(f"[{idx}/{len(eval_set)}] ERROR (provider failed): {e}")
            continue

        # Denominator tallies — only reached on successful provider responses,
        # so the printed "(provider errors excluded from scores)" holds.
        if is_conversational:
            total_zero_tool_prompts += 1
        else:
            total_tool_prompts += 1

        pred_tool_calls = (res or {}).get("tool_calls") or []
        pred_tool = None
        pred_args: Dict[str, Any] = {}
        if pred_tool_calls:
            first = pred_tool_calls[0]
            fn = first.get("function", {})
            pred_tool = fn.get("name")
            raw_pargs = fn.get("arguments", {})
            try:
                pred_args = json.loads(raw_pargs) if isinstance(raw_pargs, str) else raw_pargs
            except Exception:
                pred_args = {}
            if not isinstance(pred_args, dict):
                pred_args = {}

        verdict = grade_response(
            is_conversational_only=is_conversational_only,
            expected_calls=expected_calls,
            pred_tool=pred_tool,
            pred_args=pred_args,
            schema_map=schema_map,
        )

        correct_zero_tool_conversations += verdict["zero_tool_pass"]
        hallucinations += verdict["hallucination"]
        correct_tool_selections += verdict["tool_correct"]
        correct_arguments += verdict["args_correct"]

        latency_txt = f" ({elapsed_ms:.1f}ms)" if elapsed_ms is not None else ""
        print(f"[{idx:>2}/{len(eval_set)}] User: \"{user_prompt[:40]}...\" -> [{verdict['status']}] {verdict['detail']}{latency_txt}")

    # Print Final Benchmark Metrics
    tool_recall = (correct_tool_selections / max(1, total_tool_prompts)) * 100
    arg_acc = (correct_arguments / max(1, total_tool_prompts)) * 100
    fp_resist = (correct_zero_tool_conversations / max(1, total_zero_tool_prompts)) * 100 if total_zero_tool_prompts else 100.0
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    print("\n==================================================")
    print("            FINAL BENCHMARK RESULTS               ")
    print("==================================================")
    print(f"  * Total Test Samples Evaluated:      {total_tested} ({errored} provider errors excluded from scores)")
    print(f"  * Tool Selection Recall:             {tool_recall:.2f}% ({correct_tool_selections}/{total_tool_prompts})")
    print(f"  * Parameter & Schema Accuracy:       {arg_acc:.2f}% ({correct_arguments}/{total_tool_prompts})")
    print(f"  * Zero-Tool False Positive Defense:  {fp_resist:.2f}% ({correct_zero_tool_conversations}/{total_zero_tool_prompts})")
    print(f"  * Tool Hallucinations on QA Prompts: {hallucinations}/{total_zero_tool_prompts}")
    print(f"  * Mean Response Latency:             {avg_latency:.1f} ms")
    print("==================================================")


def main():
    asyncio.run(evaluate_benchmark(num_samples=25))


if __name__ == "__main__":
    main()
