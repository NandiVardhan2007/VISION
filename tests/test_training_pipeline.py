"""
Tests for the fine-tuning data pipeline:
- Dataset generator: determinism, schema validity, negative examples, strict validation
- Schema validator: crash guards (empty/missing/malformed files), type & extra-key checks
- Evaluator scoring logic (pure grade_response function)
- CustomFineTunedLLMProvider config wiring
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from vision.tools.registry import tool_registry  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def schema_map():
    return {s["function"]["name"]: s for s in tool_registry.get_all_schemas()}


@pytest.fixture(scope="module")
def generated_dataset(schema_map):
    """Generate the dataset once per module; must be deterministic."""
    from generate_training_dataset import synthesize_synthetic_dataset, SEED
    return synthesize_synthetic_dataset(num_samples=5000, seed=SEED)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def test_generator_is_deterministic(schema_map):
    from generate_training_dataset import synthesize_synthetic_dataset, SEED
    a = synthesize_synthetic_dataset(num_samples=200, seed=SEED)
    b = synthesize_synthetic_dataset(num_samples=200, seed=SEED)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_generated_records_are_schema_valid(generated_dataset, schema_map):
    type_checkers = {
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "array": lambda v: isinstance(v, list),
        "object": lambda v: isinstance(v, dict),
    }
    for rec in generated_dataset:
        messages = rec["messages"]
        assert messages and messages[0]["role"] == "system"
        for msg in messages:
            for tc in msg.get("tool_calls") or []:
                fn = tc["function"]
                name = fn["name"]
                assert name in schema_map, f"Unknown tool {name} in generated record"
                args = json.loads(fn["arguments"])
                params = schema_map[name]["function"].get("parameters", {})
                props = params.get("properties", {})
                # No unexpected keys
                for key in args:
                    assert key in props, f"Unexpected arg '{key}' for '{name}'"
                # Required present + typed
                for req in params.get("required", []):
                    assert req in args, f"Missing required '{req}' for '{name}'"
                    checker = type_checkers.get(props.get(req, {}).get("type", "string"))
                    if checker:
                        assert checker(args[req]), (
                            f"Wrong type for '{req}' of '{name}': {args[req]!r}"
                        )


def test_negative_examples_have_no_tool_calls(generated_dataset):
    conversational = [
        r for r in generated_dataset
        if not any(m.get("tool_calls") for m in r["messages"])
    ]
    assert len(conversational) >= len([
        "Hey Vision", "Good morning Vision!", "Who created you",
        "Tell me a funny joke", "Voice Activity Detection",
        "TCP and UDP", "Thank you Vision", "quantum computing",
    ]), "Expected all hand-written negative prompts to be present"
    for rec in conversational:
        last = rec["messages"][-1]
        assert last["role"] == "assistant"
        assert last["content"], "Negative examples should carry an answer"


def test_unknown_tool_template_is_skipped_not_emitted():
    from generate_training_dataset import sanitize_tool_args, validate_args_against_schema
    fake_map = {
        "real_tool": {
            "function": {
                "name": "real_tool",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            }
        }
    }
    # Unknown tool -> validate reports it, doesn't crash
    errors = validate_args_against_schema("ghost_tool", {}, fake_map)
    assert errors and "Unknown tool" in errors[0]
    # Extra unknown keys are caught
    errors = validate_args_against_schema("real_tool", {"path": "x", "bogus": 1}, fake_map)
    assert any("bogus" in e for e in errors)
    # sanitize drops extra keys and fills required ones
    clean = sanitize_tool_args("real_tool", {"bogus": 1}, fake_map)
    assert clean == {"path": "sample_path"}


def test_all_handcrafted_templates_match_real_tool_signatures(schema_map):
    """
    Regression guard: every hand-crafted training template (single-turn and
    multi-turn) must reference a registered tool, use only real parameter
    names, and supply every required parameter. This catches tool renames
    that would otherwise silently poison the training data.
    """
    import generate_training_dataset as gen

    problems = []

    def check(tname, args, where):
        if tname not in schema_map:
            problems.append(f"{where}: unknown tool '{tname}'")
            return
        props = schema_map[tname]["function"]["parameters"]["properties"]
        for k in args:
            if k not in props:
                problems.append(f"{where}: {tname}: arg '{k}' not in schema")
        for r in schema_map[tname]["function"]["parameters"]["required"]:
            if r not in args:
                problems.append(f"{where}: {tname}: missing required '{r}'")

    for domain, examples in gen.DOMAIN_SPECIFIC_TEMPLATES.items():
        for _prompt, tname, args in examples:
            check(tname, args, domain)

    for chain in gen.MULTI_TURN_CHAINS:
        for _prompt, tname, args in chain:
            check(tname, args, "multi_turn_chain")

    assert not problems, (
        f"{len(problems)} hand-crafted template(s) drifted from the live tool "
        f"signatures — fix the templates, not this test:\n" + "\n".join(problems)
    )


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def _write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _make_valid_record(schema_map, tmp_path):
    name = next(n for n, s in schema_map.items()
                if not s["function"]["parameters"].get("required"))
    return {
        "messages": [
            {"role": "user", "content": "do it"},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "call_x", "type": "function",
                             "function": {"name": name, "arguments": "{}"}}]},
        ],
        "tools": [],
    }


def test_validator_handles_missing_and_empty_files(schema_map, tmp_path):
    from validate_dataset_schemas import validate_file
    missing = tmp_path / "missing.jsonl"
    stats = validate_file(missing, schema_map)
    assert stats["total_records"] == 0
    assert stats["errors"], "missing file should be reported"

    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    stats = validate_file(empty, schema_map)
    assert stats["total_records"] == 0
    assert stats["valid_records"] == 0 and stats["invalid_records"] == 0


def test_validator_catches_malformed_lines_and_bad_types(schema_map, tmp_path):
    from validate_dataset_schemas import validate_file
    bad = tmp_path / "bad.jsonl"
    tool_name = next(iter(schema_map))

    bad.write_text(
        json.dumps({"messages": [{"role": "user", "content": "hi"}]}) + "\n"
        + "{not valid json" + "\n",
        encoding="utf-8",
    )
    stats = validate_file(bad, schema_map)
    assert stats["total_records"] == 2
    # First record is a plain conversational turn (valid); only the malformed
    # JSON line counts as invalid.
    assert stats["valid_records"] == 1
    assert stats["invalid_records"] == 1

    # Wrong-typed required param is flagged
    params = schema_map[tool_name]["function"]["parameters"]
    reqs = params.get("required", [])
    int_req = next((r for r in reqs
                    if params["properties"][r].get("type") in ("integer", "number")), None)
    if int_req:
        rec = {"messages": [{"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": tool_name,
                          "arguments": json.dumps({int_req: "not-a-number"})}}]}]}
        p = tmp_path / "wrong_type.jsonl"
        _write_jsonl(p, [rec])
        stats = validate_file(p, schema_map)
        assert stats["invalid_records"] == 1
        assert any("should be" in e for e in stats["errors"])

    # Unexpected extra key is flagged
    no_req_name = next((n for n, s in schema_map.items()
                        if not s["function"]["parameters"].get("required")), None)
    if no_req_name:
        rec = {"messages": [{"role": "assistant", "content": None, "tool_calls": [
            {"id": "c2", "type": "function",
             "function": {"name": no_req_name,
                          "arguments": json.dumps({"totally_bogus_key": 1})}}]}]}
        p = tmp_path / "extra_key.jsonl"
        _write_jsonl(p, [rec])
        stats = validate_file(p, schema_map)
        assert stats["invalid_records"] == 1
        assert any("Unexpected argument" in e for e in stats["errors"])


def test_validator_passes_on_shipped_datasets(schema_map):
    from validate_dataset_schemas import validate_file, DATASETS_DIR
    total_valid = 0
    total_invalid = 0
    for fname in ("train_tool_calls.jsonl", "val_tool_calls.jsonl", "test_tool_calls.jsonl"):
        stats = validate_file(DATASETS_DIR / fname, schema_map)
        total_valid += stats["valid_records"]
        total_invalid += stats["invalid_records"]
        if stats["total_records"]:
            for err in stats["errors"][:5]:
                pytest.fail(f"{fname}: {err}")
    assert total_invalid == 0, "shipped datasets must be fully valid"
    assert total_valid > 0


# ---------------------------------------------------------------------------
# Evaluator scoring
# ---------------------------------------------------------------------------

def test_grade_response_conversational_no_hallucination():
    from evaluate_tool_precision import grade_response
    v = grade_response(True, [], None, {}, {})
    assert v["status"] == "PASS" and v["zero_tool_pass"] == 1


def test_grade_response_conversational_hallucination():
    from evaluate_tool_precision import grade_response
    v = grade_response(True, [], "read_screen", {}, {})
    assert v["status"] == "FAIL" and v["hallucination"] == 1


def test_grade_response_correct_tool_with_required_args():
    from evaluate_tool_precision import grade_response
    schema_map = {"ping_host": {"function": {"name": "ping_host", "parameters": {
        "type": "object",
        "properties": {"host": {"type": "string"}, "count": {"type": "integer"}},
        "required": ["host"],
    }}}}
    v = grade_response(False, [("ping_host", {"host": "8.8.8.8"})],
                       "ping_host", {"host": "8.8.8.8", "count": 4}, schema_map)
    assert v["status"] == "PASS" and v["tool_correct"] == 1 and v["args_correct"] == 1


def test_grade_response_missing_required_param_warns():
    from evaluate_tool_precision import grade_response
    schema_map = {"ping_host": {"function": {"name": "ping_host", "parameters": {
        "type": "object",
        "properties": {"host": {"type": "string"}},
        "required": ["host"],
    }}}}
    v = grade_response(False, [("ping_host", {"host": "x"})],
                       "ping_host", {}, schema_map)
    assert v["status"] == "WARN" and v["tool_correct"] == 1 and v["args_correct"] == 0


def test_grade_response_wrong_tool_fails():
    from evaluate_tool_precision import grade_response
    v = grade_response(False, [("read_screen", {})], "set_volume", {}, {})
    assert v["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Provider config wiring
# ---------------------------------------------------------------------------

def test_custom_provider_reads_env_config(monkeypatch):
    monkeypatch.setenv("CUSTOM_MODEL_URL", "http://myserver:9999/v1")
    monkeypatch.setenv("CUSTOM_MODEL_NAME", "my-finetune")
    monkeypatch.setenv("CUSTOM_MODEL_API_KEY", "sk-test")

    # Re-import config fresh so env overrides apply
    import importlib
    import vision.config as config_mod
    importlib.reload(config_mod)

    try:
        provider_mod = importlib.import_module("vision.cognitive.providers.custom_finetuned_llm")
        importlib.reload(provider_mod)
        p = provider_mod.CustomFineTunedLLMProvider()
        assert p.base_url == "http://myserver:9999/v1"
        assert p.model == "my-finetune"
        assert p.api_key == "sk-test"
    finally:
        # Restore original config singleton for other tests
        for mod_name in ("vision.config", "vision.cognitive.providers.custom_finetuned_llm"):
            mod = sys.modules.get(mod_name)
            if mod is not None:
                importlib.reload(mod)


def test_load_balancer_includes_custom_provider_when_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_CUSTOM_MODEL_PROVIDER", "true")
    import importlib
    import vision.config as config_mod
    importlib.reload(config_mod)
    try:
        lb_mod = importlib.import_module("vision.cognitive.load_balancer")
        importlib.reload(lb_mod)
        lb = lb_mod.LoadBalancer(strategy="least_busy")
        names = [p.name for p in lb.providers]
        assert "custom_finetuned_llm" in names
    finally:
        importlib.reload(config_mod)
        importlib.reload(sys.modules["vision.cognitive.load_balancer"])
