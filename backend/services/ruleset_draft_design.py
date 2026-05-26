"""Service helpers for design-state authoring on a draft.

Lives next to `services/ruleset_draft_compile.py` so the design-state
write path stays separate from the parsed_v6 apply path. The agent
loop's design-state tools call into this module; routes for the
P0.7 frontend will reuse the same primitives.

Behavior summary:

- `apply_design_ops_to_draft`: parse + validate ops with
  `parse_design_ops`, run through the pure reducer, persist
  `design_state` + recomputed `validation_report` + `design_phase`,
  and write a `RulesetDraftEdit` audit row with a namespaced
  `apply_design_ops` op. parsed_v6 is NOT touched.
- `apply_blueprint_to_draft`: resolve the blueprint via the read-only
  loader, build/apply ops on a deep copy, persist the same way, and
  audit as `apply_blueprint`.
- `validate_design_state_for_draft`: read-only refresh that
  re-validates the existing design_state and persists the report
  (idempotent helper used by the read-only validate tool).

All three return a `DesignWriteResult` so the agent layer can build
SSE events from a single shape.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from agents.rule_editor.blueprints import (
    BlueprintNotFoundError,
    apply_blueprint as _pure_apply_blueprint,
)
from agents.rule_editor.design_state import (
    DesignPatchError,
    apply_design_ops as _pure_apply_ops,
    build_summary,
    empty_design_state,
    parse_design_ops,
    validate_design_state,
)
from orm.models import RulesetDraft, RulesetDraftEdit
from services.ruleset_drafts import _load_draft, _new_id


@dataclass
class DesignWriteResult:
    """Result of any design-state write (ops, blueprint, validate-only)."""

    edit_id: str | None
    diff: list[dict[str, Any]]
    design_state: dict[str, Any]
    design_summary: dict[str, Any]
    validation_report: dict[str, Any]
    design_phase: str
    can_compile: bool
    blueprint_id: str | None = None
    sections_seeded: list[str] = field(default_factory=list)


def _ensure_design_state(draft: RulesetDraft) -> dict[str, Any]:
    """Return a deep copy of the draft's design_state, seeding empty if needed."""
    raw = draft.design_state or {}
    if not isinstance(raw, dict) or not raw:
        return empty_design_state()
    return copy.deepcopy(raw)


def _persist_design_state(
    draft: RulesetDraft,
    new_state: dict[str, Any],
) -> dict[str, Any]:
    """Write design_state + derived validation_report + design_phase.

    Returns the validation report as a plain dict so callers can both
    persist it and ship it back to the agent without re-running the
    validator.
    """
    report = validate_design_state(new_state)
    report_dict = report.model_dump()
    phase = str(new_state.get("phase") or "intake")

    draft.design_state = new_state
    flag_modified(draft, "design_state")
    draft.validation_report = report_dict
    flag_modified(draft, "validation_report")
    if phase:
        draft.design_phase = phase
    return report_dict


async def apply_design_ops_to_draft(
    db: AsyncSession,
    *,
    draft_id: str,
    owner_id: str,
    raw_ops: list[dict[str, Any]],
    message_id: str | None = None,
) -> DesignWriteResult:
    """Apply a batch of design-state ops + persist + audit.

    Raises `DesignPatchError` if any op is invalid; the caller is
    expected to translate to a structured tool error. parsed_v6 is
    never mutated by this path.
    """
    draft = await _load_draft(db, draft_id, owner_id)
    current_state = _ensure_design_state(draft)

    ops = parse_design_ops(raw_ops or [])
    if not ops:
        # No ops -- treat as a read-only validate refresh so the caller
        # still gets a useful payload back.
        report_dict = _persist_design_state(draft, current_state)
        await db.commit()
        await db.refresh(draft)
        return _build_result(
            draft=draft,
            edit_id=None,
            diff=[],
            design_state=current_state,
            report_dict=report_dict,
        )

    apply_result = _pure_apply_ops(current_state, ops)
    new_state = apply_result.design_state
    diff_dicts = [d.model_dump() for d in apply_result.diff]

    report_dict = _persist_design_state(draft, new_state)

    edit = RulesetDraftEdit(
        id=_new_id("edit"),
        draft_id=draft.id,
        message_id=message_id,
        ops=[{
            "op": "apply_design_ops",
            "design_ops": [op.model_dump() for op in ops],
        }],
        diff=diff_dicts,
        undone=False,
    )
    db.add(edit)
    await db.commit()
    await db.refresh(edit)
    await db.refresh(draft)

    return _build_result(
        draft=draft,
        edit_id=edit.id,
        diff=diff_dicts,
        design_state=new_state,
        report_dict=report_dict,
    )


