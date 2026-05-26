"""Service helpers for the design-state -> parsed_v6 compile path.

Lives in its own module because `services/ruleset_drafts.py` is already
near the 400-line cap. Reuses the load + audit + cascade primitives the
existing draft service exposes via `services.ruleset_drafts`.

Behavior summary:

- Validator gates compile. If `validate_design_state` reports any
  blocking issues, `parsed_v6` is NOT mutated; the validation report is
  persisted on the draft and the design_state.compile block records a
  `failed` status with a machine-readable error code. The caller gets
  a structured `CompileBlockedResult`.
- On success, `parsed_v6` is replaced with the compiled artifact, the
  validation report is persisted, design_state.compile is updated, and
  a `RulesetDraftEdit` row is written with op `compile_design_state`.
  Stale flags (`needs_dice_compile`, `needs_character_ui_compile`) are
  set conservatively from the compiler's emit list.
- Existing in-place target-cascade semantics from `apply_ops_to_draft`
  are mirrored here so a target-bound draft still propagates compiled
  meta + parsed_v6 to its source ruleset.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from agents.rule_editor.compile_design import (
    CompileBlocked,
    CompileResult,
    compile_design_state,
)
from agents.rule_editor.design_state import (
    ValidationReport,
    empty_design_state,
)
from orm.models import Ruleset, RulesetDraft, RulesetDraftEdit
from services.ruleset_drafts import _load_draft, _new_id, _now


@dataclass
class CompileSuccessResult:
    """Returned when the compile produced a new parsed_v6."""

    edit_id: str
    parsed_v6: dict[str, Any]
    validation_report: dict[str, Any]
    sections_emitted: list[str]
    needs_dice_compile: bool
    needs_character_ui_compile: bool
    design_phase: str


@dataclass
class CompileBlockedResult:
    """Returned when the validator blocked the compile.

    `parsed_v6` reflects the draft's existing artifact (unchanged).
    `validation_report` carries the report that caused the block so the
    caller can surface it to the UI / agent.
    """

    parsed_v6: dict[str, Any]
    validation_report: dict[str, Any]
    ready_blockers: list[str]
    error: str
    design_phase: str


async def compile_design_for_draft(
    db: AsyncSession,
    *,
    draft_id: str,
    owner_id: str,
    message_id: str | None = None,
) -> CompileSuccessResult | CompileBlockedResult:
    """Run the design-state compiler for a draft and persist results.

    Empty / missing `design_state` is normalized to the canonical
    `empty_design_state()` before validation so a fresh blank draft
    always reaches the validator-gated path and returns structured
    blockers instead of raising. `parsed_v6` is preserved in that case.

    On blocking validation: writes the validation report + a `failed`
    compile status into design_state, returns `CompileBlockedResult`.
    Does not mutate `parsed_v6`.

    On success: replaces parsed_v6, writes a `compile_design_state` edit
    audit row, mirrors the target ruleset (in-place mode), bumps stale
    flags, returns `CompileSuccessResult`.
    """
    draft = await _load_draft(db, draft_id, owner_id)
    raw_design_state = draft.design_state
    if isinstance(raw_design_state, dict) and raw_design_state:
        design_state = copy.deepcopy(raw_design_state)
    else:
        design_state = empty_design_state()

    try:
        compile_result = compile_design_state(
            design_state, base_v6=draft.parsed_v6 or None,
        )
    except CompileBlocked as exc:
        return await _persist_blocked(
            db, draft=draft, design_state=design_state, report=exc.report,
        )

    return await _persist_success(
        db,
        draft=draft,
        design_state=design_state,
        result=compile_result,
        owner_id=owner_id,
        message_id=message_id,
    )


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


async def _persist_blocked(
    db: AsyncSession,
    *,
    draft: RulesetDraft,
    design_state: dict[str, Any],
    report: ValidationReport,
) -> CompileBlockedResult:
    report_dict = report.model_dump()
    error_code = "blocked: " + ", ".join(report.ready_blockers) if report.ready_blockers else "blocked"
    compile_block = dict(design_state.get("compile") or {})
    compile_block["status"] = "failed"
    compile_block["error"] = error_code
    compile_block["parsed_v6_ref"] = compile_block.get("parsed_v6_ref", "")
    design_state["compile"] = compile_block

    draft.design_state = design_state
    flag_modified(draft, "design_state")
    draft.validation_report = report_dict
    flag_modified(draft, "validation_report")
    await db.commit()
    await db.refresh(draft)

    return CompileBlockedResult(
        parsed_v6=draft.parsed_v6 or {},
        validation_report=report_dict,
        ready_blockers=list(report.ready_blockers),
        error=error_code,
        design_phase=draft.design_phase or "intake",
    )


async def _persist_success(
    db: AsyncSession,
    *,
    draft: RulesetDraft,
    design_state: dict[str, Any],
    result: CompileResult,
    owner_id: str,
    message_id: str | None,
) -> CompileSuccessResult:
    parsed_v6_before = copy.deepcopy(draft.parsed_v6 or {})
    parsed_v6_after = result.parsed_v6
    report_dict = result.report.model_dump()

    # Update authoring artifact: stamp compile success + parsed ref.
    compile_block = dict(design_state.get("compile") or {})
    compile_block["status"] = "success"
    compile_block["error"] = ""
    compile_block["parsed_v6_ref"] = draft.id
    design_state["compile"] = compile_block

    draft.design_state = design_state
    flag_modified(draft, "design_state")
    draft.validation_report = report_dict
    flag_modified(draft, "validation_report")

    draft.parsed_v6 = parsed_v6_after
    flag_modified(draft, "parsed_v6")
    if result.needs_dice_compile:
        draft.needs_dice_compile = True
    if result.needs_character_ui_compile:
        draft.needs_character_ui_compile = True

    new_title = str(parsed_v6_after.get("book_title") or "").strip()
    if new_title and new_title != draft.title:
        draft.title = new_title

    if draft.target_ruleset_id:
        target = await db.get(Ruleset, draft.target_ruleset_id)
        if target is not None and target.owner_id == owner_id:
            target.parsed_v6 = copy.deepcopy(parsed_v6_after)
            flag_modified(target, "parsed_v6")
            target.book_title = str(parsed_v6_after.get("book_title") or "")
            target.world_mode = str(parsed_v6_after.get("world_mode") or "")
            target.book_id = str(parsed_v6_after.get("book_id") or "")
            target.updated_at = _now()

    edit = RulesetDraftEdit(
        id=_new_id("edit"),
        draft_id=draft.id,
        message_id=message_id,
        ops=[{
            "op": "compile_design_state",
            "sections": list(result.sections_emitted),
        }],
        diff=[{
            "path": ["parsed_v6"],
            "before": parsed_v6_before,
            "after": parsed_v6_after,
        }],
        undone=False,
    )
    db.add(edit)
    await db.commit()
    await db.refresh(edit)
    await db.refresh(draft)

    return CompileSuccessResult(
        edit_id=edit.id,
        parsed_v6=parsed_v6_after,
        validation_report=report_dict,
        sections_emitted=list(result.sections_emitted),
        needs_dice_compile=bool(draft.needs_dice_compile),
        needs_character_ui_compile=bool(draft.needs_character_ui_compile),
        design_phase=draft.design_phase or "intake",
    )


__all__ = [
    "CompileBlockedResult",
    "CompileSuccessResult",
    "compile_design_for_draft",
]
