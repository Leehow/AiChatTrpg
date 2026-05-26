"""Session CRUD + chat-message endpoints.

A 'session' is one TRPG run (called a 'room' in the UI). Messages are
nested under a session and FK-deleted on session removal.

All endpoints require auth — `current_user` enforces ownership: a user
can only see / mutate their own sessions and messages.
"""

from __future__ import annotations

import logging
import uuid
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from collections.abc import AsyncIterator

from core.database import get_session_factory
from orm.models import (
    GameSession,
    Message,
    Ruleset,
    User,
)
from routes.deps import current_user, db_session
from routes.session_debug_routes import session_debug_router
from routes.session_flow_routes import session_flow_router
from routes.session_helpers import (
    _detail,
    _get_owned_session,
    _get_ruleset_for_session,  # re-export for debug/trpg/test_runtime_sync.py
    _get_visible_ruleset,
    _summary,
)

logger = logging.getLogger("chatrpg.sessions")
from schemas.session import (
    MessageCreateRequest,
    MessageListResponse,
    MessageOut,
    PostprocessStep,
    PostprocessStepsResponse,
    SessionCreateRequest,
    SessionDetail,
    SessionSummary,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class MessageTtsStreamRequest(BaseModel):
    text: str | None = None


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> list[SessionSummary]:
    # Outer-join so draft sessions (no ruleset chosen yet) still show up.
    stmt = (
        select(GameSession, Ruleset.book_title, Ruleset.short_name)
        .outerjoin(Ruleset, Ruleset.id == GameSession.ruleset_id)
        .where(GameSession.user_id == user.id)
        .order_by(desc(GameSession.last_active_at))
    )
    rows = (await db.execute(stmt)).all()
    return [_summary(s, title or "", short) for s, title, short in rows]


@router.post("", response_model=SessionDetail)
async def create_session(
    body: SessionCreateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> SessionDetail:
    rs: Ruleset | None = None
    if body.ruleset_id:
        rs = await _get_visible_ruleset(db, body.ruleset_id, user)
    now = datetime.now(timezone.utc)
    if rs is not None:
        # Caller pre-selected a ruleset → setup is implicitly done.
        title = (body.title or rs.book_title or "Untitled session").strip()
        setup_state = {
            "step": 2,
            "ruleset_id": rs.id,
            "module_id": None,
            "module_title": None,
            "completed": True,
        }
    else:
        # Empty draft — title stays blank, room shows up in the "drafts"
        # section until the wizard finishes.
        title = (body.title or "").strip()
        setup_state = {
            "step": 0,
            "ruleset_id": None,
            "module_id": None,
            "module_title": None,
            "completed": False,
        }
    s = GameSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        ruleset_id=rs.id if rs else None,
        title=title,
        last_active_at=now,
        setup_state=setup_state,
    )
    if body.character is not None:
        s.character = body.character
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return _detail(
        s,
        rs.book_title if rs else "",
        rs.short_name if rs else None,
    )


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> SessionDetail:
    s = await _get_owned_session(db, session_id, user)
    rs = await db.get(Ruleset, s.ruleset_id) if s.ruleset_id else None
    return _detail(
        s,
        rs.book_title if rs else "",
        rs.short_name if rs else None,
    )


class _TranslateCharacterBody(BaseModel):
    language: str = "zh"


@router.post("/{session_id}/character/translate", response_model=SessionDetail)
async def post_character_translate(
    session_id: str,
    body: _TranslateCharacterBody,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> SessionDetail:
    """Translate the session's character JSON values (skill / weapon /
    equipment names, descriptions, etc.) to the requested language.
    Numeric values, IDs, and universal attribute codes (STR/CON/...) are
    preserved verbatim.

    The translated JSON overwrites ``session.character`` — there's no
    history layer yet; users can re-translate by calling this endpoint
    with a different ``language`` value.
    """
    from services.character_translator import translate_character

    s = await _get_owned_session(db, session_id, user)
    if not isinstance(s.character, dict) or not s.character:
        raise HTTPException(400, "Session has no character to translate")

    try:
        translated = await translate_character(
            db, s.character, target_language=body.language,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface upstream error
        logger.exception("character translate failed")
        raise HTTPException(500, f"Translate failed: {exc}") from exc

    s.character = translated
    await db.commit()
    await db.refresh(s)
    rs = await db.get(Ruleset, s.ruleset_id) if s.ruleset_id else None
    return _detail(
        s,
        rs.book_title if rs else "",
        rs.short_name if rs else None,
    )


@router.post("/{session_id}/npcs/translate", response_model=SessionDetail)
async def post_npcs_translate(
    session_id: str,
    body: _TranslateCharacterBody,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> SessionDetail:
    """Translate every NPC's narrative fields in ``memory_state.npcs[]``
    into the requested language. Numeric stats / params / portrait URLs
    / voice IDs / visibility flags are preserved.

    One LLM call covers the whole roster. The translated values overwrite
    the existing fields — there is no history layer; users can re-call
    with another language to switch back.
    """
    from services.trpg_npc.translate import translate_session_npcs
    from sqlalchemy.orm.attributes import flag_modified

    s = await _get_owned_session(db, session_id, user)
    mem = s.memory_state if isinstance(s.memory_state, dict) else None
    npcs = mem.get("npcs") if isinstance(mem, dict) else None
    if not isinstance(npcs, list) or not npcs:
        raise HTTPException(400, "Session has no NPCs to translate")

    try:
        changed = await translate_session_npcs(
            db, npcs, target_language=body.language,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface upstream error
        logger.exception("npc translate failed")
        raise HTTPException(500, f"Translate failed: {exc}") from exc

    if changed:
        flag_modified(s, "memory_state")
        await db.commit()
        await db.refresh(s)
    rs = await db.get(Ruleset, s.ruleset_id) if s.ruleset_id else None
    return _detail(
        s,
        rs.book_title if rs else "",
        rs.short_name if rs else None,
    )


class _VoiceAssignBody(BaseModel):
    """Body for the manual voice-assignment endpoints. The provider/model
    pair tells us which TTS model the chosen voice belongs to so the
    runtime stamps the same metadata as the auto-assigner."""
    voice: str
    provider: str = ""
    model: str = ""


def _apply_voice_fields(
    target: dict[str, Any],
    body: _VoiceAssignBody,
) -> None:
    """Apply a manual voice choice to a PC/NPC card dict.

    Mirrors the per-provider override shape the runtime resolver
    (`services.trpg_tts._npc_voice_candidates`) reads, so switching providers
    mid-session keeps the manual pick. Setting a non-empty voice also locks
    the slot against rematch and busts any cached voice-intro audio.
    Passing an empty voice clears the slot for that provider and unlocks it.
    """
    voice = body.voice.strip()
    provider = body.provider.strip()
    if voice:
        target["tts_voice"] = voice
        target["active_tts_voice"] = voice
        if body.model:
            target["tts_voice_model"] = body.model
        if provider:
            target["tts_voice_provider"] = provider
            overrides = target.get("tts_voice_overrides")
            if not isinstance(overrides, dict):
                overrides = {}
            overrides[provider] = voice
            target["tts_voice_overrides"] = overrides
        target["tts_voice_locked"] = True
    else:
        target["tts_voice"] = ""
        target["active_tts_voice"] = ""
        target["tts_voice_locked"] = False
        if provider:
            overrides = target.get("tts_voice_overrides")
            if isinstance(overrides, dict) and provider in overrides:
                overrides.pop(provider, None)
                target["tts_voice_overrides"] = overrides
    target["voice_intro_text"] = ""
    target["voice_intro_audio_url"] = ""
    target["voice_intro_signature"] = ""


@router.post("/{session_id}/character/voice", response_model=SessionDetail)
async def post_character_voice(
    session_id: str,
    body: _VoiceAssignBody,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> SessionDetail:
    """Set the player character's TTS voice. Writes both ``tts_voice``
    (primary) and ``active_tts_voice`` (resolved) so the chat TTS picks
    it up immediately. Pass an empty ``voice`` to clear the override."""
    from sqlalchemy.orm.attributes import flag_modified

    s = await _get_owned_session(db, session_id, user)
    if not isinstance(s.character, dict) or not s.character:
        raise HTTPException(400, "Session has no character")
    character = dict(s.character)
    _apply_voice_fields(character, body)
    s.character = character
    flag_modified(s, "character")
    s.last_active_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(s)
    rs = await db.get(Ruleset, s.ruleset_id) if s.ruleset_id else None
    return _detail(
        s,
        rs.book_title if rs else "",
        rs.short_name if rs else None,
    )


@router.post("/{session_id}/npcs/{npc_key}/voice", response_model=SessionDetail)
async def post_npc_voice(
    session_id: str,
    npc_key: str,
    body: _VoiceAssignBody,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> SessionDetail:
    """Set a single NPC's TTS voice in ``memory_state.npcs[]``."""
    from sqlalchemy.orm.attributes import flag_modified

    s = await _get_owned_session(db, session_id, user)
    mem = s.memory_state if isinstance(s.memory_state, dict) else None
    npcs = mem.get("npcs") if isinstance(mem, dict) else None
    if not isinstance(npcs, list):
        raise HTTPException(400, "Session has no NPCs")
    target = next(
        (n for n in npcs if isinstance(n, dict) and str(n.get("key") or "") == npc_key),
        None,
    )
    if target is None:
        raise HTTPException(404, f"NPC '{npc_key}' not found")
    _apply_voice_fields(target, body)
    flag_modified(s, "memory_state")
    s.last_active_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(s)
    rs = await db.get(Ruleset, s.ruleset_id) if s.ruleset_id else None
    return _detail(
        s,
        rs.book_title if rs else "",
        rs.short_name if rs else None,
    )


# -- Setup-time character creation, in-game flow, update/delete ------------
# Setup/flow cluster, `PUT /{session_id}`, and `DELETE /{session_id}` live in
# `routes.session_flow_routes` so this file stays under the 600-line policy.
# Mounted here at the original cluster location so the debug router below it
# still registers in the same order on the parent router.


router.include_router(session_flow_router)


# -- Debug / runtime inspection --------------------------------------------


router.include_router(session_debug_router)


# -- Messages --------------------------------------------------------------


@router.get("/{session_id}/messages", response_model=MessageListResponse)
async def list_messages(
    session_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    before_id: str | None = Query(default=None),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> MessageListResponse:
    """Return up to `limit` of the most recent messages, in ASC order.

    Pagination is cursor-based: pass `before_id` to fetch messages strictly
    older than that message. Compare on `(created_at, id)` so identical
    timestamps still sort deterministically.
    """
    await _get_owned_session(db, session_id, user)
    total_stmt = select(func.count()).select_from(Message).where(
        Message.session_id == session_id
    )
    total = int((await db.execute(total_stmt)).scalar() or 0)

    where_clauses = [Message.session_id == session_id]
    if before_id:
        anchor = (
            await db.execute(
                select(Message.created_at, Message.id).where(
                    Message.id == before_id,
                    Message.session_id == session_id,
                )
            )
        ).first()
        if anchor is None:
            raise HTTPException(404, "before_id not found in this session")
        anchor_ts, anchor_id = anchor
        where_clauses.append(
            or_(
                Message.created_at < anchor_ts,
                and_(
                    Message.created_at == anchor_ts,
                    Message.id < anchor_id,
                ),
            )
        )

    # Fetch newest-first, +1 to detect has_more, then reverse to ASC.
    stmt = (
        select(Message)
        .where(*where_clauses)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit + 1)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    rows.reverse()

    items = [
        MessageOut(
            id=m.id,
            session_id=m.session_id,
            role=m.role,
            content=m.content,
            metadata_json=m.metadata_json,
            created_at=m.created_at,
        )
        for m in rows
    ]
    return MessageListResponse(items=items, total=total, has_more=has_more)


@router.get(
    "/{session_id}/messages/{message_id}/postprocess-steps",
    response_model=PostprocessStepsResponse,
)
async def get_message_postprocess_steps(
    session_id: str,
    message_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> PostprocessStepsResponse:
    """Poll the post-visible step timeline for an assistant message.

    Returns ``{steps, done}`` where ``done`` flips to True once the
    finaliser has written ``phase3_complete``. Frontend polls
    aggressively until ``done`` then stops.
    """
    from services.trpg_postprocess_steps import fetch_steps

    # Ownership check (404 if session is not the user's, then 404 if
    # message is not in the session).
    s = await _get_owned_session(db, session_id, user)
    msg = await db.get(Message, message_id)
    if msg is None or msg.session_id != s.id:
        raise HTTPException(404, "Message not found")

    raw_steps, done = await fetch_steps(db, message_id)
    items: list[PostprocessStep] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            continue
        items.append(PostprocessStep(
            name=str(raw.get("name") or ""),
            status=str(raw.get("status") or "done"),
            duration_ms=int(raw.get("duration_ms") or 0),
            detail=str(raw.get("detail") or ""),
            ts=str(raw.get("ts") or ""),
        ))
    return PostprocessStepsResponse(steps=items, done=done)


@router.post("/{session_id}/messages", response_model=MessageOut)
async def create_message(
    session_id: str,
    body: MessageCreateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> MessageOut:
    s = await _get_owned_session(db, session_id, user)
    if body.role not in {"user", "gm", "system", "dice"}:
        raise HTTPException(422, "role must be one of user|gm|system|dice")
    m = Message(
        id=str(uuid.uuid4()),
        session_id=s.id,
        role=body.role,
        content=body.content,
        metadata_json=body.metadata,
    )
    db.add(m)
    s.last_active_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(m)
    return MessageOut(
        id=m.id,
        session_id=m.session_id,
        role=m.role,
        content=m.content,
        metadata_json=m.metadata_json,
        created_at=m.created_at,
    )


@router.post("/{session_id}/messages/{message_id}/tts/stream")
async def stream_message_tts(
    session_id: str,
    message_id: str,
    body: MessageTtsStreamRequest,
    user: User = Depends(current_user),
) -> EventSourceResponse:
    """Stream per-segment TTS for a persisted GM message."""

    async def _generate() -> AsyncIterator[dict[str, str]]:
        factory = get_session_factory()
        async with factory() as db:
            s = await _get_owned_session(db, session_id, user)
            msg = await db.get(Message, message_id)
            if msg is None or msg.session_id != s.id:
                yield {
                    "data": json.dumps(
                        {"type": "error", "message": "message not found"},
                        ensure_ascii=False,
                    )
                }
                return
            from services.trpg_tts import stream_message_tts_events

            async for event in stream_message_tts_events(
                db,
                s,
                msg,
                user_id=user.id,
                request_text=body.text or "",
            ):
                yield {"data": json.dumps(event, ensure_ascii=False)}

    return EventSourceResponse(_generate(), ping=15)
