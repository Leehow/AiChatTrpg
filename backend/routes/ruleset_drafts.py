"""HTTP routes for the conversational rule editor draft.

CRUD + apply / undo / promote / recompile + the agent message stream.

Auth: every endpoint scoped to `owner_id == current_user`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agents.rule_editor.patch_ops import PatchError
from core.audit_log import audit
from orm.models import RulesetDraft, RulesetDraftEdit, RulesetDraftMessage, User
from routes.deps import current_user, db_session
from schemas.ruleset_draft import (
    ApplyPatchRequest,
    ApplyPatchResponse,
    CreateDraftRequest,
    DraftDetail,
    DraftEdit,
    DraftMessage,
    DraftSummary,
    PromoteRequest,
    PromoteResponse,
    RecompileResponse,
    UndoEditResponse,
)
from services import ruleset_drafts as svc
from services.ruleset_drafts import patch_error_to_http


logger = logging.getLogger("chatrpg.ruleset_drafts")

router = APIRouter(prefix="/api/ruleset-drafts", tags=["ruleset-drafts"])


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _summary(d: RulesetDraft) -> DraftSummary:
    return DraftSummary(
        id=d.id,
        owner_id=d.owner_id,
        title=d.title,
        base_ruleset_id=d.base_ruleset_id,
        target_ruleset_id=d.target_ruleset_id,
        needs_dice_compile=bool(d.needs_dice_compile),
        needs_character_ui_compile=bool(d.needs_character_ui_compile),
        design_phase=d.design_phase or "intake",
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


def _msg(m: RulesetDraftMessage) -> DraftMessage:
    return DraftMessage(
        id=m.id,
        seq=m.seq,
        role=m.role,  # type: ignore[arg-type]
        content=m.content or {},
        created_at=m.created_at,
    )


def _edit(e: RulesetDraftEdit) -> DraftEdit:
    return DraftEdit(
        id=e.id,
        message_id=e.message_id,
        ops=list(e.ops or []),
        diff=list(e.diff or []),
        undone=bool(e.undone),
        created_at=e.created_at,
    )


async def _detail(
    db: AsyncSession, draft: RulesetDraft, owner_id: str,
) -> DraftDetail:
    msgs = await svc.list_messages(db, draft_id=draft.id, owner_id=owner_id)
    edits = await svc.list_edits(db, draft_id=draft.id, owner_id=owner_id)
    base = _summary(draft).model_dump()
    return DraftDetail(
        **base,
        parsed_v6=draft.parsed_v6 or {},
        design_state=draft.design_state or {},
        validation_report=draft.validation_report or {},
        messages=[_msg(m) for m in msgs],
        edits=[_edit(e) for e in edits],
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=DraftDetail)
async def create_draft(
    body: CreateDraftRequest,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> DraftDetail:
    draft = await svc.create_draft(
        db,
        owner_id=user.id,
        base_ruleset_id=body.base_ruleset_id,
        target_ruleset_id=body.target_ruleset_id,
        title=body.title,
    )
    return await _detail(db, draft, user.id)


@router.get("", response_model=list[DraftSummary])
async def list_drafts(
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> list[DraftSummary]:
    drafts = await svc.list_drafts(db, owner_id=user.id)
    return [_summary(d) for d in drafts]


@router.get("/{draft_id}", response_model=DraftDetail)
async def get_draft(
    draft_id: str,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> DraftDetail:
    draft = await svc.get_draft(db, draft_id=draft_id, owner_id=user.id)
    return await _detail(db, draft, user.id)


@router.get("/{draft_id}/messages", response_model=list[DraftMessage])
async def list_messages(
    draft_id: str,
    after_seq: int = 0,
    kind: str = "main",
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> list[DraftMessage]:
    """List one agent's transcript. `kind` is "main" (rule editor)
    or "dice" (dice procedure designer); each pane reads its own.
    """
    msgs = await svc.list_messages(
        db, draft_id=draft_id, owner_id=user.id,
        after_seq=after_seq, kind=kind,
    )
    return [_msg(m) for m in msgs]


@router.delete("/{draft_id}")
async def delete_draft(
    draft_id: str,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> dict[str, bool]:
    # Audit logging now lives in `svc.delete_draft` so EVERY caller
    # (route, smoke tests, internal cleanup) leaves a forensic record.
    # The route only needs to tag this call's source.
    await svc.delete_draft(
        db, draft_id=draft_id, owner_id=user.id, audit_source="route",
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Apply / undo / messages
# ---------------------------------------------------------------------------


@router.post("/{draft_id}/apply", response_model=ApplyPatchResponse)
async def apply_patch(
    draft_id: str,
    body: ApplyPatchRequest,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> ApplyPatchResponse:
    """Direct apply path. The agent uses POST /messages (P3); this endpoint
    is for manual / programmatic edits and for testing."""
    try:
        edit = await svc.apply_ops_to_draft(
            db, draft_id=draft_id, owner_id=user.id, raw_ops=body.ops,
        )
    except PatchError as e:
        raise patch_error_to_http(e)
    draft = await svc.get_draft(db, draft_id=draft_id, owner_id=user.id)
    return ApplyPatchResponse(
        edit_id=edit.id,
        diff=list(edit.diff or []),
        needs_dice_compile=bool(draft.needs_dice_compile),
        needs_character_ui_compile=bool(draft.needs_character_ui_compile),
        parsed_v6_after=draft.parsed_v6 or {},
    )


@router.post("/{draft_id}/edits/{edit_id}/undo", response_model=UndoEditResponse)
async def undo_edit(
    draft_id: str,
    edit_id: str,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> UndoEditResponse:
    inverse = await svc.undo_edit(
        db, draft_id=draft_id, owner_id=user.id, edit_id=edit_id,
    )
    draft = await svc.get_draft(db, draft_id=draft_id, owner_id=user.id)
    return UndoEditResponse(
        new_edit_id=inverse.id,
        parsed_v6_after=draft.parsed_v6 or {},
    )


# Agent message SSE endpoints live in routes/ruleset_draft_agents.py to
# keep this file under the 400-line cap. They share this router instance.
from routes.ruleset_draft_agents import add_agent_routes  # noqa: E402
add_agent_routes(router)

# Design-state compile endpoint lives in its own module for the same
# reason; attach to the shared router so client URLs stay consistent.
from routes.ruleset_draft_compile import add_compile_routes  # noqa: E402
add_compile_routes(router)


# ---------------------------------------------------------------------------
# Promote
# ---------------------------------------------------------------------------


@router.post("/{draft_id}/promote", response_model=PromoteResponse)
async def promote(
    draft_id: str,
    body: PromoteRequest,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> PromoteResponse:
    if body.mode == "new" and not body.new_title:
        # Allow empty title -- service falls back to draft.title -- but log it.
        pass
    ruleset_id = await svc.promote_draft(
        db,
        draft_id=draft_id,
        owner_id=user.id,
        mode=body.mode,
        new_title=body.new_title,
    )
    return PromoteResponse(ruleset_id=ruleset_id, mode=body.mode)


# ---------------------------------------------------------------------------
# Recompile
# ---------------------------------------------------------------------------
#
# Recompile delegates to helpers in routes.rulesets so we don't fork the
# compile pipeline. The cross-route imports are intentional for P1; if the
# coupling becomes painful we can extract to services/ruleset_compile.py
# during P5 polish.


@router.post("/{draft_id}/recompile/dice", response_model=RecompileResponse)
async def recompile_dice(
    draft_id: str,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> RecompileResponse:
    from routes.rulesets import (
        _build_compile_markdown,
        _mark_applied_check_spec,
        _pick_compiled_check_spec,
        _resolve_default_compiler_config,
    )
    from agents.trpg.check_ir.compile_direct import (
        DEFAULT_DICE_COMPILER_MODEL,
        DiceRuleCompilerError,
        compile_to_ir_direct,
    )
    from agents.trpg.pipeline_helpers import resolve_compiler_api_config
    from sqlalchemy.orm.attributes import flag_modified

    draft = await svc.get_draft(db, draft_id=draft_id, owner_id=user.id)
    parsed_v6 = dict(draft.parsed_v6 or {})
    markdown = _build_compile_markdown(parsed_v6)
    if not markdown:
        raise HTTPException(400, "Draft has no compilable content")

    cfg = resolve_compiler_api_config(
        model=DEFAULT_DICE_COMPILER_MODEL, base_url="", api_key="",
    )
    output_language = (parsed_v6.get("output_language") or "en").lower()
    if output_language not in {"en", "zh"}:
        output_language = "en"

    try:
        package = await compile_to_ir_direct(
            markdown,
            system_name=str(parsed_v6.get("book_title") or ""),
            house_rules="",
            model=cfg["model"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            output_language=output_language,
        )
    except DiceRuleCompilerError as exc:
        raise HTTPException(400, str(exc)) from exc

    artifact = {
        "schema_version": "ruleset_dice_ir_compiler_artifact_v1",
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "model": package.get("model") or cfg["model"],
        "output_language": output_language,
        "package": package,
    }
    procedure_id, check_spec = _pick_compiled_check_spec(artifact)
    if check_spec is not None:
        artifact = _mark_applied_check_spec(
            artifact,
            procedure_id=procedure_id,
            check_spec=check_spec,
            source="auto_default",
        )

    parsed_v6["dice_ir"] = artifact
    if check_spec is not None:
        parsed_v6["check_spec"] = check_spec

    draft.parsed_v6 = parsed_v6
    flag_modified(draft, "parsed_v6")
    draft.needs_dice_compile = False
    await db.commit()
    await db.refresh(draft)
    return RecompileResponse(ok=True, parsed_v6_after=draft.parsed_v6 or {})


@router.post(
    "/{draft_id}/recompile/character-ui",
    response_model=RecompileResponse,
)
async def recompile_character_ui(
    draft_id: str,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> RecompileResponse:
    from routes.rulesets import _resolve_default_compiler_config
    from agents.trpg.character_ui import (
        CharacterUICompilerError,
        compile_character_ui as _compile_character_ui,
    )
    from sqlalchemy.orm.attributes import flag_modified

    draft = await svc.get_draft(db, draft_id=draft_id, owner_id=user.id)
    parsed_v6 = dict(draft.parsed_v6 or {})
    sheet = parsed_v6.get("character_sheet")
    if not isinstance(sheet, dict) or not isinstance(sheet.get("template_json"), dict):
        raise HTTPException(
            400, "Draft has no character_sheet.template_json to compile",
        )
    cfg = await _resolve_default_compiler_config(db)
    if not cfg.get("api_key") or not cfg.get("base_url"):
        raise HTTPException(
            400, "No API config available for the default compiler model",
        )

    try:
        # `compile_character_ui` returns the wrapped artifact directly
        # (schema_version + saved_at + package). Match the route in
        # routes/rulesets.py -- pass `parsed_v6` + `book_title`, not the
        # extracted template fields.
        artifact = await _compile_character_ui(
            parsed_v6,
            book_title=str(parsed_v6.get("book_title") or draft.title or ""),
            model=cfg["model"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            output_language=str(parsed_v6.get("output_language") or "en"),
        )
    except CharacterUICompilerError as exc:
        raise HTTPException(400, str(exc)) from exc

    parsed_v6["character_ui"] = artifact
    draft.parsed_v6 = parsed_v6
    flag_modified(draft, "parsed_v6")
    draft.needs_character_ui_compile = False
    await db.commit()
    await db.refresh(draft)
    return RecompileResponse(ok=True, parsed_v6_after=draft.parsed_v6 or {})
