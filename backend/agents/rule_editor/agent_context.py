"""Agent-side helpers for the design-state-first turn loop.

Kept in its own module so `agent.py` stays under the 400-line cap. The
helpers are deliberately thin: they consume the `RulesetDraft` ORM
object and the structured tool payloads the design-state tools emit,
and produce (a) the per-turn prompt context block and (b) SSE event
dicts mirrored from those payloads. No FastAPI imports here.
"""

from __future__ import annotations

import copy
from typing import Any

from agents.rule_editor.design_state import (
    build_summary,
    empty_design_state,
    validate_design_state,
)
from agents.rule_editor.prompts import render_design_context
from agents.rule_editor.tools import allowed_tool_names_for_draft
from agents.rule_editor.tools.dice_bridge import (
    DICE_COMPILE_PROGRESS_MARKER,
    DICE_STATE_CHANGED_MARKER,
)
from orm.models import RulesetDraft


# Payload keys that mark the agent loop should emit SSE events. The
# design-state tool wrappers stamp these so the agent does not have to
# hard-code which tool names are "writers".
DESIGN_STATE_CHANGED_MARKER = "_design_state_changed"
VALIDATION_REPORT_KEY = "validation_report"


def build_design_context_block(draft: RulesetDraft) -> str:
    """Render the per-turn design-state context block for the system prompt.

    Reads design_state and validation_report from the draft. If either
    is missing or stale, the validator runs in-process so the prompt
    block still reflects reality. This function never mutates the
    draft -- persistence is the responsibility of the design-state
    write tools, not the prompt builder.
    """
    raw_state = draft.design_state or {}
    if not isinstance(raw_state, dict) or not raw_state:
        state = empty_design_state()
    else:
        state = copy.deepcopy(raw_state)

    raw_report = draft.validation_report or {}
    if not isinstance(raw_report, dict) or not raw_report:
        report_dict = validate_design_state(state).model_dump()
    else:
        report_dict = raw_report

    summary = build_summary(state)
    return render_design_context(
        design_phase=str(draft.design_phase or state.get("phase") or "intake"),
        design_summary=summary,
        validation_report=report_dict,
        allowed_tool_names=allowed_tool_names_for_draft(draft),
    )


def strip_internal_markers(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop `_<marker>` keys before sending the payload back to the LLM.

    Internal markers (`_design_state_changed`,
    `_request_dice_compile_changed`, `_request_dice_compile_progress`)
    are part of the agent <-> agent-loop protocol; the LLM should see
    only the public structured fields.
    """
    if not isinstance(payload, dict):
        return payload
    return {k: v for k, v in payload.items() if not k.startswith("_")}


def events_from_tool_payload(
    *,
    payload: dict[str, Any],
    edit_id: str | None,
) -> list[dict[str, Any]]:
    """Translate a structured tool payload into SSE-ready event dicts.

    Up to four events may be emitted, in order:

    1. `design_state_changed` -- whenever the payload carries the
       `_design_state_changed` marker. Includes design_phase,
       design_summary, edit_id, diff, blueprint_id (if any), and
       sections_seeded (if any).
    2. `dice_compile_progress` -- whenever the payload carries the
       `_request_dice_compile_progress` marker. Carries the source
       (`direct` / `codeact` / `fallback_*`), primitive_calls, iters,
       and fallback_reason from the bridge so the frontend can show
       what compile path ran.
    3. `dice_state_changed` -- whenever the payload carries the
       `_request_dice_compile_changed` marker. Mirrors the event the
       dice agent emits after `design_dice_procedure` succeeds so the
       frontend reloads the dice preview the same way.
    4. `validation_report` -- whenever the payload carries a
       structured `validation_report` (every design-state write tool,
       and `compile_design`). Includes the report and can_compile.

    Returning a list (rather than yielding) keeps the agent loop's
    streaming code easy to read; iteration is cheap given at most a
    few events per call.
    """
    if not isinstance(payload, dict):
        return []
    events: list[dict[str, Any]] = []

    if payload.get(DESIGN_STATE_CHANGED_MARKER):
        ev: dict[str, Any] = {
            "type": "design_state_changed",
            "design_phase": payload.get("design_phase") or "",
            "design_summary": payload.get("design_summary") or {},
            "edit_id": edit_id or payload.get("edit_id"),
            "diff": list(payload.get("diff") or []),
        }
        if "blueprint_id" in payload:
            ev["blueprint_id"] = payload.get("blueprint_id")
        if "sections_seeded" in payload:
            ev["sections_seeded"] = list(payload.get("sections_seeded") or [])
        events.append(ev)

    progress = payload.get(DICE_COMPILE_PROGRESS_MARKER)
    if isinstance(progress, dict):
        events.append({
            "type": "dice_compile_progress",
            "source": str(progress.get("source") or ""),
            "primitive_calls": int(progress.get("primitive_calls") or 0),
            "iters": int(progress.get("iters") or 0),
            "fallback_reason": progress.get("fallback_reason"),
        })

    if payload.get(DICE_STATE_CHANGED_MARKER):
        events.append({"type": "dice_state_changed"})

    report = payload.get(VALIDATION_REPORT_KEY)
    if isinstance(report, dict) and report:
        events.append({
            "type": "validation_report",
            "validation_report": report,
            "can_compile": bool(
                payload.get("can_compile", report.get("can_compile", False))
            ),
        })
    return events


__all__ = [
    "DESIGN_STATE_CHANGED_MARKER",
    "VALIDATION_REPORT_KEY",
    "build_design_context_block",
    "events_from_tool_payload",
    "strip_internal_markers",
]
