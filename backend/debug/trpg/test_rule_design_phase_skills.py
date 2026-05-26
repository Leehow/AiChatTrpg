"""Phase-skill smokes for the M2 ReAct redesign.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_rule_design_phase_skills.py

Covers (no DB, no LLM):

1. `PHASE_SKILLS` keys cover every entry in `defaults.PHASES` so a
   future phase addition fails loudly here instead of silently falling
   back to `intake`.
2. Every tool name listed by a `PhaseSkill` resolves in the tool
   registry (`_TOOL_INDEX`); skills cannot advertise a name that does
   not exist.
3. Registry gating is a single source of truth: `PHASE_TOOLSETS[p]`
   equals `PHASE_SKILLS[p].tools` for every phase, and
   `allowed_tool_names_for_draft` returns a subset whose order matches
   the skill's tuple (modulo names actually registered).
4. Prompt composition splices in only the active phase fragment.
   `build_system_prompt(skill_fragment=X)` includes X and excludes
   every other phase's distinctive header marker.
5. `select_skill_for_draft` returns the right skill for ORM-style,
   dict, nested-state, None, and unknown-phase drafts.
6. Each `done_when` is a callable taking (summary, report) and gives
   a sensible boolean for a couple of fixture inputs.

The base prompt content invariants (cheat-sheet phrases, no stale
prohibitions) are still owned by
`backend/debug/trpg/test_rule_design_agent_p0_6_schema.py`; this file
focuses on the skill abstraction itself.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.rule_editor.design_state.defaults import PHASES  # noqa: E402
from agents.rule_editor.phase_skills import (  # noqa: E402
    PHASE_SKILLS,
    PhaseSkill,
    select_skill_for_draft,
)
from agents.rule_editor.prompts import build_system_prompt  # noqa: E402
from agents.rule_editor.tools import (  # noqa: E402
    allowed_tool_names_for_draft,
)
from agents.rule_editor.tools.registry import (  # noqa: E402
    PHASE_TOOLSETS,
    _TOOL_INDEX,
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
    return SimpleNamespace(design_phase=phase, design_state={})


# ---------------------------------------------------------------------------
# 1. PHASE_SKILLS covers defaults.PHASES
# ---------------------------------------------------------------------------


def test_phase_coverage() -> None:
    print("\n--- 1. PHASE_SKILLS covers defaults.PHASES ---")
    missing = set(PHASES) - set(PHASE_SKILLS.keys())
    assert_true(
        "every PHASES entry has a PhaseSkill",
        not missing,
        why=f"missing={sorted(missing)}",
    )
    extras = set(PHASE_SKILLS.keys()) - set(PHASES)
    assert_true(
        "no stray PHASE_SKILLS keys outside defaults.PHASES",
        not extras,
        why=f"extras={sorted(extras)}",
    )
    for phase, skill in PHASE_SKILLS.items():
        assert_true(
            f"PHASE_SKILLS[{phase!r}] is a PhaseSkill",
            isinstance(skill, PhaseSkill),
        )
        assert_eq(
            f"PHASE_SKILLS[{phase!r}].phase == key",
            skill.phase, phase,
        )
        assert_true(
            f"PHASE_SKILLS[{phase!r}].tools non-empty",
            bool(skill.tools),
        )
        assert_true(
            f"PHASE_SKILLS[{phase!r}].prompt_fragment non-empty",
            bool(skill.prompt_fragment.strip()),
        )
        assert_true(
            f"PHASE_SKILLS[{phase!r}].done_when callable",
            callable(skill.done_when),
        )


# ---------------------------------------------------------------------------
# 2. Every advertised tool name exists in the registry
# ---------------------------------------------------------------------------


def test_skill_tool_names_exist() -> None:
    print("\n--- 2. skill tools exist in registry ---")
    for phase, skill in PHASE_SKILLS.items():
        unknown = [name for name in skill.tools if name not in _TOOL_INDEX]
        assert_true(
            f"phase {phase!r}: every skill tool resolves in registry",
            not unknown,
            why=f"unknown={unknown}",
        )


# ---------------------------------------------------------------------------
# 3. Registry gating matches skill toolsets (single source of truth)
# ---------------------------------------------------------------------------


def test_registry_matches_skills() -> None:
    print("\n--- 3. PHASE_TOOLSETS mirrors PHASE_SKILLS ---")
    assert_eq(
        "PHASE_TOOLSETS keys == PHASE_SKILLS keys",
        set(PHASE_TOOLSETS.keys()),
        set(PHASE_SKILLS.keys()),
    )
    for phase, skill in PHASE_SKILLS.items():
        assert_eq(
            f"PHASE_TOOLSETS[{phase!r}] == PHASE_SKILLS[{phase!r}].tools",
            PHASE_TOOLSETS[phase],
            skill.tools,
        )
        # allowed_tool_names_for_draft filters down to registry hits
        # while preserving the skill's order. Make sure that filtered
        # list equals the skill's tools intersected with the registry.
        expected = [n for n in skill.tools if n in _TOOL_INDEX]
        actual = allowed_tool_names_for_draft(_fake_draft(phase))
        assert_eq(
            f"allowed_tool_names_for_draft({phase!r}) == skill ∩ registry",
            actual,
            expected,
        )


# ---------------------------------------------------------------------------
# 4. Prompt composition includes only the active phase fragment
# ---------------------------------------------------------------------------


def _phase_marker(phase: str) -> str:
    """Each fragment opens with `## Phase: <phase>` -- use that as a
    distinctive marker that should appear only when the matching
    fragment is active."""
    return f"## Phase: {phase}"


def test_prompt_composition_active_phase_only() -> None:
    print("\n--- 4. prompt composition: only the active fragment ---")
    base_prompt = build_system_prompt()
    for phase in PHASE_SKILLS:
        assert_true(
            f"base prompt: no phase marker `{phase}` leaks without fragment",
            _phase_marker(phase) not in base_prompt,
        )

    # When a fragment is passed, its marker appears; other phase markers
    # do NOT (the fragments themselves never mention sibling phases by
    # marker, only by name in advance/back instructions).
    for phase, skill in PHASE_SKILLS.items():
        prompt = build_system_prompt(
            skill_fragment=skill.prompt_fragment,
        )
        assert_true(
            f"phase {phase!r}: active marker present",
            _phase_marker(phase) in prompt,
        )
        # The full fragment text appears verbatim (whitespace-stripped)
        # in the assembled prompt.
        assert_true(
            f"phase {phase!r}: full prompt_fragment appears in prompt",
            skill.prompt_fragment in prompt,
        )
        # No other phase's marker appears.
        for other in PHASE_SKILLS:
            if other == phase:
                continue
            assert_true(
                f"phase {phase!r}: sibling marker `{other}` absent",
                _phase_marker(other) not in prompt,
                why=f"unexpected marker `{_phase_marker(other)}` in prompt",
            )

    # Compatibility: existing zero-arg call path still produces a
    # string that contains the base op cheat sheet. (The detailed
    # base-content invariants are in test_rule_design_agent_p0_6_schema.)
    assert_true(
        "build_system_prompt() still returns non-empty body",
        bool(base_prompt.strip()),
    )
    assert_true(
        "build_system_prompt() still mentions apply_design_ops",
        "apply_design_ops" in base_prompt,
    )

    # Compatibility: build_system_prompt(context_block=...) without a
    # skill fragment still appends the context block.
    block = "tools_available: read_draft"
    composed = build_system_prompt(context_block=block)
    assert_true(
        "build_system_prompt(context_block=...) still splices the block",
        block in composed,
    )


# ---------------------------------------------------------------------------
# 5. select_skill_for_draft accepts the same shapes as _resolve_phase
# ---------------------------------------------------------------------------


def test_select_skill_for_draft_shapes() -> None:
    print("\n--- 5. select_skill_for_draft shapes ---")
    assert_eq(
        "None draft -> intake skill",
        select_skill_for_draft(None).phase,
        "intake",
    )
    assert_eq(
        "ORM-style with design_phase set",
        select_skill_for_draft(
            SimpleNamespace(design_phase="resolution_model", design_state={})
        ).phase,
        "resolution_model",
    )
    assert_eq(
        "plain dict with design_phase",
        select_skill_for_draft({"design_phase": "ready"}).phase,
        "ready",
    )
    assert_eq(
        "plain dict, phase nested in design_state",
        select_skill_for_draft(
            {"design_state": {"phase": "core_loop"}}
        ).phase,
        "core_loop",
    )
    assert_eq(
        "unknown phase falls back to intake skill",
        select_skill_for_draft(
            SimpleNamespace(design_phase="bogus_xyz")
        ).phase,
        "intake",
    )
    # Same skill instance is returned for the same phase (frozen dataclass
    # in PHASE_SKILLS, so identity-equality is meaningful).
    intake_one = select_skill_for_draft(None)
    intake_two = select_skill_for_draft(
        SimpleNamespace(design_phase="intake", design_state={})
    )
    assert_true(
        "intake skill is the singleton PHASE_SKILLS entry",
        intake_one is intake_two is PHASE_SKILLS["intake"],
    )


# ---------------------------------------------------------------------------
# 6. done_when helpers respond to summary / report fields
# ---------------------------------------------------------------------------


def test_done_when_helpers() -> None:
    print("\n--- 6. done_when helpers ---")
    intake = PHASE_SKILLS["intake"]
    assert_true(
        "intake.done_when False for empty summary",
        intake.done_when({}, {}) is False,
    )
    assert_true(
        "intake.done_when True when brief.concept_preview filled",
        intake.done_when(
            {"brief": {"concept_preview": "ghost hunters"}}, {}
        ) is True,
    )

    blueprint = PHASE_SKILLS["blueprint_selection"]
    assert_true(
        "blueprint_selection.done_when True when blueprint.id set",
        blueprint.done_when({"blueprint": {"id": "coc_classic"}}, {})
        is True,
    )
    assert_true(
        "blueprint_selection.done_when False on empty blueprint",
        blueprint.done_when({"blueprint": {"id": ""}}, {}) is False,
    )

    resolution = PHASE_SKILLS["resolution_model"]
    assert_true(
        "resolution_model.done_when True when section flag set",
        resolution.done_when(
            {"sections": {"resolution_mechanic_filled": True}}, {}
        ) is True,
    )
    assert_true(
        "resolution_model.done_when False otherwise",
        resolution.done_when({"sections": {}}, {}) is False,
    )

    ready = PHASE_SKILLS["ready"]
    assert_true(
        "ready.done_when True when validator can_compile",
        ready.done_when({}, {"can_compile": True}) is True,
    )
    assert_true(
        "ready.done_when False when validator blocks",
        ready.done_when({}, {"can_compile": False}) is False,
    )


def main() -> None:
    test_phase_coverage()
    test_skill_tool_names_exist()
    test_registry_matches_skills()
    test_prompt_composition_active_phase_only()
    test_select_skill_for_draft_shapes()
    test_done_when_helpers()
    print("\nAll phase-skill smokes passed.")


if __name__ == "__main__":
    main()
