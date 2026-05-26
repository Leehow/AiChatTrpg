"""Per-session audio endpoints: BGM selection, NPC voice rematch, voice intro.

BGM selection lives in ``GameSession.memory_state["_settings"]["bgm_track_ids"]``;
voice intro audio is cached on the PC/NPC dict via a ``voice_intro_signature``
of provider/model/voice/text; rematch reuses ``_assign_missing_voices``.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from orm.models import Ruleset, User
from routes.deps import current_user, db_session
from routes.music import _to_out as _track_to_out
from routes.sessions import _detail, _get_owned_session
from schemas.session import SessionDetail
from schemas.session_audio import (
    NpcRematchVoicesRequest,
    NpcRematchVoicesResponse,
    SessionBgmListResponse,
    SessionBgmSelectionRequest,
    VoiceIntroRequest,
    VoiceIntroResponse,
)
from services import model_pool
from services.media_generation import (
    MediaGenerationError,
    default_voice_for,
    is_tts_model,
    synthesize_speech,
)
from services.media_storage import store_audio_reference
from services.music import list_visible_tracks
from services.trpg_npc.assets import (
    _assign_missing_voices,
    _resolve_role_model,
    _tts_provider_for_model,
)
from services.trpg_tts import _resolve_tts_runtime

logger = logging.getLogger("chatrpg.session_audio")

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


_SETTINGS_KEY = "_settings"
_BGM_KEY = "bgm_track_ids"


# -- BGM --------------------------------------------------------------------


def _read_bgm_track_ids(session: Any) -> list[str]:
    mem = session.memory_state if isinstance(session.memory_state, dict) else {}
    settings = mem.get(_SETTINGS_KEY)
    if not isinstance(settings, dict):
        return []
    raw = settings.get(_BGM_KEY)
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tid = str(item or "").strip()
        if tid and tid not in seen:
            seen.add(tid)
            out.append(tid)
    return out


def _write_bgm_track_ids(session: Any, track_ids: list[str]) -> None:
    mem = dict(session.memory_state) if isinstance(session.memory_state, dict) else {}
    settings = mem.get(_SETTINGS_KEY)
    if not isinstance(settings, dict):
        settings = {}
    settings = dict(settings)
    settings[_BGM_KEY] = list(track_ids)
    mem[_SETTINGS_KEY] = settings
    session.memory_state = mem
    flag_modified(session, "memory_state")


def normalize_bgm_selection(
    raw_ids: list[str],
    visible_ids: set[str],
) -> list[str]:
    """Preserve order, dedupe, reject ids the caller can't see."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_ids:
        tid = str(raw or "").strip()
        if not tid:
            continue
        if tid in seen:
            continue
        if tid not in visible_ids:
            raise HTTPException(400, f"track '{tid}' is not visible to this user")
        seen.add(tid)
        out.append(tid)
    return out


