"""Per-session bond NPC enrichment endpoint.

Bond NPCs are PC-known characters seeded by ``character_intake``. When
intake leaves them with thin profiles (missing description / personality
/ relationship_dynamic / voice_card) the player can call this endpoint
to fill them out. Voice selection / TTS lock state stays under
``routes.session_audio``; this route only writes text fields.

The LLM compiler config is resolved lazily, only when there is actual
work to do. A session with zero eligible bond NPCs returns 200 with
zero counts even when no compiler model is configured -- this matches
the no-op-is-success contract documented in the lead brief.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from orm.models import Ruleset, User
from routes.deps import current_user, db_session
from routes.sessions import _detail, _get_owned_session
from schemas.session_bond import BondNpcEnrichRequest, BondNpcEnrichResponse
from services.trpg_npc.bond_enrichment import (
    enrich_bond_npcs,
    make_default_profile_generator,
    select_eligible_bond_npcs,
)

logger = logging.getLogger("chatrpg.session_bond_npcs")

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _build_session_detail(s, rs):
    return _detail(
        s,
        rs.book_title if rs else "",
        rs.short_name if rs else None,
    )


def _empty_response(s, rs) -> BondNpcEnrichResponse:
    return BondNpcEnrichResponse(
        session=_build_session_detail(s, rs),
        eligible=0,
        enriched=0,
        skipped=0,
        enriched_npc_keys=[],
        skipped_npc_keys=[],
        errors=[],
    )


@router.post(
    "/{session_id}/bond-npcs/enrich",
    response_model=BondNpcEnrichResponse,
)
async def post_bond_npcs_enrich(
    session_id: str,
    body: BondNpcEnrichRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> BondNpcEnrichResponse:
    s = await _get_owned_session(db, session_id, user)

    eligible = select_eligible_bond_npcs(s, force=body.force)
    if not eligible:
        # No work to do; do not resolve compiler config, do not 409.
        rs = await db.get(Ruleset, s.ruleset_id) if s.ruleset_id else None
        return _empty_response(s, rs)

    # Imported lazily so services/trpg_npc has no static dependency on
    # the routes layer; mirrors the pattern in services.character_intake.
    from routes.rulesets import _resolve_default_compiler_config
    cfg = await _resolve_default_compiler_config(db)
    if not cfg.get("api_key") or not cfg.get("base_url") or not cfg.get("model"):
        raise HTTPException(409, "No compiler model configured for enrichment")

    generator = make_default_profile_generator(
        model=cfg["model"],
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
    )

    result = await enrich_bond_npcs(
        s, db,
        profile_generator=generator,
        force=body.force,
        limit=body.limit,
    )

    if result.enriched:
        s.last_active_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(s)

    rs = await db.get(Ruleset, s.ruleset_id) if s.ruleset_id else None
    return BondNpcEnrichResponse(
        session=_build_session_detail(s, rs),
        eligible=result.eligible,
        enriched=result.enriched,
        skipped=result.skipped,
        enriched_npc_keys=result.enriched_keys,
        skipped_npc_keys=result.skipped_keys,
        errors=result.errors,
    )