async def apply_blueprint_to_draft(
    db: AsyncSession,
    *,
    draft_id: str,
    owner_id: str,
    blueprint_id: str,
    message_id: str | None = None,
) -> DesignWriteResult:
    """Apply a built-in blueprint to the draft's design_state.

    Raises `BlueprintNotFoundError` if the id is unknown. Does not
    overwrite already-filled sections (the pure loader is responsible
    for that policy). parsed_v6 is never mutated.
    """
    draft = await _load_draft(db, draft_id, owner_id)
    current_state = _ensure_design_state(draft)

    apply_result = _pure_apply_blueprint(current_state, blueprint_id)
    new_state = apply_result.design_state
    diff_dicts = [d.model_dump() for d in apply_result.diff]

    sections_seeded = sorted({
        str(d.path[0])
        for d in apply_result.diff
        if d.path and isinstance(d.path[0], str)
    })

    report_dict = _persist_design_state(draft, new_state)

    edit = RulesetDraftEdit(
        id=_new_id("edit"),
        draft_id=draft.id,
        message_id=message_id,
        ops=[{
            "op": "apply_blueprint",
            "blueprint_id": blueprint_id,
            "sections_seeded": sections_seeded,
        }],
        diff=diff_dicts,
        undone=False,
    )
    db.add(edit)
    await db.commit()
    await db.refresh(edit)
    await db.refresh(draft)

    result = _build_result(
        draft=draft,
        edit_id=edit.id,
        diff=diff_dicts,
        design_state=new_state,
        report_dict=report_dict,
    )
    result.blueprint_id = blueprint_id
    result.sections_seeded = sections_seeded
    return result


async def validate_design_state_for_draft(
    db: AsyncSession,
    *,
    draft_id: str,
    owner_id: str,
    persist: bool = True,
) -> DesignWriteResult:
    """Recompute + (optionally) persist validation_report.

    Returns the same shape the write paths return, with `edit_id=None`
    and `diff=[]` because nothing changed in design_state itself.
    """
    draft = await _load_draft(db, draft_id, owner_id)
    current_state = _ensure_design_state(draft)
    if persist:
        report_dict = _persist_design_state(draft, current_state)
        await db.commit()
        await db.refresh(draft)
    else:
        report_dict = validate_design_state(current_state).model_dump()

    return _build_result(
        draft=draft,
        edit_id=None,
        diff=[],
        design_state=current_state,
        report_dict=report_dict,
    )


def _build_result(
    *,
    draft: RulesetDraft,
    edit_id: str | None,
    diff: list[dict[str, Any]],
    design_state: dict[str, Any],
    report_dict: dict[str, Any],
) -> DesignWriteResult:
    summary = build_summary(design_state)
    return DesignWriteResult(
        edit_id=edit_id,
        diff=diff,
        design_state=design_state,
        design_summary=summary,
        validation_report=report_dict,
        design_phase=str(draft.design_phase or design_state.get("phase") or "intake"),
        can_compile=bool(report_dict.get("can_compile")),
    )


__all__ = [
    "DesignWriteResult",
    "BlueprintNotFoundError",
    "DesignPatchError",
    "apply_design_ops_to_draft",
    "apply_blueprint_to_draft",
    "validate_design_state_for_draft",
]
