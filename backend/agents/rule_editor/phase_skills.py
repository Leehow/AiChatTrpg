"""Phase skill specs for the rule-design ReAct loop.

A `PhaseSkill` bundles policy data for one design phase:

  - `phase`           -- phase id (matches `defaults.PHASES`).
  - `tools`           -- tool names the LLM may call in this phase.
  - `prompt_fragment` -- short string spliced into the system prompt
                         for this phase only.
  - `done_when`       -- deterministic helper returning True when the
                         phase's local goals are met (reads the design
                         summary + validation report).

This module is pure Python policy: no FastAPI / ORM / React imports.
The tool registry imports `PHASE_SKILLS` and derives its phase tool
table from it, so skills are the single source of truth for what is
advertised in each phase. `prompts.build_system_prompt` accepts the
active fragment so the agent loop can splice in the right one for the
current draft.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .design_state.defaults import PHASES


DoneCheck = Callable[[dict, dict], bool]


# --- Tool sets --------------------------------------------------------------
# Kept here (not in `tools/registry.py`) so PHASE_SKILLS is the single
# source of truth. The registry re-exports a `PHASE_TOOLSETS` view for
# back-compat with the M1 phase-gating smoke.

_BASE_TOOL_NAMES: tuple[str, ...] = (
    # Read / inspect
    "read_draft",
    "read_design_state",
    "validate_design_state",
    # Search the user library / world
    "search_my_rulesets",
    "read_ruleset",
    "grep_in_ruleset",
    "search_my_modules",
    "read_module",
    "list_my_sessions",
    "read_session",
    "web_search",
    # Compile (validator-gated; the LLM can discover blockers via the
    # structured `blocked` payload it returns)
    "compile_design",
)

# Blueprint trio: only advertised in `intake` + `blueprint_selection`.
# Re-applying a blueprint mid-design risks overwriting filled sections.
_BLUEPRINT_TRIO: tuple[str, ...] = (
    "list_blueprints",
    "recommend_blueprints",
    "apply_blueprint",
)

# Authoring writer kept across every authoring phase so the LLM can
# backtrack (e.g., fix an attribute, switch phase via set_phase op).
# `ready` deliberately omits it -- compile-only terminal state.
_AUTHORING_WRITER: tuple[str, ...] = ("apply_design_ops",)


# Dice bridge tool. Only advertised in phases where authoring a dice
# procedure is on-task: `resolution_model` (defining the core check
# mechanic), `procedures` (per-action procedures may need their own
# dice IR entries), and `playtest` (smoke-test before compile may
# reveal a missing/incorrect procedure). Earlier phases (`intake`,
# `blueprint_selection`, `core_loop`, `character_model`, `catalogs`)
# either pre-date the resolution decision or are off-topic; `ready`
# is compile-only.
_DICE_BRIDGE: tuple[str, ...] = ("request_dice_compile",)


# --- Done checks ------------------------------------------------------------
# Each takes the structured `design_summary` (from `read_design_state`)
# and the `validation_report`. Reading both keeps the policy expressible
# without requiring the full design_state dict.


def _intake_done(summary: dict, _report: dict) -> bool:
    brief = (summary or {}).get("brief") or {}
    concept = brief.get("concept_preview") or brief.get("concept")
    return bool(concept)


def _blueprint_done(summary: dict, _report: dict) -> bool:
    blueprint = (summary or {}).get("blueprint") or {}
    return bool(blueprint.get("id"))


def _core_loop_done(summary: dict, _report: dict) -> bool:
    sections = (summary or {}).get("sections") or {}
    return bool(sections.get("core_loop_filled"))


def _character_model_done(summary: dict, _report: dict) -> bool:
    sections = (summary or {}).get("sections") or {}
    return int(sections.get("character_attribute_count") or 0) > 0


def _resolution_done(summary: dict, _report: dict) -> bool:
    sections = (summary or {}).get("sections") or {}
    return bool(sections.get("resolution_mechanic_filled"))


def _procedures_done(summary: dict, _report: dict) -> bool:
    sections = (summary or {}).get("sections") or {}
    return int(sections.get("procedure_count") or 0) >= 1


def _catalogs_done(summary: dict, _report: dict) -> bool:
    sections = (summary or {}).get("sections") or {}
    counts = sections.get("catalog_counts") or {}
    return any(
        int(counts.get(name) or 0) > 0
        for name in ("skills", "actions", "resources", "gear")
    )


def _playtest_done(_summary: dict, report: dict) -> bool:
    return bool((report or {}).get("can_compile"))


def _ready_done(_summary: dict, report: dict) -> bool:
    return bool((report or {}).get("can_compile"))


# --- Prompt fragments -------------------------------------------------------
# Per-phase reminders spliced into the system prompt. Each fragment is
# short (~10 lines) so the global rules in `prompts._BASE_PROMPT` stay
# the substantive guidance and the fragment is purely "what to do right
# now". No fragment duplicates the base op cheat sheet.

_INTAKE_FRAGMENT = """
## Phase: intake

