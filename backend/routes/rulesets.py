"""Ruleset CRUD + dice IR compile endpoints.

Each ruleset belongs to one owner. Visibility mirrors `parsed_modules`:
`is_shared=False` is owner-only, `is_shared=True` is visible to every
signed-in user. Only the owner can edit, delete, recompile, or flip the
flag — non-owners on a shared ruleset get read-only access.

We persist the raw v6 JSON intact so the frontend can re-derive its
4-section view, and attach the dice-IR compiler artifact / applied
check_spec on subsequent calls.

Implementation note: artifact helpers, background compile orchestration,
and dice-IR/character-UI compile/apply routes were extracted into sibling
modules (`rulesets_artifacts.py`, `rulesets_compile.py`, and
`rulesets_compile_routes.py`) so this file fits the 600-line policy. The
re-exports below keep the original `from routes.rulesets import _foo`
import paths working.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit_log import audit
from orm.models import GameSession, Ruleset, User
from routes.deps import current_user, db_session
from routes.rulesets_artifacts import (
    _build_compile_markdown,  # re-export for backwards-compat imports
    _can_see,
    _detail,
    _extract_embedded_dice_ir,  # re-export for backwards-compat imports
    _is_compiled_artifact,  # re-export for backwards-compat imports
    _mark_applied_check_spec,  # re-export for backwards-compat imports
    _pick_compiled_check_spec,  # re-export for backwards-compat imports
    _summary,
)
from routes.rulesets_compile import (
    _create_ruleset_from_artifact,  # re-export for backwards-compat imports
    _resolve_default_compiler_config,  # re-export for backwards-compat imports
    _run_character_ui_compile_background,  # re-export for backwards-compat imports
    _run_dice_ir_compile_background,  # re-export for backwards-compat imports
)
from routes.rulesets_compile_routes import rulesets_compile_router
from schemas.ruleset import (
    RulesetDetail,
    RulesetShareRequest,
    RulesetSummary,
    RulesetUploadRequest,
)
from services.ocr import OCRError
from services.ruleset_file_ingestion import (
    accepted_ruleset_file_extensions,
    parse_ruleset_file,
)
from services.ruleset_parse_workflow import RulesetParseWorkflowConfig
from services.short_name import get_or_generate_ruleset_short_name

logger = logging.getLogger("chatrpg.rulesets")

router = APIRouter(prefix="/api/rulesets", tags=["rulesets"])


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=RulesetDetail)
async def upload_ruleset(
    body: RulesetUploadRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> RulesetDetail:
    """Persist a v6 JSON artifact uploaded by the frontend.

    If the artifact carries a `dice_ir` field (top-level chatrpg/new-chatlab
    shape, or legacy chatlab `parse_artifacts.*` shapes), pull it out into
    the dedicated column. Otherwise schedule a background compile so the
    dice tab populates without the user having to click "compile".
    """
    return await _create_ruleset_from_artifact(
        body.artifact,
        background_tasks=background_tasks,
        db=db,
        user=user,
    )


@router.post("/file", response_model=RulesetDetail)
async def upload_ruleset_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    output_language: str | None = Form(default=None),
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> RulesetDetail:
    """Upload a PDF/Markdown ruleset and store it as a v6-compatible artifact."""
    if not file.filename:
        raise HTTPException(400, "filename required")
    ext = Path(file.filename).suffix.lower()
    allowed = accepted_ruleset_file_extensions()
    if ext not in set(allowed):
        raise HTTPException(
            400,
            f"Unsupported extension '{ext}'. Allowed: {', '.join(allowed)}",
        )

    suffix = ext or ".bin"
    tmp = tempfile.NamedTemporaryFile(prefix="ruleset-", suffix=suffix, delete=False)
    try:
        chunk = await file.read()
        tmp.write(chunk)
        tmp.flush()
        tmp.close()

        try:
            cfg = await _resolve_default_compiler_config(db)
            artifact = await parse_ruleset_file(
                Path(tmp.name),
                file.filename,
                output_language=output_language,
                workflow_config=RulesetParseWorkflowConfig(
                    model=cfg.get("model") or "",
                    base_url=cfg.get("base_url") or "",
                    api_key=cfg.get("api_key") or "",
                ),
            )
        except OCRError as exc:
            raise HTTPException(500, str(exc)) from exc

        return await _create_ruleset_from_artifact(
            artifact,
            background_tasks=background_tasks,
            db=db,
            user=user,
        )
    finally:
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except OSError:
            pass


@router.get("", response_model=list[RulesetSummary])
async def list_rulesets(
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> list[RulesetSummary]:
    """Visible rulesets = mine ∪ everyone-else's-shared, ordered by recency."""
    result = await db.execute(
        select(Ruleset)
        .where(
            (Ruleset.owner_id == user.id) | (Ruleset.is_shared == True)  # noqa: E712
        )
        .order_by(Ruleset.updated_at.desc())
    )
    return [_summary(rs) for rs in result.scalars().all()]


