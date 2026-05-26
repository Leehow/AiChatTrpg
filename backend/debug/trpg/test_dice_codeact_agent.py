"""Deterministic tests for the CodeAct loop + feature-flag wiring.

No real LLM. Stub `llm_call` returns canned chat-completion shapes
so we exercise: flag parsing; happy-path proposal;
apply-boundary consumability; compile_one fallback branch; invalid
proposal falling back to compile_one; silent (no-tool-call) loop
falling back to compile_one.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_dice_codeact_agent.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))


def fail(label: str, why: str = "") -> None:
    print(f"FAIL: {label} {why}")
    sys.exit(1)


def assert_true(label: str, cond: bool, why: str = "") -> None:
    if not cond:
        fail(label, why)
    print(f"OK: {label}")


from agents.rule_editor_dice import codeact_agent as CA  # noqa: E402
from agents.rule_editor_dice import codeact_primitives as P  # noqa: E402
from agents.rule_editor_dice import codeact_prompts as CP  # noqa: E402
from agents.rule_editor_dice import tools_apply as TA  # noqa: E402


# ---------------------------------------------------------------------------
# Stub chat-completion shape
# ---------------------------------------------------------------------------


class _Fn:
    def __init__(self, name: str, arguments: str) -> None:
        self.name, self.arguments = name, arguments


class _Tc:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id, self.type = call_id, "function"
        self.function = _Fn(name, arguments)


class _Msg:
    def __init__(self, content: str, tool_calls: List[_Tc]) -> None:
        self.content, self.tool_calls = content, tool_calls


class _Choice:
    def __init__(self, message: _Msg) -> None:
        self.message = message
        self.finish_reason = "tool_calls" if message.tool_calls else "stop"


class _Resp:
    def __init__(self, message: _Msg) -> None:
        self.choices = [_Choice(message)]


def _propose_final_call(
    *, ir: Dict[str, Any], samples: List[Dict[str, Any]],
    procedure_id: str, name: str, primary_family: str,
) -> _Resp:
    import json
    args = json.dumps({
        "ir": ir, "samples": samples,
        "procedure_id": procedure_id, "name": name,
        "primary_family": primary_family,
    })
    return _Resp(_Msg(
        "", [_Tc("call_1", CP.TOOL_NAME_PROPOSE_FINAL, args)],
    ))


def _compile_one_call(description: str, name: str) -> _Resp:
    import json
    args = json.dumps({
        "description": description, "name": name, "engine_hint": "",
    })
    return _Resp(_Msg(
        "", [_Tc("call_1", CP.TOOL_NAME_COMPILE_ONE, args)],
    ))


def _empty_call() -> _Resp:
    return _Resp(_Msg("", []))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_codeact_flag_default_off_and_truthy() -> None:
    print("\n--- 1. codeact_enabled() honours CHATRPG_DICE_CODEACT ---")
    prev = os.environ.pop(CA.CODEACT_ENV_FLAG, None)
    try:
        assert_true("default is off", CA.codeact_enabled() is False)
        for v in ("1", "true", "yes", "ON"):
            os.environ[CA.CODEACT_ENV_FLAG] = v
            assert_true(f"value {v!r} enables", CA.codeact_enabled() is True)
        for v in ("0", "false", "", "no", "bogus"):
            os.environ[CA.CODEACT_ENV_FLAG] = v
            assert_true(
                f"value {v!r} keeps off", CA.codeact_enabled() is False,
            )
    finally:
        os.environ.pop(CA.CODEACT_ENV_FLAG, None)
        if prev is not None:
            os.environ[CA.CODEACT_ENV_FLAG] = prev


def _good_coc_proposal_args() -> Dict[str, Any]:
    ir = P.propose_ir_skeleton(
        "coc_7e_d100", procedure_id="stealth_check", name="Stealth Check",
    )
    samples = P.generate_sample_cases("coc_7e_d100", {"skill": 50})
    return {
        "ir": ir, "samples": samples,
        "procedure_id": "stealth_check", "name": "Stealth Check",
        "primary_family": "sum_vs_target",
    }


async def _run_with_stub(stub_calls: List[_Resp]) -> CA.CodeActOutcome:
    """Run compile_via_codeact with a queue of stub LLM responses."""
    queue = list(stub_calls)

    async def _stub_llm(messages, tools):
        return queue.pop(0) if queue else _empty_call()

    return await CA.compile_via_codeact(
        procedure_id="stealth_check", name="Stealth Check",
        description="CoC d100 stealth check", engine_hint="coc_7e_d100",
        system_name="Test", output_language="en",
        cfg={"model": "stub-model", "base_url": "", "api_key": ""},
        provider="debug",
        budget=CA.CodeActBudget(
            max_primitive_calls=5, max_inner_iters=2, wallclock_seconds=10.0,
        ),
        llm_call=_stub_llm,
    )


def test_propose_final_happy_path() -> None:
    print("\n--- 2. proposal happy path produces apply-compatible package ---")
    args = _good_coc_proposal_args()
    stub = _propose_final_call(**args)
    outcome = asyncio.run(_run_with_stub([stub]))

    assert_true("source == codeact", outcome.source == "codeact",
                why=f"got {outcome.source}")
    pkg = outcome.package
    assert_true(
        "package schema_version is canonical",
        pkg.get("schema_version") == "rulebook_dice_compilation_v1",
    )
    compiled = pkg.get("compiled") or {}
    specs = compiled.get("check_specs") or []
    assert_true("exactly one compiled spec", len(specs) == 1)
    entry = specs[0]
    assert_true(
        "spec procedure_id propagated",
        entry.get("procedure_id") == "stealth_check",
    )
    assert_true(
        "spec engine is generic_resolution_v1",
        (entry.get("check_spec") or {}).get("engine") == "generic_resolution_v1",
    )
    assert_true(
        "validation.ok=True",
        ((entry.get("validation") or {}).get("ok")) is True,
    )
    assert_true(
        "compiled_strategy is codeact_v1",
        pkg.get("compiler_strategy") == "codeact_v1",
    )


def test_package_consumable_by_apply_helpers() -> None:
    print("\n--- 3. package is consumable by tools_apply helpers ---")
    args = _good_coc_proposal_args()
    stub = _propose_final_call(**args)
    outcome = asyncio.run(_run_with_stub([stub]))
    compiled = outcome.package.get("compiled") or {}
    specs = compiled.get("check_specs") or []

    summary = TA._summarize_specs(specs)
    assert_true("summary has one entry", len(summary) == 1)
    summary_entry = summary[0]
    assert_true(
        "summary surfaces engine + procedure_id",
        summary_entry["engine"] == "generic_resolution_v1"
        and summary_entry["procedure_id"] == "stealth_check",
    )
    assert_true(
        "summary.validation_ok=True",
        summary_entry["validation_ok"] is True,
    )

    # Dry-run merge: ensure the merger accepts the spec shape and
    # writes the same artifact a real apply call would. No DB touched.
    parsed_v6: Dict[str, Any] = {}
    TA._merge_into_dice_ir(parsed_v6, specs, model="stub-model")
    new_ir = parsed_v6.get("dice_ir") or {}
    merged_specs = (
        ((new_ir.get("package") or {}).get("compiled") or {})
        .get("check_specs") or []
    )
    assert_true(
        "merge_into_dice_ir wrote one spec",
        len(merged_specs) == 1
        and merged_specs[0]["procedure_id"] == "stealth_check",
    )


def test_compile_one_fallback_branch() -> None:
    print("\n--- 4. compile_one-only stub triggers compile_one_fallback ---")

    canonical_pkg = {
        "schema_version": "rulebook_dice_compilation_v1",
        "compiler_strategy": "direct_ir_v1",
        "model": "stub-model",
        "compiled": {
            "schema_version": "compiled_check_specs_v1",
            "default_procedure_id": "x",
            "check_specs": [{
                "procedure_id": "x", "name": "X", "primary_family": "f",
                "check_spec": {"engine": "generic_resolution_v1", "ir": {}},
                "validation": {"ok": True, "sample_count": 0, "samples": []},
                "samples": [],
            }],
            "unsupported_procedures": [],
            "overall_ok": True,
        },
    }

    async def _stub_compile_one(*_a, **_kw):
        return canonical_pkg

    orig = P.compile_one
    P.compile_one = _stub_compile_one  # type: ignore[assignment]
    try:
        # Two turns: each turn issues a compile_one call, neither
        # issues propose_final. Loop exits at max_inner_iters with
        # last_compile_one_package preserved.
        stubs = [
            _compile_one_call("desc", "x"),
            _compile_one_call("desc", "x"),
        ]
        outcome = asyncio.run(_run_with_stub(stubs))
    finally:
        P.compile_one = orig  # type: ignore[assignment]

    assert_true(
        "source is fallback_compile_one",
        outcome.source == "fallback_compile_one",
        why=f"got {outcome.source}",
    )
    assert_true(
        "fallback package is the one compile_one returned",
        outcome.package is canonical_pkg,
    )


def test_invalid_proposal_falls_back_to_compile_one() -> None:
    print("\n--- 5. invalid proposal samples re-route to compile_one ---")
    bad_args = _good_coc_proposal_args()
    bad_samples = [{
        "name": "rigged", "args": {"roll": [1], "skill": 50},
        "expected": {"primary_tier": "failure", "passed": False},
    }]
    bad_args["samples"] = bad_samples
    stub = _propose_final_call(**bad_args)

    fallback_pkg = {"compiler_strategy": "direct_ir_v1", "compiled": {}}

    called: List[bool] = []

    async def _stub_compile_one(*_a, **_kw):
        called.append(True)
        return fallback_pkg

    orig = P.compile_one
    P.compile_one = _stub_compile_one  # type: ignore[assignment]
    try:
        outcome = asyncio.run(_run_with_stub([stub]))
    finally:
        P.compile_one = orig  # type: ignore[assignment]

    assert_true(
        "source is fallback_codeact_failed",
        outcome.source == "fallback_codeact_failed",
        why=f"got {outcome.source}",
    )
    assert_true(
        "fallback compile_one was invoked",
        called == [True],
    )
    assert_true(
        "fallback_reason names proposal_validation_failed",
        outcome.fallback_reason == "proposal_validation_failed",
        why=str(outcome.fallback_reason),
    )
    assert_true(
        "proposal_errors surface from validator",
        len(outcome.proposal_errors) >= 1,
    )


def test_no_tool_call_falls_back_to_compile_one() -> None:
    print("\n--- 6. silent stub (no tool calls) routes to compile_one ---")
    fallback_pkg = {"compiler_strategy": "direct_ir_v1", "compiled": {}}
    called: List[bool] = []

    async def _stub_compile_one(*_a, **_kw):
        called.append(True)
        return fallback_pkg

    orig = P.compile_one
    P.compile_one = _stub_compile_one  # type: ignore[assignment]
    try:
        outcome = asyncio.run(_run_with_stub([_empty_call()]))
    finally:
        P.compile_one = orig  # type: ignore[assignment]

    assert_true(
        "source is fallback_codeact_failed",
        outcome.source == "fallback_codeact_failed",
        why=f"got {outcome.source}",
    )
    assert_true(
        "fallback compile_one was invoked",
        called == [True],
    )
    assert_true(
        "fallback_reason is no_tool_call",
        outcome.fallback_reason == "no_tool_call",
        why=str(outcome.fallback_reason),
    )


def main() -> None:
    test_codeact_flag_default_off_and_truthy()
    test_propose_final_happy_path()
    test_package_consumable_by_apply_helpers()
    test_compile_one_fallback_branch()
    test_invalid_proposal_falls_back_to_compile_one()
    test_no_tool_call_falls_back_to_compile_one()
    print("\nAll dice CodeAct agent checks passed.")


if __name__ == "__main__":
    main()