@router.get("/{session_id}/bgm", response_model=SessionBgmListResponse)
async def get_session_bgm(
    session_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> SessionBgmListResponse:
    s = await _get_owned_session(db, session_id, user)
    rows = await list_visible_tracks(db, user_id=user.id)
    track_ids = _read_bgm_track_ids(s)
    return SessionBgmListResponse(
        track_ids=track_ids,
        tracks=[_track_to_out(track, owner, user) for track, owner in rows],
    )


@router.post("/{session_id}/bgm/selection", response_model=SessionBgmListResponse)
async def post_session_bgm_selection(
    session_id: str,
    body: SessionBgmSelectionRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> SessionBgmListResponse:
    s = await _get_owned_session(db, session_id, user)
    rows = await list_visible_tracks(db, user_id=user.id)
    visible_ids = {track.id for track, _owner in rows}
    cleaned = normalize_bgm_selection(body.track_ids, visible_ids)
    _write_bgm_track_ids(s, cleaned)
    s.last_active_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(s)
    return SessionBgmListResponse(
        track_ids=cleaned,
        tracks=[_track_to_out(track, owner, user) for track, owner in rows],
    )


# -- NPC rematch ------------------------------------------------------------


def _is_npc_locked(npc: dict[str, Any]) -> bool:
    return bool(npc.get("tts_voice_locked"))


def _clear_npc_voice_slots(npc: dict[str, Any], provider: str) -> None:
    """Drop the voice fields the assigner consults so it picks a fresh one.

    We intentionally do not touch other providers' overrides — a user who later
    switches the dialogue model back should still see their old MiniMax pick.
    """
    npc["tts_voice"] = ""
    npc["active_tts_voice"] = ""
    npc["tts_voice_model"] = ""
    npc["tts_voice_provider"] = ""
    overrides = npc.get("tts_voice_overrides")
    if isinstance(overrides, dict) and provider in overrides:
        overrides.pop(provider, None)
        npc["tts_voice_overrides"] = overrides


@router.post("/{session_id}/npcs/rematch-voices", response_model=NpcRematchVoicesResponse)
async def post_npcs_rematch_voices(
    session_id: str,
    body: NpcRematchVoicesRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> NpcRematchVoicesResponse:
    s = await _get_owned_session(db, session_id, user)
    mem = s.memory_state if isinstance(s.memory_state, dict) else None
    npcs = mem.get("npcs") if isinstance(mem, dict) else None
    if not isinstance(npcs, list) or not npcs:
        raise HTTPException(400, "Session has no NPCs")

    voice_model = await _resolve_role_model(db, "dialogue")
    voice_model_name = voice_model.model if voice_model else "qwen3-tts-flash"
    provider = _tts_provider_for_model(voice_model_name)

    # `skip_locked` is accepted for API symmetry but does not relax the lock.
    # Locked NPCs are only ever cleared when the caller explicitly opts in
    # with `force=True`, so a request like {skip_locked: false, force: false}
    # still preserves manually-locked voices.
    allow_clear_locked = bool(body.force)
    rematched = 0
    skipped_locked = 0
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        if _is_npc_locked(npc) and not allow_clear_locked:
            skipped_locked += 1
            continue
        _clear_npc_voice_slots(npc, provider)
        npc["voice_intro_text"] = ""
        npc["voice_intro_audio_url"] = ""
        npc["voice_intro_signature"] = ""
        rematched += 1

    if rematched:
        _assign_missing_voices(npcs, voice_model_name)
        flag_modified(s, "memory_state")
        s.last_active_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(s)

    rs = await db.get(Ruleset, s.ruleset_id) if s.ruleset_id else None
    detail = _detail(
        s,
        rs.book_title if rs else "",
        rs.short_name if rs else None,
    )
    return NpcRematchVoicesResponse(
        session=detail,
        rematched=rematched,
        skipped_locked=skipped_locked,
        voice_model=voice_model_name,
    )


# -- Voice intro ------------------------------------------------------------


def build_voice_intro_text(card: dict[str, Any], *, default_name: str = "Stranger") -> str:
    """Deterministic short intro built from card fields; language-neutral."""
    name = str(card.get("name") or "").strip() or default_name
    role = (
        str(card.get("role") or "").strip()
        or str(card.get("title") or "").strip()
        or str(card.get("class") or "").strip()
    )
    description = (
        str(card.get("description") or "").strip()
        or str(card.get("summary") or "").strip()
    )
    hint = (
        str(card.get("voice_hint") or "").strip()
        or str(card.get("dialogue_style") or "").strip()
    )
    parts: list[str] = [name]
    if role:
        parts.append(role)
    if description:
        parts.append(description[:160])
    if hint:
        parts.append(hint[:160])
    text = " — ".join(parts)
    return text[:400] or default_name


def voice_intro_signature(provider: str, model: str, voice: str, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{provider}:{model}:{voice}:{digest}"


def _card_voice(card: dict[str, Any], provider: str) -> str:
    overrides = card.get("tts_voice_overrides")
    if isinstance(overrides, dict):
        override = str(overrides.get(provider) or "").strip()
        if override:
            return override
    active = str(card.get("active_tts_voice") or "").strip()
    if active:
        return active
    return str(card.get("tts_voice") or "").strip()


async def _resolve_voice_intro(
    db: AsyncSession,
    card: dict[str, Any],
    *,
    force: bool,
) -> VoiceIntroResponse:
    runtime = await _resolve_tts_runtime(db, "dialogue")
    if runtime is None:
        raise HTTPException(409, "No dialogue TTS model configured in the model pool")

    provider = runtime.provider
    model = runtime.model
    voice = _card_voice(card, _tts_provider_for_model(model))
    if not voice:
        voice = default_voice_for(provider, model)
    if not voice:
        raise HTTPException(409, "No TTS voice available for this character")
    if provider != "mock" and not is_tts_model(provider, model):
        raise HTTPException(400, f"{provider}:{model} is not a TTS model")

    text = build_voice_intro_text(card)
    signature = voice_intro_signature(provider, model, voice, text)
    cached_sig = str(card.get("voice_intro_signature") or "").strip()
    cached_url = str(card.get("voice_intro_audio_url") or "").strip()
    cached_text = str(card.get("voice_intro_text") or "").strip()
    if not force and cached_sig == signature and cached_text:
        return VoiceIntroResponse(
            text=cached_text,
            audio_url=cached_url,
            provider=provider,
            model=model,
            voice=voice,
            cached=True,
        )

    audio_url = ""
    if provider == "mock":
        audio_url = ""
    else:
        try:
            result = await synthesize_speech(
                runtime.media_runtime(),
                text,
                voice=voice,
                instructions="Short character self-introduction; warm, in-character delivery.",
                language="auto",
            )
        except MediaGenerationError as exc:
            raise HTTPException(502, f"TTS failed: {exc}") from exc
        reference = result.audio_data_uri or result.audio_url
        try:
            audio_url = await store_audio_reference(reference) or result.audio_url
        except ValueError as exc:
            raise HTTPException(502, str(exc)) from exc

    card["voice_intro_text"] = text
    card["voice_intro_audio_url"] = audio_url
    card["voice_intro_signature"] = signature
    card["voice_intro_provider"] = provider
    card["voice_intro_model"] = model
    card["voice_intro_voice"] = voice
    return VoiceIntroResponse(
        text=text,
        audio_url=audio_url,
        provider=provider,
        model=model,
        voice=voice,
        cached=False,
    )


@router.post(
    "/{session_id}/character/voice-intro",
    response_model=VoiceIntroResponse,
)
async def post_character_voice_intro(
    session_id: str,
    body: VoiceIntroRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> VoiceIntroResponse:
    s = await _get_owned_session(db, session_id, user)
    if not isinstance(s.character, dict) or not s.character:
        raise HTTPException(400, "Session has no character")
    character = dict(s.character)
    response = await _resolve_voice_intro(db, character, force=body.force)
    s.character = character
    flag_modified(s, "character")
    s.last_active_at = datetime.now(timezone.utc)
    await db.commit()
    return response
@router.post(
    "/{session_id}/npcs/{npc_key}/voice-intro",
    response_model=VoiceIntroResponse,
)
async def post_npc_voice_intro(
    session_id: str,
    npc_key: str,
    body: VoiceIntroRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> VoiceIntroResponse:
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
    response = await _resolve_voice_intro(db, target, force=body.force)
    flag_modified(s, "memory_state")
    s.last_active_at = datetime.now(timezone.utc)
    await db.commit()
    return response
