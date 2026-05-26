"""Phase-aware tool gating smokes for the M1 ReAct redesign.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_rule_design_phase_gating.py

Covers (no DB, no LLM):

1. `PHASE_TOOLSETS` keys cover every entry in `defaults.PHASES` so a
   future phase addition fails loudly here instead of silently falling
   back to `intake`.
2. Three representative phases -- `intake`, `resolution_model`,
   `ready` -- advertise different expected tool sets. `intake`
   exposes the blueprint trio + apply_design_ops, mid-authoring
   phases drop the blueprint trio but keep apply_design_ops, and
   `ready` drops apply_design_ops too (terminal compile-only state).
3. Hidden parsed_v6 writers (`P0_6_HIDDEN_NAMES`) stay rejected by
   `get_allowed_tool_for_draft` in every phase, including `intake`.
4. `_resolve_phase` accepts ORM-style attributes, plain dicts,
   nested `design_state.phase`, and unrecognized values (falls back
   to `intake`).
5. `build_tools_schema_for_draft` is the boundary the agent loop
   re-invokes after every tool call. Mutating the same draft object's
   phase between calls produces a different advertised tool list,
   which is the mechanism the in-loop refresh relies on.

The actual `run_agent_turn` refresh is a single line that re-invokes
`build_tools_schema_for_draft(draft)` after the tool-call inner loop.
Reproducing a real OpenAI streaming round trip in a unit test would
require mocking the AsyncOpenAI client; the helper-boundary test
below covers the same invariant deterministically.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.rule_editor.design_state.defaults import PHASES  # noqa: E402
from agents.rule_editor.tools import (  # noqa: E402
    P0_6_HIDDEN_NAMES,
    allowed_tool_names_for_draft,
    build_tools_schema_for_draft,
    get_allowed_tool_for_draft,
)
from agents.rule_editor.tools.registry import (  # noqa: E402
    PHASE_TOOLSETS,
    _resolve_phase,
)


def fail(label: str, why: str = "") -> None:
    print(f"FAIL: {label} {why}")
    sys.exit(1)


def assert_true(label: str, cond: bool, why: str = "") -> None:
    if not cond:
        fail(label, why)
    print(f"OK: {label}")


def assert_eq(label, actual, expected) -> None:
    if actual != expected:
        print(f"FAIL: {label}\n  expected: {expected!r}\n  actual:   {actual!r}")
        sys.exit(1)
    print(f"OK: {label}")


def _fake_draft(phase: str | None) -> SimpleNamespace:
    """Build a minimal stand-in for `RulesetDraft` exposing only the
    column the resolver reads. Using SimpleNamespace keeps the test
    independent of the ORM and async sessions."""
    return SimpleNamespace(design_phase=phase, design_state={})


# ---------------------------------------------------------------------------
# 1. Phase coverage
# ---------------------------------------------------------------------------


def test_phase_coverage() -> None:
    print("\n--- 1. PHASE_TOOLSETS covers defaults.PHASES ---")
    missing = set(PHASES) - set(PHASE_TOOLSETS.keys())
    assert_true(
        "every PHASES entry has a PHASE_TOOLSETS row",
        not missing,
        why=f"missing={sorted(missing)}",
    )
    extras = set(PHASE_TOOLSETS.keys()) - set(PHASES)
    assert_true(
        "no stray PHASE_TOOLSETS keys outside defaults.PHASES",
        not extras,
        why=f"extras={sorted(extras)}",
    )
    for phase, names in PHASE_TOOLSETS.items():
        assert_true(
            f"PHASE_TOOLSETS[{phase!r}] is non-empty",
            bool(names),
        )


# ---------------------------------------------------------------------------
# 2. Per-phase advertised sets differ as expected
# ---------------------------------------------------------------------------


_BASE_EXPECTED: frozenset[str] = frozenset({
    "read_draft",
    "read_design_state",
    "validate_design_state",
    "search_my_rulesets",
    "read_ruleset",
    "grep_in_ruleset",
    "search_my_modules",
    "read_module",
    "list_my_sessions",
    "read_session",
    "web_search",
    "compile_design",
})

_BLUEPRINT_TRIO: frozenset[str] = frozenset({
    "list_blueprints",
    "recommend_blueprints",
    "apply_blueprint",
})


def test_intake_vs_resolution_model_vs_ready() -> None:
    print("\n--- 2. three representative phases differ ---")

    intake_names = set(allowed_tool_names_for_draft(_fake_draft("intake")))
    resolution_names = set(
        allowed_tool_names_for_draft(_fake_draft("resolution_model"))
    )
    ready_names = set(allowed_tool_names_for_draft(_fake_draft("ready")))

    # Base set is in every phase.
    for phase_name, names in (
        ("intake", intake_names),
        ("resolution_model", resolution_names),
        ("ready", ready_names),
    ):
        missing_base = _BASE_EXPECTED - names
        assert_true(
            f"{phase_name}: advertises full base set",
            not missing_base,
            why=f"missing={sorted(missing_base)}",
        )

    # intake-only delta: blueprint trio.
    assert_true(
        "intake: advertises blueprint trio",
        _BLUEPRINT_TRIO.issubset(intake_names),
    )
    assert_true(
        "resolution_model: blueprint trio hidden",
        not (_BLUEPRINT_TRIO & resolution_names),
    )
    assert_true(
        "ready: blueprint trio hidden",
        not (_BLUEPRINT_TRIO & ready_names),
    )

    # apply_design_ops is in intake + resolution_model (authoring) but
    # NOT in ready (terminal compile-only state).
    assert_true(
        "intake: apply_design_ops advertised",
        "apply_design_ops" in intake_names,
    )
    assert_true(
        "resolution_model: apply_design_ops advertised",
        "apply_design_ops" in resolution_names,
    )
    assert_true(
        "ready: apply_design_ops hidden",
        "apply_design_ops" not in ready_names,
    )

    # The three sets must be pairwise distinct.
    assert_true(
        "intake != resolution_model",
        intake_names != resolution_names,
    )
    assert_true(
        "resolution_model != ready",
        resolution_names != ready_names,
    )
    assert_true(
        "intake != ready",
        intake_names != ready_names,
    )

    # `compile_design` survives in `ready`.
    assert_true(
        "ready: compile_design still advertised",
        "compile_design" in ready_names,
    )


# ---------------------------------------------------------------------------
# 3. Hidden parsed_v6 writers stay rejected in every phase
# ---------------------------------------------------------------------------


def test_hidden_tools_rejected_per_phase() -> None:
    print("\n--- 3. hidden parsed_v6 writers rejected per phase ---")
    for phase in PHASES:
        draft = _fake_draft(phase)
        advertised = set(allowed_tool_names_for_draft(draft))
        leaks = advertised & set(P0_6_HIDDEN_NAMES)
        assert_true(
            f"phase {phase!r}: no hidden tool advertised",
            not leaks,
            why=f"leaked={sorted(leaks)}",
        )
        for hidden in P0_6_HIDDEN_NAMES:
            if get_allowed_tool_for_draft(draft, hidden) is not None:
                fail(
                    f"phase {phase!r}: hidden tool resolved via gated lookup",
                    why=hidden,
                )
    print("OK: every PHASES entry rejects every P0_6_HIDDEN_NAMES entry")


# ---------------------------------------------------------------------------
# 4. _resolve_phase accepts ORM / dict / nested / unknown shapes
# ---------------------------------------------------------------------------


def test_resolve_phase_shapes() -> None:
    print("\n--- 4. _resolve_phase shapes ---")
    assert_eq(
        "None draft -> intake",
        _resolve_phase(None), "intake",
    )
    assert_eq(
        "ORM-style with design_phase set",
        _resolve_phase(SimpleNamespace(design_phase="resolution_model")),
        "resolution_model",
    )
    assert_eq(
        "plain dict with design_phase",
        _resolve_phase({"design_phase": "ready"}),
        "ready",
    )
    assert_eq(
        "plain dict, phase nested in design_state",
        _resolve_phase({"design_state": {"phase": "core_loop"}}),
        "core_loop",
    )
    assert_eq(
        "ORM-style, phase only on design_state",
        _resolve_phase(
            SimpleNamespace(design_phase=None,
                            design_state={"phase": "catalogs"})
        ),
        "catalogs",
    )
    assert_eq(
        "unknown phase string falls back to intake",
        _resolve_phase(SimpleNamespace(design_phase="bogus_phase_xyz")),
        "intake",
    )
    assert_eq(
        "empty string falls back to intake",
        _resolve_phase(SimpleNamespace(design_phase="")),
        "intake",
    )


# ---------------------------------------------------------------------------
# 5. build_tools_schema_for_draft tracks live phase mutations
# ---------------------------------------------------------------------------


def _schema_names(draft) -> set[str]:
    return {entry["function"]["name"] for entry in
            build_tools_schema_for_draft(draft)}


def test_schema_tracks_phase_mutation() -> None:
    print("\n--- 5. schema refresh tracks phase mutation on same draft ---")
    # Same fake draft object, phase mutates between calls. This mirrors
    # what `run_agent_turn` does: after a tool call, it re-fetches the
    # draft, then re-calls `build_tools_schema_for_draft(draft)` so the
    # next LLM iteration sees the narrowed surface.
    draft = _fake_draft("intake")
    before = _schema_names(draft)
    assert_true(
        "intake schema: includes apply_blueprint",
        "apply_blueprint" in before,
    )

    draft.design_phase = "resolution_model"
    mid = _schema_names(draft)
    assert_true(
        "resolution_model schema: drops apply_blueprint",
        "apply_blueprint" not in mid,
    )
    assert_true(
        "resolution_model schema: keeps apply_design_ops",
        "apply_design_ops" in mid,
    )
    assert_true(
        "schema actually changed across phase mutation",
        before != mid,
    )

    draft.design_phase = "ready"
    after = _schema_names(draft)
    assert_true(
        "ready schema: drops apply_design_ops too",
        "apply_design_ops" not in after,
    )
    assert_true(
        "ready schema: still keeps compile_design",
        "compile_design" in after,
    )
    assert_true(
        "ready schema differs from resolution_model schema",
        after != mid,
    )

    # Final sanity: hidden tools never leak across the mutations.
    for label, names in (
        ("intake", before), ("resolution_model", mid), ("ready", after),
    ):
        leaks = names & set(P0_6_HIDDEN_NAMES)
        assert_true(
            f"{label} schema: no hidden tool leaks across refresh",
            not leaks,
            why=f"leaked={sorted(leaks)}",
        )


def main() -> None:
    test_phase_coverage()
    test_intake_vs_resolution_model_vs_ready()
    test_hidden_tools_rejected_per_phase()
    test_resolve_phase_shapes()
    test_schema_tracks_phase_mutation()
    print("\nAll phase-gating smokes passed.")


if __name__ == "__main__":
    main()
