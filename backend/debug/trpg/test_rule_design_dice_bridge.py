"""Bridge smokes for the M3 main-agent dice compile path.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_rule_design_dice_bridge.py

Covers (no DB, no live LLM):

1. `request_dice_compile` is registered and lives in the dice bridge
   module (so the single-writer audit stays mechanical).
2. JSON schema accepts `{name, description, engine_hint}` with
   `name`/`description` required.
3. Tool is advertised only in `resolution_model`, `procedures`,
   `playtest`. Hidden in `intake`, `blueprint_selection`,
   `core_loop`, `character_model`, `catalogs`, `ready`.
4. `P0_6_HIDDEN_NAMES` still excluded in every phase.
5. `strip_internal_markers` drops the bridge markers.
6. `events_from_tool_payload` emits `dice_compile_progress` then
   `dice_state_changed` when markers are present; nothing otherwise.
7. With a monkeypatched helper, executing the tool returns a payload
   carrying both markers and routes through the shared
   `compile_and_apply_dice_procedure` boundary.
8. `tools_design.compile_and_apply_dice_procedure` exists with the
   expected callable shape, so the dice agent still routes through it.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from agents.rule_editor import agent_context  # noqa: E402
from agents.rule_editor.phase_skills import PHASE_SKILLS  # noqa: E402
from agents.rule_editor.tools import (  # noqa: E402
    P0_6_HIDDEN_NAMES,
    ToolResult,
    allowed_tool_names_for_draft,
    get_tool,
)
from agents.rule_editor.tools.dice_bridge import (  # noqa: E402
    DICE_COMPILE_PROGRESS_MARKER,
    DICE_STATE_CHANGED_MARKER,
    request_dice_compile_tool,
)
from agents.rule_editor_dice import tools_design  # noqa: E402


def fail(label: str, why: str = "") -> None:
    print(f"FAIL: {label} {why}")
    sys.exit(1)


def assert_true(label: str, cond: bool, why: str = "") -> None:
    if not cond:
        fail(label, why)
    print(f"OK: {label}")


def assert_eq(label: str, actual, expected) -> None:
    if actual != expected:
        print(f"FAIL: {label}\n  expected: {expected!r}\n  actual:   {actual!r}")
        sys.exit(1)
    print(f"OK: {label}")


def _fake_draft(phase: str | None) -> SimpleNamespace:
    return SimpleNamespace(design_phase=phase, design_state={})


_ADVERTISED_IN: frozenset[str] = frozenset(
    {"resolution_model", "procedures", "playtest"}
)


# --- 1. Registration + module ownership -------------------------------------


def test_tool_registered_in_dice_bridge_module() -> None:
    print("\n--- 1. request_dice_compile registration ---")
    tool = get_tool("request_dice_compile")
    assert_true(
        "tool registered in the main editor registry",
        tool is not None and tool.name == "request_dice_compile",
    )
    assert_true(
        "tool is the same object exported by dice_bridge",
        tool is request_dice_compile_tool,
    )
    src = (
        BACKEND_ROOT / "agents" / "rule_editor" / "tools" / "dice_bridge.py"
    ).read_text()
    assert_true(
        "dice_bridge does not import _merge_into_dice_ir",
        "_merge_into_dice_ir" not in src,
    )
    assert_true(
        "dice_bridge does not write parsed_v6['dice_ir']",
        'parsed_v6["dice_ir"]' not in src and "parsed_v6['dice_ir']" not in src,
    )
    assert_true(
        "dice_bridge does not call apply_dice_proposal "
        "(routed via compile_and_apply_dice_procedure)",
        "apply_dice_proposal(" not in src,
    )
    assert_true(
        "dice_bridge calls compile_and_apply_dice_procedure",
        "compile_and_apply_dice_procedure(" in src,
    )


# --- 2. JSON schema shape ---------------------------------------------------


def test_tool_json_schema_shape() -> None:
    print("\n--- 2. JSON schema shape ---")
    schema = request_dice_compile_tool.json_schema
    assert_eq("schema.type == 'object'", schema.get("type"), "object")
    props = schema.get("properties") or {}
    assert_eq(
        "property keys",
        set(props.keys()),
        {"name", "description", "engine_hint"},
    )
    assert_eq(
        "required fields",
        sorted(list(schema.get("required") or [])),
        ["description", "name"],
    )
    assert_true(
        "additionalProperties is False",
        schema.get("additionalProperties") is False,
    )
    for key in ("name", "description", "engine_hint"):
        assert_eq(
            f"{key} typed as string",
            (props.get(key) or {}).get("type"), "string",
        )


# --- 3. Advertised phases ---------------------------------------------------


def test_request_dice_compile_phase_advertisement() -> None:
    print("\n--- 3. request_dice_compile phase advertisement ---")
    for phase, skill in PHASE_SKILLS.items():
        has_tool = "request_dice_compile" in skill.tools
        want = phase in _ADVERTISED_IN
        assert_true(
            f"PHASE_SKILLS[{phase!r}].tools "
            f"{'contains' if want else 'omits'} request_dice_compile",
            has_tool is want,
        )
        names = set(allowed_tool_names_for_draft(_fake_draft(phase)))
        assert_true(
            f"phase {phase!r}: request_dice_compile "
            f"{'advertised' if want else 'hidden'}",
            ("request_dice_compile" in names) is want,
        )


# --- 4. Hidden writers never advertised -------------------------------------


def test_hidden_writers_still_hidden() -> None:
    print("\n--- 4. hidden parsed_v6 writers stay hidden ---")
    for phase in PHASE_SKILLS:
        advertised = set(allowed_tool_names_for_draft(_fake_draft(phase)))
        leaks = advertised & set(P0_6_HIDDEN_NAMES)
        assert_true(
            f"phase {phase!r}: no hidden tool leaks",
            not leaks,
            why=f"leaked={sorted(leaks)}",
        )


# --- 5. Markers stripped from LLM-visible payload ---------------------------


def test_strip_internal_markers_removes_bridge_markers() -> None:
    print("\n--- 5. strip_internal_markers strips bridge markers ---")
    payload = {
        "ok": True,
        "compiled_specs": [{"procedure_id": "p1"}],
        DICE_STATE_CHANGED_MARKER: True,
        DICE_COMPILE_PROGRESS_MARKER: {
            "source": "direct", "primitive_calls": 0,
            "iters": 0, "fallback_reason": None,
        },
    }
    public = agent_context.strip_internal_markers(payload)
    assert_eq(
        "public payload keys exclude markers",
        sorted(public.keys()), ["compiled_specs", "ok"],
    )


# --- 6. events_from_tool_payload mapping ------------------------------------


def test_events_from_tool_payload_emits_dice_events() -> None:
    print("\n--- 6. events_from_tool_payload emits dice events ---")
    payload = {
        "ok": True,
        DICE_STATE_CHANGED_MARKER: True,
        DICE_COMPILE_PROGRESS_MARKER: {
            "source": "codeact", "primitive_calls": 4,
            "iters": 2, "fallback_reason": None,
        },
    }
    events = agent_context.events_from_tool_payload(
        payload=payload, edit_id=None,
    )
    assert_eq(
        "emits dice_compile_progress then dice_state_changed",
        [ev["type"] for ev in events],
        ["dice_compile_progress", "dice_state_changed"],
    )
    progress = events[0]
    assert_eq("progress.source", progress["source"], "codeact")
    assert_eq("progress.primitive_calls", progress["primitive_calls"], 4)
    assert_eq("progress.iters", progress["iters"], 2)
    assert_true(
        "progress.fallback_reason is None",
        progress.get("fallback_reason") is None,
    )

    quiet = agent_context.events_from_tool_payload(
        payload={"ok": True}, edit_id=None,
    )
    types_quiet = [ev["type"] for ev in quiet]
    assert_true(
        "no dice events without markers",
        "dice_state_changed" not in types_quiet
        and "dice_compile_progress" not in types_quiet,
    )


# --- 7. Executor stamps markers + routes through helper ---------------------


@dataclass
class _FakeCtx:
    db: object = None
    owner_id: str = "u1"
    draft_id: str = "d1"
    assistant_message_id: str | None = None


def _build_outcome(source: str = "direct") -> tools_design.CompileAndApplyOutcome:
    return tools_design.CompileAndApplyOutcome(
        payload={
            "ok": True,
            "compiled_specs": [{
                "procedure_id": "skill_check", "name": "Skill check",
                "engine": "generic_resolution_v1", "validation_ok": True,
                "samples_passed": 2, "samples_failed": 0,
                "sample_summary": [],
            }],
            "unsupported": [],
        },
        source=source, primitive_calls=3, iters=1, fallback_reason=None,
    )


def test_executor_stamps_markers_and_routes_through_helper() -> None:
    print("\n--- 7. executor stamps markers + routes via helper ---")
    captured: dict[str, object] = {}

    async def fake_helper(
        ctx, *, name, description, engine_hint="",
    ):
        captured["name"] = name
        captured["description"] = description
        captured["engine_hint"] = engine_hint
        return _build_outcome(source="direct")

    # Patch the source module's binding. The bridge executor imports
    # the helper lazily inside the function body (to avoid a circular
    # import at module load), so the lookup happens against the
    # patched symbol at call time.
    real = tools_design.compile_and_apply_dice_procedure
    tools_design.compile_and_apply_dice_procedure = fake_helper  # type: ignore[assignment]
    try:
        result: ToolResult = asyncio.run(
            request_dice_compile_tool.execute(
                _FakeCtx(),  # type: ignore[arg-type]
                {
                    "name": "skill_check",
                    "description": "roll d100 under skill",
                    "engine_hint": "coc_7e_d100",
                },
            )
        )
    finally:
        tools_design.compile_and_apply_dice_procedure = real  # type: ignore[assignment]

    assert_true("executor returns a ToolResult", isinstance(result, ToolResult))
    payload = result.payload
    assert_true(
        "payload carries dice_state_changed marker",
        payload.get(DICE_STATE_CHANGED_MARKER) is True,
    )
    progress = payload.get(DICE_COMPILE_PROGRESS_MARKER)
    assert_true(
        "payload carries dice_compile_progress marker (dict)",
        isinstance(progress, dict),
    )
    assert_eq("progress.source", progress["source"], "direct")  # type: ignore[index]
    assert_eq("captured.name", captured.get("name"), "skill_check")
    assert_eq(
        "captured.description",
        captured.get("description"), "roll d100 under skill",
    )
    assert_eq(
        "captured.engine_hint",
        captured.get("engine_hint"), "coc_7e_d100",
    )
    assert_true(
        "public payload has ok=True and compiled_specs",
        payload.get("ok") is True
        and isinstance(payload.get("compiled_specs"), list),
    )


# --- 8. Shared helper shape --------------------------------------------------


def test_shared_helper_shape() -> None:
    print("\n--- 8. shared helper shape ---")
    helper = getattr(tools_design, "compile_and_apply_dice_procedure", None)
    assert_true(
        "tools_design exposes compile_and_apply_dice_procedure",
        callable(helper),
    )
    outcome_cls = getattr(tools_design, "CompileAndApplyOutcome", None)
    assert_true(
        "tools_design exposes CompileAndApplyOutcome",
        outcome_cls is not None,
    )
    src = (
        BACKEND_ROOT / "agents" / "rule_editor_dice" / "tools_design.py"
    ).read_text()
    assert_true(
        "tools_design._design_dice_procedure calls "
        "compile_and_apply_dice_procedure",
        "compile_and_apply_dice_procedure(" in src,
    )


def main() -> None:
    test_tool_registered_in_dice_bridge_module()
    test_tool_json_schema_shape()
    test_request_dice_compile_phase_advertisement()
    test_hidden_writers_still_hidden()
    test_strip_internal_markers_removes_bridge_markers()
    test_events_from_tool_payload_emits_dice_events()
    test_executor_stamps_markers_and_routes_through_helper()
    test_shared_helper_shape()
    print("\nAll dice bridge smokes passed.")


if __name__ == "__main__":
    main()