You just opened this draft. Goal of this phase:
- Understand the user's pitch (concept, tone, genre, complexity).
- Call `recommend_blueprints` early to anchor candidates if the brief
  is concrete enough.
- Do NOT apply ops on a single line of input -- ask one or two compact
  clarifying questions, or wait for the user to confirm direction
  ("go", "你决定", "build it", ...).
- When ready, advance via apply_design_ops `set_phase` to
  `blueprint_selection`.
"""

_BLUEPRINT_SELECTION_FRAGMENT = """
## Phase: blueprint_selection

A blueprint anchors the slot list and seeds sections. Goal of this
phase:
- Use `list_blueprints` / `recommend_blueprints` to surface candidates.
- Apply one with `apply_blueprint`; the loader preserves any sections
  already filled, so partial state is safe.
- Record the brief alongside (set_brief_field, add_assumption,
  taxonomy).
- Advance via set_phase to `core_loop` once a blueprint is in place.
"""

_CORE_LOOP_FRAGMENT = """
## Phase: core_loop

Author the core gameplay loop:
- Use `apply_design_ops` with `set_core_loop` (summary, phases[],
  pacing).
- Flip the `core_loop` slot to `filled` via `set_slot_status` in the
  same or the next batch.
- Advance via set_phase to `character_model` once the loop is
  recorded.
"""

_CHARACTER_MODEL_FRAGMENT = """
## Phase: character_model

Author the character model:
- Use `apply_design_ops` with `set_character_model` (archetypes[],
  attributes[], derived_stats[], progression_model).
- Each attributes / derived_stats entry should at minimum be
  `{"id": ..., "name": ...}`.
- Flip the `character_attributes` slot to `filled` via
  `set_slot_status` once attributes are recorded.
- Advance via set_phase to `resolution_model`.
"""

_RESOLUTION_MODEL_FRAGMENT = """
## Phase: resolution_model

Author the resolution mechanic (model only -- runtime adjudication is
deterministic and lives elsewhere):
- `set_resolution_model` (mechanic, dice, success_thresholds[],
  notes).
- Flip the `resolution_model` slot to `filled` after recording it.
- Optionally call `request_dice_compile` to land a default check
  procedure (~10-30s, slow); leave dice authoring to the dice tab
  for iterative work.
- Advance via set_phase to `procedures` once the model is in.
"""

_PROCEDURES_FRAGMENT = """
## Phase: procedures

Author structured procedures (combat / investigation / chase / ...):
- Use `upsert_procedure` with `id` + `procedure` object (`name`,
  `when`, `steps[]`).
- Flip matching slots via `set_slot_status` when each procedure is
  authored.
- Use `request_dice_compile` sparingly when a procedure needs its
  own dice IR entry that the resolution-model default does not
  cover; leave iterative dice authoring to the dice tab.
- Advance via set_phase to `catalogs` once the procedures required by
  the blueprint are filled.
"""

_CATALOGS_FRAGMENT = """
## Phase: catalogs

Author the id-keyed catalogs (skills, actions, resources, gear):
- Use `upsert_catalog_entry` (catalog, id, entry with `name` plus
  `summary` or `description`).
- Flip catalog-related slots via `set_slot_status` once their entries
  are in.
- Advance via set_phase to `playtest` once required catalog entries
  are recorded.
"""

_PLAYTEST_FRAGMENT = """
## Phase: playtest

Smoke-test the design before compile:
- Re-read `read_design_state`; confirm validator `can_compile=true`.
- If `ready_blockers` lists codes, backtrack via apply_design_ops to
  fix the underlying gap; do not just flip the phase.
- If `needs_dice_compile` is true or a required procedure is missing
  a dice IR entry, you may call `request_dice_compile` to land it
  before advancing.
- Advance via set_phase to `ready` once all blockers are cleared.
"""

_READY_FRAGMENT = """
## Phase: ready

Validator says the design is ready. The only LLM move in this phase
is `compile_design`:
- Call `compile_design`. On success parsed_v6 is replaced and an edit
  row is recorded.
- If the validator surprises you with a block, return to an authoring
  phase via UI; `apply_design_ops` is NOT advertised here so do not
  attempt to backtrack via tool in this turn.
