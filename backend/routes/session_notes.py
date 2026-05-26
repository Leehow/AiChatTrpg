"""Player-notes CRUD on top of ``GameSession.memory_state["player_notes"]``.

Canonical storage stays in the existing JSON column — no new table — so notes
produced by the in-game ``[ADD_NOTE]`` marker pipeline
(``services/trpg_ic_markers.apply_chatrpg_markers``) and notes created
through this route coexist in the same array. Legacy marker rows lack
``source``/``updated_at`` and are lazily normalized on read; that lets the
floating-notes UI render every note without rewriting historical state.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from orm.models import GameSession, User
from routes.deps import current_user, db_session
from schemas.session import (
    PlayerNoteCreateRequest,
    PlayerNoteDeleteResponse,
    PlayerNoteOut,
    PlayerNoteUpdateRequest,
    PlayerNoteWriteResponse,
    PlayerNotesListResponse,
)


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


_MAX_CONTENT_LEN = 4000
_MAX_TAGS = 16
_MAX_TAG_LEN = 64


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_tags(raw: Any) -> list[str]:
    """Trim and dedupe a raw tag list, dropping non-strings and blanks.
    Order is preserved so the UI sees the first occurrence position."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str):
            continue
        text = entry.strip()
        if not text or text in seen:
            continue
        if len(text) > _MAX_TAG_LEN:
            text = text[:_MAX_TAG_LEN]
        out.append(text)
        seen.add(text)
        if len(out) >= _MAX_TAGS:
            break
    return out


