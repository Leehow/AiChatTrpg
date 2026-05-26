"""Setup-time character creation, in-game flow, and update/delete routes for
`/api/sessions/{session_id}/...`.

Extracted from `routes/sessions.py` so the main router file can focus on
session CRUD around the basics (list/create/get), per-target translation /
voice endpoints, mounted debug routes, and messages. This subrouter is
mounted via `router.include_router(session_flow_router)` from `sessions.py`
at the original cluster location, so route paths, response models, query
parameters, auth dependencies, SSE event shapes, and payload shapes are
unchanged.

Includes `PUT /{session_id}` and `DELETE /{session_id}` so the host module
fits under the 600-line policy; their registration position is preserved
because the mount point sits right after the character-cluster comment,
before the debug router include.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from core.audit_log import audit
from orm.models import ParsedModule, Ruleset, User
from routes.deps import current_user, db_session
from routes.session_helpers import (
    _detail,
    _get_owned_session,
    _get_ruleset_for_session,
    _get_visible_module,
    _get_visible_ruleset,
    _setup_state,
    _stream_with_fresh_db,
)
from schemas.common import OkResponse
from schemas.session import (
    AdventureStartOptions,
    AdventureStartRequest,
    CharacterChatRequest,
    CharacterDraftResponse,
    CharacterGenerateRequest,
    CharacterImportRequest,
    CharacterStartRequest,
    ContextSnapshot,
    ContextSnapshotBP1,
    ContextSnapshotBP2,
    ContextSnapshotBP3,
    ForceInGameTimeRequest,
    ForceInGameTimeResponse,
    SessionDetail,
    SessionUpdateRequest,
)

logger = logging.getLogger("chatrpg.sessions")

session_flow_router = APIRouter()


# -- Setup-time character creation -----------------------------------------


@session_flow_router.get(
    "/{session_id}/character-draft",
    response_model=CharacterDraftResponse,
)
async def get_character_draft(
    session_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> CharacterDraftResponse:
    s = await _get_owned_session(db, session_id, user)
    from services.character_creator import (
        _load_chat_history, _migrate_chat_if_needed, character_snapshot,
    )

    await _migrate_chat_if_needed(db, s)
    chat = await _load_chat_history(db, s.id)
    return CharacterDraftResponse(**character_snapshot(s, chat=chat))


@session_flow_router.post(
    "/{session_id}/character-start",
    response_model=CharacterDraftResponse,
)
async def post_character_start(
    session_id: str,
    body: CharacterStartRequest | None = None,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> CharacterDraftResponse:
    s = await _get_owned_session(db, session_id, user)
    rs = await _get_ruleset_for_session(db, s, user)
    from services.character_creator import start_character_creation

    try:
        result = await start_character_creation(
            db, s, rs, target_language=(body.language if body else "") or "",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return CharacterDraftResponse(**result)


@session_flow_router.post("/{session_id}/character-start-stream")
async def post_character_start_stream(
    session_id: str,
    body: CharacterStartRequest | None = None,
    user: User = Depends(current_user),
) -> EventSourceResponse:
    from services.character_creator import stream_character_creation_start

    return EventSourceResponse(_stream_with_fresh_db(
        session_id, user,
        lambda db, s, rs: stream_character_creation_start(
            db, s, rs, target_language=(body.language if body else "") or "",
        ),
    ))


@session_flow_router.post(
    "/{session_id}/character-chat",
    response_model=CharacterDraftResponse,
)
async def post_character_chat(
    session_id: str,
    body: CharacterChatRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> CharacterDraftResponse:
    s = await _get_owned_session(db, session_id, user)
    rs = await _get_ruleset_for_session(db, s, user)
    from services.character_creator import chat_character_creation

    try:
        result = await chat_character_creation(
            db, s, rs, body.message, target_language=body.language or "",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return CharacterDraftResponse(**result)


@session_flow_router.post("/{session_id}/character-chat-stream")
async def post_character_chat_stream(
    session_id: str,
    body: CharacterChatRequest,
    user: User = Depends(current_user),
) -> EventSourceResponse:
    from services.character_creator import stream_character_creation_chat

    return EventSourceResponse(_stream_with_fresh_db(
        session_id, user,
        lambda db, s, rs: stream_character_creation_chat(
            db, s, rs, body.message, target_language=body.language or "",
        ),
    ))


# -- IC chat (in-game) -----------------------------------------------------
# Uses the unified `messages` table (phase=ic). Drives `run_trpg_turn` from
# the framework via `services.trpg_ic_runner.stream_ic_turn`.


@session_flow_router.post("/{session_id}/chat-stream")
async def post_chat_stream(
    session_id: str,
    body: CharacterChatRequest,
    user: User = Depends(current_user),
) -> EventSourceResponse:
    from services.trpg_ic_runner import stream_ic_turn

    return EventSourceResponse(_stream_with_fresh_db(
        session_id, user,
        lambda db, s, rs: stream_ic_turn(
            db, s, rs, body.message,
            intent=body.intent,
            pending_check_id=body.pending_check_id,
            roll_result=body.roll_result,
        ),
    ))


# Operator-driven in-game clock override. The GM normally advances time via
# `[TAKE_TIME]` markers; this endpoint backs the gear icon in the TRPG scene
# HUD so a player can fix drift or jump to a story moment.
@session_flow_router.post(
    "/{session_id}/in-game-time",
    response_model=ForceInGameTimeResponse,
)
async def post_in_game_time(
    session_id: str,
    body: ForceInGameTimeRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> ForceInGameTimeResponse:
    from sqlalchemy.orm.attributes import flag_modified

    if body.day < 1:
        raise HTTPException(400, "day must be >= 1")
    clock = body.clock.strip()
    import re as _re
    if not _re.match(r"^\d{1,2}:\d{2}$", clock):
        raise HTTPException(400, "clock must be HH:MM (24-hour)")
    hour, minute = (int(p) for p in clock.split(":", 1))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise HTTPException(400, "clock out of range")

    s = await _get_owned_session(db, session_id, user)

    period = _period_from_hour(hour)
    ms = dict(s.module_state) if isinstance(s.module_state, dict) else {}
    ms["day_count"] = body.day
    ms["in_game_time"] = f"{hour:02d}:{minute:02d}"
    ms["in_game_period"] = period
    if body.date and body.date.strip():
        ms["in_game_date"] = body.date.strip()
    s.module_state = ms
    flag_modified(s, "module_state")
    s.last_active_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(s)

    return ForceInGameTimeResponse(
        day=body.day,
        clock=ms["in_game_time"],
        period=period,
        date=ms.get("in_game_date"),
        elapsed_minutes=int(ms.get("elapsed_minutes") or 0),
    )


def _period_from_hour(hour: int) -> str:
    """Map a 24-hour clock value to a coarse period bucket. Frontend renders
    a localized label (上午/下午/傍晚/深夜)."""
    if 6 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 22:
        return "evening"
    return "night"


@session_flow_router.get(
    "/{session_id}/adventure-start-options",
    response_model=AdventureStartOptions,
)
async def get_adventure_start_options(
    session_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> AdventureStartOptions:
    from services.trpg_adventure_start import build_adventure_start_options

    s = await _get_owned_session(db, session_id, user)
    setup = _setup_state(s)
    module_id = str(setup.get("module_id") or "")
    if not module_id or module_id == "__freeform__":
        return AdventureStartOptions(**build_adventure_start_options(None))
    module = await _get_visible_module(db, module_id, user)
    return AdventureStartOptions(**build_adventure_start_options(module))


@session_flow_router.post(
    "/{session_id}/adventure-start",
    response_model=SessionDetail,
)
async def post_adventure_start(
    session_id: str,
    body: AdventureStartRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> SessionDetail:
    from services.trpg_adventure_start import activate_adventure_start
    from services.trpg_npc import enhance_player_known_names
    from services.trpg_npc.assets import (
        ensure_npc_assets,
        spawn_npc_portrait_task,
    )

    s = await _get_owned_session(db, session_id, user)
    rs = await _get_ruleset_for_session(db, s, user)
    setup = _setup_state(s)
    module_id = str(body.module_id or setup.get("module_id") or "")
    module: ParsedModule | None = None
    if module_id and module_id != "__freeform__":
        module = await _get_visible_module(db, module_id, user)
    activate_adventure_start(
        s,
        module,
        unit_index=body.unit_index,
        unit_id=body.unit_id,
    )
    # Adventure-start NPCs were just labelled by the sync regex path —
    # ask the fast model to upgrade entries that landed on a generic
    # "陌生人 / unknown person" fallback (typical for creatures or
    # groups the regex can't categorise).
    seeded_npcs = (s.memory_state or {}).get("npcs") if isinstance(s.memory_state, dict) else None
    if isinstance(seeded_npcs, list) and seeded_npcs:
        if await enhance_player_known_names(db, seeded_npcs):
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(s, "memory_state")
    asset_summary = await ensure_npc_assets(db, s)
    s.last_active_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(s)
    if asset_summary.portraits_queued:
        spawn_npc_portrait_task(s.id, s.user_id, asset_summary.portraits_queued)
    return _detail(
        s,
        rs.book_title if rs else "",
        rs.short_name if rs else None,
    )


@session_flow_router.post(
    "/{session_id}/character-import",
    response_model=CharacterDraftResponse,
)
async def post_character_import(
    session_id: str,
    body: CharacterImportRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> CharacterDraftResponse:
    s = await _get_owned_session(db, session_id, user)
    await _get_ruleset_for_session(db, s, user)
    from services.character_creator import import_character_draft

    try:
        result = await import_character_draft(
            db,
            s,
            body.character,
            pool_id=body.pool_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return CharacterDraftResponse(**result)


@session_flow_router.post(
    "/{session_id}/character-generate",
    response_model=CharacterDraftResponse,
)
async def post_character_generate(
    session_id: str,
    body: CharacterGenerateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> CharacterDraftResponse:
    s = await _get_owned_session(db, session_id, user)
    rs = await _get_ruleset_for_session(db, s, user)
    from services.character_creator import generate_character_card

    try:
        result = await generate_character_card(
            db,
            s,
            rs,
            mode=body.mode,
            seed=body.seed or "",
            target_language=body.language or "",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return CharacterDraftResponse(**result)


@session_flow_router.post("/{session_id}/character-generate-stream")
async def post_character_generate_stream(
    session_id: str,
    body: CharacterGenerateRequest,
    user: User = Depends(current_user),
) -> EventSourceResponse:
    from services.character_creator import stream_generate_character_card

    return EventSourceResponse(_stream_with_fresh_db(
        session_id, user,
        lambda db, s, rs: stream_generate_character_card(
            db, s, rs, mode=body.mode, seed=body.seed or "",
            target_language=body.language or "",
        ),
    ))


@session_flow_router.post(
    "/{session_id}/character-confirm",
    response_model=CharacterDraftResponse,
)
async def post_character_confirm(
    session_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> CharacterDraftResponse:
    s = await _get_owned_session(db, session_id, user)
    rs = await _get_ruleset_for_session(db, s, user)
    from services.character_creator import confirm_character_card
    from services.trpg_equipment_enricher import enrich_pc_equipment

    try:
        result = await confirm_character_card(db, s, rs)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    # Best-effort: stamp canonical impaling/range/etc onto PC equipment so
    # the GM's first [CONTEST] doesn't have to round-trip through
    # [SEARCH_RULES] for damage formulas. Failures don't block character
    # confirmation — the GM can still look up rules on demand.
    try:
        await enrich_pc_equipment(db, s, rs)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[character-confirm] equipment enrich failed: %s", exc, exc_info=True)
    return CharacterDraftResponse(**result)


# Manual trigger so a running session whose PC was created BEFORE this hook
# existed can backfill canonical equipment fields without rebuilding the
# character card. Idempotent — safe to call multiple times.
@session_flow_router.post("/{session_id}/character/enrich-equipment")
async def post_enrich_equipment(
    session_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> dict[str, Any]:
    s = await _get_owned_session(db, session_id, user)
    rs = await _get_ruleset_for_session(db, s, user)
    from services.trpg_equipment_enricher import enrich_pc_equipment

    result = await enrich_pc_equipment(db, s, rs, force=False)
    return {
        "enriched_count": result.enriched_count,
        "skipped_count": result.skipped_count,
        "no_match_count": result.no_match_count,
        "by_bucket": result.by_bucket,
        "errors": result.errors,
        "skipped_reason": result.skipped_reason,
    }


@session_flow_router.delete(
    "/{session_id}/character-draft",
    response_model=CharacterDraftResponse,
)
async def delete_character_draft(
    session_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> CharacterDraftResponse:
    s = await _get_owned_session(db, session_id, user)
    from services.character_creator import clear_character_draft

    return CharacterDraftResponse(**(await clear_character_draft(db, s)))


@session_flow_router.get(
    "/{session_id}/context-snapshot",
    response_model=ContextSnapshot,
)
async def get_context_snapshot(
    session_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> ContextSnapshot:
    """Mirror exactly what the character-creation pipeline injects into the
    LLM prompt. Used by the debug panel's Context tab."""
    from services.character_creator import (
        _build_context_packet,
        _load_chat_history,
        _migrate_chat_if_needed,
        CARD_KEY,
        READY_KEY,
    )

    s = await _get_owned_session(db, session_id, user)
    rs = await _get_ruleset_for_session(db, s, user)
    # Migrate any legacy setup_state.character_chat into the messages table so
    # the snapshot reflects the canonical storage shape.
    await _migrate_chat_if_needed(db, s)
    packet = await _build_context_packet(db, s, rs)
    raw = rs.parsed_v6 if isinstance(rs.parsed_v6, dict) else {}
    sheet = raw.get("character_sheet") if isinstance(raw.get("character_sheet"), dict) else {}
    template_text = sheet.get("template_content") or ""
    if not template_text and isinstance(sheet.get("template_json"), (dict, list)):
        template_text = json.dumps(sheet["template_json"], ensure_ascii=False, indent=2)

    bp1 = ContextSnapshotBP1(
        ruleset_title=str(rs.book_title or ""),
        ruleset_world_mode=str(rs.world_mode or ""),
        core_rules=str(raw.get("core_rules") or ""),
        sheet_template=str(template_text),
        sheet_guide=str(sheet.get("guide_content") or ""),
        scene_guide=packet.scene_guide or "",
        module_title=packet.module_title or None,
        module_text=packet.module_text if hasattr(packet, "module_text") else "",
    )
    mem = s.memory_state if isinstance(s.memory_state, dict) else {}
    bp2 = ContextSnapshotBP2(
        module_state=s.module_state if isinstance(s.module_state, dict) else {},
        scenes=list(mem.get("scenes") or []),
        npcs=list(mem.get("npcs") or []),
        plot_threads=list(mem.get("plot_threads") or []),
        world_facts=list(mem.get("world_facts") or []),
        narrative_summary=str(s.narrative_summary or ""),
    )
    setup = s.setup_state if isinstance(s.setup_state, dict) else {}
    chat_history = await _load_chat_history(db, s.id)
    bp3 = ContextSnapshotBP3(
        chat=chat_history,
        pc=s.character if isinstance(s.character, dict) and s.character else None,
        draft_card=setup.get(CARD_KEY) if isinstance(setup.get(CARD_KEY), dict) else None,
        ready=bool(setup.get(READY_KEY) or False),
        dice_history=list(s.dice_history or []),
    )
    return ContextSnapshot(bp1=bp1, bp2=bp2, bp3=bp3)


