"""Dice IR + character-UI compile/apply routes for `/api/rulesets/...`.

Extracted from `routes/rulesets.py` so the main router file can focus on
ruleset CRUD. This sub-router carries no prefix of its own and is mounted
via `router.include_router(rulesets_compile_router)` from `rulesets.py`,
so route paths, response models, tags, auth dependencies, error
semantics, and side-effects (audit logging, persisted columns) are
unchanged.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agents.trpg.character_ui import (
    CharacterUICompilerError,
    compile_character_ui,
)
from agents.trpg.check_ir.compile_direct import (
    DEFAULT_DICE_COMPILER_MODEL,
    DiceRuleCompilerError,
    compile_to_ir_direct,
)
from agents.trpg.check_spec_registry import public_check_spec
from agents.trpg.pipeline_helpers import resolve_compiler_api_config
from orm.models import Ruleset, User
from routes.deps import current_user, db_session
from routes.rulesets_artifacts import (
    _build_compile_markdown,
    _can_see,
    _detail,
    _mark_applied_check_spec,
    _pick_compiled_check_spec,
)
from routes.rulesets_compile import _resolve_default_compiler_config
from schemas.ruleset import (
    ApplyCheckSpecRequest,
    CompileCharacterUIRequest,
    CompileCharacterUIResponse,
    CompileDiceIRRequest,
    CompileDiceIRResponse,
    RulesetDetail,
)

logger = logging.getLogger("chatrpg.rulesets")

rulesets_compile_router = APIRouter()


@rulesets_compile_router.post(
    "/{ruleset_id}/dice-ir/compile",
    response_model=CompileDiceIRResponse,
)
async def compile_dice_ir(
    ruleset_id: str,
    body: CompileDiceIRRequest,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> CompileDiceIRResponse:
    """Run the dice-IR compiler on a ruleset's content.

    By default targets codex-relay's gpt-5.5. Caller can override model,
    base_url, and api_key. The resulting artifact is saved into the ruleset's
    `dice_ir` column unless `save=false` is requested (useful for previews).
    """
    rs = await db.get(Ruleset, ruleset_id)
    if rs is None or not _can_see(rs, user.id):
        raise HTTPException(404, "Ruleset not found")
    if rs.owner_id != user.id:
        raise HTTPException(403, "only the owner can recompile this ruleset")

    markdown = _build_compile_markdown(rs.parsed_v6 or {})
    if not markdown:
        raise HTTPException(400, "Ruleset has no compilable content")

    cfg = resolve_compiler_api_config(
        model=body.model or DEFAULT_DICE_COMPILER_MODEL,
        base_url=body.base_url or "",
        api_key=body.api_key or "",
    )
    output_language = (body.output_language or rs.parsed_v6.get("output_language") or "en").lower()
    if output_language not in {"en", "zh"}:
        # Non-en/zh requests fall back to en — the prompt only branches on those.
        output_language = "en"

    try:
        package = await compile_to_ir_direct(
            markdown,
            system_name=rs.book_title,
            house_rules="",
            model=cfg["model"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            output_language=output_language,
        )
    except DiceRuleCompilerError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("[chatrpg] dice IR compile failed")
        raise HTTPException(500, f"Dice IR compilation failed: {exc}") from exc

    artifact: dict[str, Any] = {
        "schema_version": "ruleset_dice_ir_compiler_artifact_v1",
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "model": package.get("model") or cfg["model"],
        "output_language": output_language,
        "package": package,
    }

    saved = False
    if body.save:
        procedure_id, check_spec = _pick_compiled_check_spec(artifact)
        if check_spec is not None:
            artifact = _mark_applied_check_spec(
                artifact,
                procedure_id=procedure_id,
                check_spec=check_spec,
                source="auto_default",
            )
            rs.check_spec = check_spec
        rs.dice_ir = artifact
        await db.commit()
        await db.refresh(rs)
        saved = True

    return CompileDiceIRResponse(
        ok=True,
        ruleset_id=rs.id,
        artifact_saved=saved,
        package=artifact,
        output_language=output_language,
    )


@rulesets_compile_router.post(
    "/{ruleset_id}/character-ui/compile",
    response_model=CompileCharacterUIResponse,
)
async def compile_character_ui_endpoint(
    ruleset_id: str,
    body: CompileCharacterUIRequest,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> CompileCharacterUIResponse:
    """Run the character-UI compiler on a ruleset.

    Used both for first-time compilation on rulesets uploaded before this
    feature shipped, and for re-running after the user changes the default
    model. Defaults to the model_pool's default entry; caller may override.
    """
    rs = await db.get(Ruleset, ruleset_id)
    if rs is None or not _can_see(rs, user.id):
        raise HTTPException(404, "Ruleset not found")
    if rs.owner_id != user.id:
        raise HTTPException(
            403, "only the owner can recompile this ruleset",
        )
    if not isinstance(rs.parsed_v6, dict):
        raise HTTPException(400, "Ruleset has no parsed content")

    if body.model and body.base_url and body.api_key:
        cfg = {
            "model": body.model,
            "base_url": body.base_url.rstrip("/"),
            "api_key": body.api_key,
        }
    else:
        cfg = await _resolve_default_compiler_config(db)
        if body.model:
            cfg = dict(cfg)
            cfg["model"] = body.model
    if not cfg.get("api_key") or not cfg.get("base_url"):
        raise HTTPException(
            400,
            "No API config available for the default compiler model",
        )

    output_language = (
        body.output_language
        or str(rs.parsed_v6.get("output_language") or "en")
    )

    try:
        artifact = await compile_character_ui(
            rs.parsed_v6,
            book_title=rs.book_title or "",
            model=cfg["model"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            output_language=output_language,
        )
    except CharacterUICompilerError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("[chatrpg] character_ui compile failed")
        raise HTTPException(
            500, f"Character UI compilation failed: {exc}",
        ) from exc

    saved = False
    if body.save:
        rs.character_ui = artifact
        await db.commit()
        await db.refresh(rs)
        saved = True

    return CompileCharacterUIResponse(
        ok=True,
        ruleset_id=rs.id,
        artifact_saved=saved,
        package=artifact,
        output_language=artifact.get("output_language"),
    )


@rulesets_compile_router.post(
    "/{ruleset_id}/dice-ir/apply",
    response_model=RulesetDetail,
)
async def apply_check_spec(
    ruleset_id: str,
    body: ApplyCheckSpecRequest,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> RulesetDetail:
    """Promote one of the compiled check_specs to runtime use.

    Caller may pass a check_spec dict directly, or a procedure_id to pick
    out from the compiled list.
    """
    rs = await db.get(Ruleset, ruleset_id)
    if rs is None or not _can_see(rs, user.id):
        raise HTTPException(404, "Ruleset not found")
    if rs.owner_id != user.id:
        raise HTTPException(
            403, "only the owner can change the applied check_spec",
        )

    if body.check_spec is not None:
        chosen = public_check_spec(body.check_spec)
        rs.check_spec = chosen
        if isinstance(rs.dice_ir, dict):
            rs.dice_ir = _mark_applied_check_spec(
                rs.dice_ir,
                procedure_id=str(body.procedure_id or ""),
                check_spec=chosen,
                source="manual_direct",
            )
        await db.commit()
        await db.refresh(rs)
        return _detail(rs)

    artifact = rs.dice_ir or {}
    procedure_id, chosen = _pick_compiled_check_spec(
        artifact,
        str(body.procedure_id or ""),
    )
    if chosen is None:
        raise HTTPException(400, "No compiled check_spec available to apply")
    rs.check_spec = chosen
    if isinstance(artifact, dict):
        rs.dice_ir = _mark_applied_check_spec(
            artifact,
            procedure_id=procedure_id,
            check_spec=chosen,
            source="manual",
        )
    await db.commit()
    await db.refresh(rs)
    return _detail(rs)