def _normalize_note(raw: Any) -> dict[str, Any] | None:
    """Coerce one persisted note dict to the canonical shape used by the API.

    Marker-produced rows look like ``{"id", "content", "tags", "created_at"}``
    with no ``source``. Older rows may even lack ``id``. Anything without
    usable text is dropped so the UI never sees a blank row.
    """
    if not isinstance(raw, dict):
        return None
    content_val = raw.get("content")
    if not isinstance(content_val, str):
        content_val = raw.get("text") if isinstance(raw.get("text"), str) else ""
    content = content_val.strip() if isinstance(content_val, str) else ""
    if not content:
        return None
    note_id_val = raw.get("id")
    note_id = str(note_id_val).strip() if note_id_val else ""
    if not note_id:
        note_id = str(uuid.uuid4())
    source_val = raw.get("source")
    source = str(source_val).strip() if isinstance(source_val, str) else ""
    if source not in ("player", "gm"):
        # Marker-emitted notes never carry source; treat them as GM-authored
        # so the UI can render a different chip without erasing history.
        source = "gm"
    created_at = raw.get("created_at") if isinstance(raw.get("created_at"), str) else None
    updated_at = raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else None
    return {
        "id": note_id,
        "content": content,
        "tags": _normalize_tags(raw.get("tags")),
        "source": source,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _ensure_memory_state(session: GameSession) -> dict[str, Any]:
    mem = session.memory_state
    return dict(mem) if isinstance(mem, dict) else {}


def _read_notes(memory_state: dict[str, Any]) -> list[dict[str, Any]]:
    bucket = memory_state.get("player_notes")
    return [n for n in bucket if isinstance(n, dict)] if isinstance(bucket, list) else []


def _normalize_bucket(memory_state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every note normalized for display, mutating the in-memory
    bucket in place so subsequent updates target stable IDs/sources."""
    raw_bucket = memory_state.get("player_notes")
    if not isinstance(raw_bucket, list):
        memory_state["player_notes"] = []
        return []
    normalized: list[dict[str, Any]] = []
    cleaned: list[dict[str, Any]] = []
    for entry in raw_bucket:
        note = _normalize_note(entry)
        if note is None:
            continue
        cleaned.append(note)
        normalized.append(note)
    memory_state["player_notes"] = cleaned
    return normalized


async def _get_owned_session(
    db: AsyncSession, session_id: str, user: User,
) -> GameSession:
    s = await db.get(GameSession, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "session not found")
    return s


def _persist_notes(session: GameSession, memory_state: dict[str, Any]) -> None:
    session.memory_state = memory_state
    flag_modified(session, "memory_state")
    session.last_active_at = datetime.now(timezone.utc)


def add_note(
    memory_state: dict[str, Any], *, content: str, tags: Any = None,
) -> dict[str, Any]:
    """Append a new player-authored note. Raises ``ValueError`` on empty
    content so the caller can translate to HTTP 400.
    """
    text = (content or "").strip()
    if not text:
        raise ValueError("content must not be empty")
    if len(text) > _MAX_CONTENT_LEN:
        text = text[:_MAX_CONTENT_LEN]
    note = {
        "id": str(uuid.uuid4()),
        "content": text,
        "tags": _normalize_tags(tags),
        "source": "player",
        "created_at": _now_iso(),
        "updated_at": None,
    }
    bucket = _normalize_bucket(memory_state)
    bucket.append(note)
    memory_state["player_notes"] = bucket
    return note


def update_note(
    memory_state: dict[str, Any],
    note_id: str,
    *,
    content: Any = None,
    tags: Any = None,
) -> dict[str, Any]:
    """Patch an existing player note in place. Either field may be omitted;
    an empty new content raises ``ValueError``. Missing id raises
    ``KeyError``. Notes whose ``source != "player"`` (GM/legacy `[ADD_NOTE]`
    rows) are read-only and raise ``PermissionError`` so the route can
    surface a 403.
    """
    bucket = _normalize_bucket(memory_state)
    target: dict[str, Any] | None = None
    for entry in bucket:
        if entry["id"] == note_id:
            target = entry
            break
    if target is None:
        raise KeyError(note_id)
    if target.get("source") != "player":
        raise PermissionError(note_id)
    if content is not None:
        text = str(content).strip()
        if not text:
            raise ValueError("content must not be empty")
        if len(text) > _MAX_CONTENT_LEN:
            text = text[:_MAX_CONTENT_LEN]
        target["content"] = text
    if tags is not None:
        target["tags"] = _normalize_tags(tags)
    target["updated_at"] = _now_iso()
    memory_state["player_notes"] = bucket
    return target


def delete_note(memory_state: dict[str, Any], note_id: str) -> None:
    """Drop a player note by id. Missing id raises ``KeyError``. GM/legacy
    notes (``source != "player"``) are read-only and raise
    ``PermissionError`` so the route can surface a 403.
    """
    bucket = _normalize_bucket(memory_state)
    target: dict[str, Any] | None = None
    for entry in bucket:
        if entry["id"] == note_id:
            target = entry
            break
    if target is None:
        raise KeyError(note_id)
    if target.get("source") != "player":
        raise PermissionError(note_id)
    memory_state["player_notes"] = [n for n in bucket if n["id"] != note_id]


@router.get(
    "/{session_id}/notes",
    response_model=PlayerNotesListResponse,
)
async def list_notes(
    session_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> PlayerNotesListResponse:
    s = await _get_owned_session(db, session_id, user)
    raw = s.memory_state if isinstance(s.memory_state, dict) else {}
    notes = [PlayerNoteOut(**n) for n in (_normalize_note(r) for r in _read_notes(raw)) if n]
    return PlayerNotesListResponse(notes=notes)


@router.post(
    "/{session_id}/notes",
    response_model=PlayerNoteWriteResponse,
)
async def create_note(
    session_id: str,
    body: PlayerNoteCreateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> PlayerNoteWriteResponse:
    s = await _get_owned_session(db, session_id, user)
    memory_state = _ensure_memory_state(s)
    try:
        note = add_note(memory_state, content=body.content, tags=body.tags)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _persist_notes(s, memory_state)
    await db.commit()
    await db.refresh(s)
    return PlayerNoteWriteResponse(note=PlayerNoteOut(**note))


@router.post(
    "/{session_id}/notes/{note_id}",
    response_model=PlayerNoteWriteResponse,
)
async def update_note_route(
    session_id: str,
    note_id: str,
    body: PlayerNoteUpdateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> PlayerNoteWriteResponse:
    s = await _get_owned_session(db, session_id, user)
    memory_state = _ensure_memory_state(s)
    try:
        note = update_note(
            memory_state,
            note_id,
            content=body.content,
            tags=body.tags,
        )
    except KeyError:
        raise HTTPException(404, "note not found")
    except PermissionError:
        raise HTTPException(403, "note is read-only")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _persist_notes(s, memory_state)
    await db.commit()
    await db.refresh(s)
    return PlayerNoteWriteResponse(note=PlayerNoteOut(**note))


@router.delete(
    "/{session_id}/notes/{note_id}",
    response_model=PlayerNoteDeleteResponse,
)
async def delete_note_route(
    session_id: str,
    note_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> PlayerNoteDeleteResponse:
    s = await _get_owned_session(db, session_id, user)
    memory_state = _ensure_memory_state(s)
    try:
        delete_note(memory_state, note_id)
    except KeyError:
        raise HTTPException(404, "note not found")
    except PermissionError:
        raise HTTPException(403, "note is read-only")
    _persist_notes(s, memory_state)
    await db.commit()
    return PlayerNoteDeleteResponse()