@router.get("/{ruleset_id}", response_model=RulesetDetail)
async def get_ruleset(
    ruleset_id: str,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> RulesetDetail:
    rs = await db.get(Ruleset, ruleset_id)
    # Mask private rulesets as 404 rather than 403 — leaks less about
    # whether a given id exists at all.
    if rs is None or not _can_see(rs, user.id):
        raise HTTPException(404, "Ruleset not found")
    return _detail(rs)


@router.get("/{ruleset_id}/short-name")
async def get_ruleset_short_name(
    ruleset_id: str,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> dict[str, str]:
    """Return the short tag used in room titles like `[coc]<module>`.

    First call generates it via the model pool's "fast" entry and caches
    the result on the ruleset row; subsequent calls are pure DB reads.
    The cache write benefits every viewer, so non-owners on a shared
    ruleset can also trigger generation.
    """
    rs = await db.get(Ruleset, ruleset_id)
    if rs is None or not _can_see(rs, user.id):
        raise HTTPException(404, "Ruleset not found")
    short = await get_or_generate_ruleset_short_name(db, rs)
    return {"short_name": short}


@router.delete("/{ruleset_id}")
async def delete_ruleset(
    ruleset_id: str,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    rs = await db.get(Ruleset, ruleset_id)
    if rs is None or not _can_see(rs, user.id):
        raise HTTPException(404, "Ruleset not found")
    if rs.owner_id != user.id:
        raise HTTPException(403, "only the owner can delete this ruleset")
    pre_title = rs.book_title
    # Detach any sessions still pointing at this ruleset so the FK doesn't
    # block the delete. Pre-alpha DBs may have the old FK without ON DELETE
    # SET NULL, so we null it explicitly.
    await db.execute(
        update(GameSession)
        .where(GameSession.ruleset_id == ruleset_id)
        .values(ruleset_id=None)
    )
    await db.delete(rs)
    await db.commit()
    audit(
        "ruleset.delete",
        actor=user.id,
        target=ruleset_id,
        extra={"book_title": pre_title},
    )
    return {"ok": True, "id": ruleset_id}


@router.post("/{ruleset_id}/share", response_model=RulesetSummary)
async def set_ruleset_shared(
    ruleset_id: str,
    body: RulesetShareRequest,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> RulesetSummary:
    """Toggle visibility. Only the owner can flip the flag."""
    rs = await db.get(Ruleset, ruleset_id)
    if rs is None or not _can_see(rs, user.id):
        raise HTTPException(404, "Ruleset not found")
    if rs.owner_id != user.id:
        raise HTTPException(403, "only the owner can change visibility")
    rs.is_shared = bool(body.is_shared)
    await db.commit()
    await db.refresh(rs)
    return _summary(rs)


# ---------------------------------------------------------------------------
# Dice IR + character-UI compile/apply routes
# ---------------------------------------------------------------------------


# Mounted here so `/api/rulesets/{ruleset_id}/dice-ir/...` and
# `/api/rulesets/{ruleset_id}/character-ui/...` keep the original prefix +
# tags. The sub-router carries no prefix of its own (see
# `rulesets_compile_routes.py`).
router.include_router(rulesets_compile_router)
