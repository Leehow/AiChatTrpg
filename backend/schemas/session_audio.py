"""Schemas for the per-session audio endpoints in routes/session_audio.py."""

from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.music import MusicTrackOut
from schemas.session import SessionDetail


class SessionBgmListResponse(BaseModel):
    """Current BGM selection plus the visible tracks that back it.

    `tracks` is filtered to the caller's visible library (own + public) so the
    frontend can render a picker without a second round-trip. `track_ids`
    preserves the user's chosen order and may include ids that are no longer
    visible (e.g. a public track that went private); those are surfaced so the
    UI can warn rather than silently dropping them.
    """
    track_ids: list[str] = Field(default_factory=list)
    tracks: list[MusicTrackOut] = Field(default_factory=list)


class SessionBgmSelectionRequest(BaseModel):
    track_ids: list[str] = Field(default_factory=list)


class NpcRematchVoicesRequest(BaseModel):
    skip_locked: bool = True
    force: bool = False


class NpcRematchVoicesResponse(BaseModel):
    session: SessionDetail
    rematched: int = 0
    skipped_locked: int = 0
    voice_model: str = ""


class VoiceIntroRequest(BaseModel):
    force: bool = False


class VoiceIntroResponse(BaseModel):
    text: str
    audio_url: str = ""
    provider: str = ""
    model: str = ""
    voice: str = ""
    cached: bool = False