"""


# --- Dataclass + table ------------------------------------------------------


@dataclass(frozen=True)
class PhaseSkill:
    """Policy data for one design phase. See module docstring."""

    phase: str
    tools: tuple[str, ...]
    prompt_fragment: str
    done_when: DoneCheck


def _skill(
    phase: str,
    tools: tuple[str, ...],
    fragment: str,
    done: DoneCheck,
) -> PhaseSkill:
    return PhaseSkill(
        phase=phase,
        tools=tools,
        prompt_fragment=fragment.strip("\n"),
        done_when=done,
    )


PHASE_SKILLS: dict[str, PhaseSkill] = {
    "intake": _skill(
        "intake",
        _BASE_TOOL_NAMES + _AUTHORING_WRITER + _BLUEPRINT_TRIO,
        _INTAKE_FRAGMENT,
        _intake_done,
    ),
    "blueprint_selection": _skill(
        "blueprint_selection",
        _BASE_TOOL_NAMES + _AUTHORING_WRITER + _BLUEPRINT_TRIO,
        _BLUEPRINT_SELECTION_FRAGMENT,
        _blueprint_done,
    ),
    "core_loop": _skill(
        "core_loop",
        _BASE_TOOL_NAMES + _AUTHORING_WRITER,
        _CORE_LOOP_FRAGMENT,
        _core_loop_done,
    ),
    "character_model": _skill(
        "character_model",
        _BASE_TOOL_NAMES + _AUTHORING_WRITER,
        _CHARACTER_MODEL_FRAGMENT,
        _character_model_done,
    ),
    "resolution_model": _skill(
        "resolution_model",
        _BASE_TOOL_NAMES + _AUTHORING_WRITER + _DICE_BRIDGE,
        _RESOLUTION_MODEL_FRAGMENT,
        _resolution_done,
    ),
    "procedures": _skill(
        "procedures",
        _BASE_TOOL_NAMES + _AUTHORING_WRITER + _DICE_BRIDGE,
        _PROCEDURES_FRAGMENT,
        _procedures_done,
    ),
    "catalogs": _skill(
        "catalogs",
        _BASE_TOOL_NAMES + _AUTHORING_WRITER,
        _CATALOGS_FRAGMENT,
        _catalogs_done,
    ),
    "playtest": _skill(
        "playtest",
        _BASE_TOOL_NAMES + _AUTHORING_WRITER + _DICE_BRIDGE,
        _PLAYTEST_FRAGMENT,
        _playtest_done,
    ),
    "ready": _skill(
        "ready",
        _BASE_TOOL_NAMES,
        _READY_FRAGMENT,
        _ready_done,
    ),
}


# Static guard: PHASE_SKILLS must cover every value in `defaults.PHASES`.
# A new phase landing in defaults without an accompanying skill spec
# fails import here so the omission is caught before the agent loop
# silently falls back to `intake`.
_MISSING_PHASES = tuple(p for p in PHASES if p not in PHASE_SKILLS)
if _MISSING_PHASES:  # pragma: no cover - guarded by tests as well
    raise RuntimeError(
        "PHASE_SKILLS missing entries for: " + ", ".join(_MISSING_PHASES)
    )


def _resolve_phase(draft: Any) -> str:
    """Extract the design_phase string from a draft-like object.

    Accepts:
      - an ORM `RulesetDraft` (`.design_phase` column),
      - a plain mapping with `design_phase` / `design_state.phase`,
      - `None` (treated as a fresh draft -> `intake`).
    Falls back to `intake` for any unrecognized phase so callers are
    never left with `None`.
    """
    if draft is None:
        return "intake"
    phase: Any = None
    if hasattr(draft, "design_phase"):
        phase = getattr(draft, "design_phase", None)
    if not phase and isinstance(draft, dict):
        phase = draft.get("design_phase")
        if not phase:
            state = draft.get("design_state") or {}
            if isinstance(state, dict):
                phase = state.get("phase")
    if not phase and hasattr(draft, "design_state"):
        state = getattr(draft, "design_state", None)
        if isinstance(state, dict):
            phase = state.get("phase")
    phase_str = str(phase or "intake")
    if phase_str not in PHASE_SKILLS:
        return "intake"
    return phase_str


def select_skill_for_draft(draft: Any) -> PhaseSkill:
    """Return the skill for `draft`'s current phase, falling back to
    the `intake` skill for unknown or unset phases."""
    return PHASE_SKILLS[_resolve_phase(draft)]


__all__ = [
    "DoneCheck",
    "PHASE_SKILLS",
    "PhaseSkill",
    "select_skill_for_draft",
]