# -- Session update / delete -----------------------------------------------
# Co-located with the setup/flow cluster so `sessions.py` fits under the
# 600-line policy. Registration order is preserved: the parent router mounts
# this subrouter at the original cluster position, before the debug router.


@session_flow_router.put("/{session_id}", response_model=SessionDetail)
async def update_session(
    session_id: str,
    body: SessionUpdateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> SessionDetail:
    s = await _get_owned_session(db, session_id, user)
    data = body.model_dump(exclude_unset=True)
    # Validate ownership when caller switches the ruleset on a draft.
    if "ruleset_id" in data and data["ruleset_id"]:
        await _get_visible_ruleset(db, data["ruleset_id"], user)
    if "setup_state" in data and isinstance(data["setup_state"], dict):
        # Merge over the existing dict so partial updates from the wizard
        # don't blow away unrelated fields.
        merged = dict(s.setup_state or {})
        merged.update(data["setup_state"])
        data["setup_state"] = merged
    for field, value in data.items():
        setattr(s, field, value)
    s.last_active_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(s)
    rs = await db.get(Ruleset, s.ruleset_id) if s.ruleset_id else None
    return _detail(
        s,
        rs.book_title if rs else "",
        rs.short_name if rs else None,
    )


@session_flow_router.delete("/{session_id}", response_model=OkResponse)
async def delete_session(
    session_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> OkResponse:
    s = await _get_owned_session(db, session_id, user)
    pre_title = s.title
    pre_ruleset = s.ruleset_id
    await db.delete(s)
    await db.commit()
    audit(
        "session.delete",
        actor=user.id,
        target=session_id,
        extra={"title": pre_title, "ruleset_id": pre_ruleset},
    )
    return OkResponse()
