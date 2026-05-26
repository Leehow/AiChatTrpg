"""validate_design_state -- pure validator over a DesignState dict.

Default behavior:

- Authoring writes are always allowed; the reducer never consults this module.
- Compile is blocked when any blocking issue exists.
- Required slots come from `design_state.blueprint.slots_required`. A slot
  is satisfied when `design_state.slots[slot] == "filled"`.

The validator returns a `ValidationReport` with three severity buckets, a
slot-completion view, a `can_compile` boolean, and an explicit
`ready_blockers` list so callers do not have to re-derive it from issues.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .defaults import PHASES
from .issues import DesignIssue


class SlotCompletion(BaseModel):
    required: list[str] = Field(default_factory=list)
    filled: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    drafting: list[str] = Field(default_factory=list)
    progress: float = 0.0


class ValidationReport(BaseModel):
    blocking: list[DesignIssue] = Field(default_factory=list)
    warnings: list[DesignIssue] = Field(default_factory=list)
    info: list[DesignIssue] = Field(default_factory=list)
    slots: SlotCompletion = Field(default_factory=SlotCompletion)
    can_compile: bool = False
    ready_blockers: list[str] = Field(default_factory=list)


def validate_design_state(state: dict[str, Any]) -> ValidationReport:
    """Inspect a DesignState and return blocking/warning/info issues."""
    blocking: list[DesignIssue] = []
    warnings: list[DesignIssue] = []
    info: list[DesignIssue] = []

    _check_schema_and_phase(state, blocking, warnings)
    _check_brief(state, warnings, info)
    _check_blueprint(state, blocking, info)
    slot_view = _check_slots(state, blocking)
    _check_core_loop(state, blocking)
    _check_resolution_model(state, blocking, warnings)
    _check_character_model(state, warnings)

    can_compile = len(blocking) == 0
    ready_blockers = sorted({iss.code for iss in blocking})

    return ValidationReport(
        blocking=blocking,
        warnings=warnings,
        info=info,
        slots=slot_view,
        can_compile=can_compile,
        ready_blockers=ready_blockers,
    )


# ---------------------------------------------------------------------------
# Section checks
# ---------------------------------------------------------------------------


def _check_schema_and_phase(
    state: dict[str, Any],
    blocking: list[DesignIssue],
    warnings: list[DesignIssue],
) -> None:
    if state.get("schema_version") != 1:
        blocking.append(DesignIssue(
            code="schema_version_unsupported",
            severity="blocking",
            message="DesignState schema_version must be 1",
            path=["schema_version"],
        ))
    phase = state.get("phase")
    if phase not in PHASES:
        warnings.append(DesignIssue(
            code="phase_unknown",
            severity="warning",
            message=f"Phase `{phase}` is not in the known phase list",
            path=["phase"],
        ))


def _check_brief(
    state: dict[str, Any],
    warnings: list[DesignIssue],
    info: list[DesignIssue],
) -> None:
    brief = state.get("brief") or {}
    if not (brief.get("concept") or "").strip():
        warnings.append(DesignIssue(
            code="brief_concept_empty",
            severity="warning",
            message="No concept recorded yet -- capture the user's pitch.",
            path=["brief", "concept"],
            hint="Use set_brief_field with field='concept'.",
        ))
    if not brief.get("assumptions"):
        info.append(DesignIssue(
            code="brief_no_assumptions",
            severity="info",
            message="No assumptions recorded.",
            path=["brief", "assumptions"],
            hint="Surface implicit choices via add_assumption.",
        ))


def _check_blueprint(
    state: dict[str, Any],
    blocking: list[DesignIssue],
    info: list[DesignIssue],
) -> None:
    blueprint = state.get("blueprint") or {}
    if not (blueprint.get("id") or "").strip():
        blocking.append(DesignIssue(
            code="blueprint_required",
            severity="blocking",
            message="No blueprint selected -- required for compile.",
            path=["blueprint", "id"],
            hint="Pick or recommend a blueprint, then call set_blueprint.",
        ))
        return
    slots_required = blueprint.get("slots_required") or []
    if not isinstance(slots_required, list) or not slots_required:
        info.append(DesignIssue(
            code="blueprint_no_required_slots",
            severity="info",
            message="Blueprint declared no required slots.",
            path=["blueprint", "slots_required"],
        ))


def _check_slots(
    state: dict[str, Any],
    blocking: list[DesignIssue],
) -> SlotCompletion:
    blueprint = state.get("blueprint") or {}
    required = list(blueprint.get("slots_required") or [])
    slots = state.get("slots") or {}
    if not isinstance(slots, dict):
        slots = {}
    filled: list[str] = []
    missing: list[str] = []
    drafting: list[str] = []
    for slot in required:
        status = slots.get(slot, "missing")
        if status == "filled":
            filled.append(slot)
        elif status == "drafting":
            drafting.append(slot)
        else:
            missing.append(slot)
    for slot in missing:
        blocking.append(DesignIssue(
            code="slot_missing",
            severity="blocking",
            message=f"Required slot `{slot}` is not filled.",
            path=["slots", slot],
        ))
    progress = (len(filled) / len(required)) if required else 0.0
    return SlotCompletion(
        required=required,
        filled=filled,
        missing=missing,
        drafting=drafting,
        progress=round(progress, 4),
    )


def _check_core_loop(
    state: dict[str, Any],
    blocking: list[DesignIssue],
) -> None:
    core_loop = state.get("core_loop") or {}
    if not (core_loop.get("summary") or "").strip():
        blocking.append(DesignIssue(
            code="core_loop_summary_missing",
            severity="blocking",
            message="Core loop summary is required for compile.",
            path=["core_loop", "summary"],
            hint="Use set_core_loop with summary='...'.",
        ))


def _check_resolution_model(
    state: dict[str, Any],
    blocking: list[DesignIssue],
    warnings: list[DesignIssue],
) -> None:
    resolution = state.get("resolution_model") or {}
    if not (resolution.get("mechanic") or "").strip():
        blocking.append(DesignIssue(
            code="resolution_mechanic_missing",
            severity="blocking",
            message="Resolution mechanic is required for compile.",
            path=["resolution_model", "mechanic"],
            hint="e.g. d100 roll-under, d20 vs DC, 2d6 PBTA.",
        ))
    if not (resolution.get("dice") or "").strip():
        warnings.append(DesignIssue(
            code="resolution_dice_missing",
            severity="warning",
            message="No dice expression recorded for resolution.",
            path=["resolution_model", "dice"],
        ))


def _check_character_model(
    state: dict[str, Any],
    warnings: list[DesignIssue],
) -> None:
    character = state.get("character_model") or {}
    attributes = character.get("attributes") or []
    if not attributes:
        warnings.append(DesignIssue(
            code="character_attributes_missing",
            severity="warning",
            message="Character model has no attributes yet.",
            path=["character_model", "attributes"],
        ))


__all__ = ["SlotCompletion", "ValidationReport", "validate_design_state"]
