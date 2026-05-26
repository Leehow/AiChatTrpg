"""Music track persistence + upload helper."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from orm.models import MusicTrack, User
from services.media_storage import store_audio_bytes


_AUDIO_EXTENSIONS = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "opus": "audio/opus",
    "flac": "audio/flac",
    "aac": "audio/aac",
    "m4a": "audio/mp4",
}


def derive_title_from_url(url: str) -> str:
    """Pick a reasonable display title from a URL when none is supplied."""
    cleaned = url.split("?", 1)[0].rstrip("/")
    if not cleaned:
        return "Untitled"
    last = cleaned.rsplit("/", 1)[-1]
    name = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", last) or last
    return (name or "Untitled")[:255]


def normalise_audio_mime(filename: str, content_type: str) -> str:
    """Best-effort audio mime detection from filename + browser-supplied type."""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    by_ext = _AUDIO_EXTENSIONS.get(suffix, "")
    declared = (content_type or "").split(";", 1)[0].strip().lower()
    if declared and declared.startswith("audio/"):
        return declared
    return by_ext or "audio/mpeg"


async def list_visible_tracks(
    db: AsyncSession,
    *,
    user_id: str,
) -> list[tuple[MusicTrack, User]]:
    """Tracks the caller can see: their own + any public track from others."""
    stmt = (
        select(MusicTrack, User)
        .join(User, User.id == MusicTrack.user_id)
        .where(or_(MusicTrack.user_id == user_id, MusicTrack.is_public.is_(True)))
        .order_by(MusicTrack.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.all())


async def create_track_from_url(
    db: AsyncSession,
    *,
    user_id: str,
    url: str,
    title: str,
    is_public: bool,
) -> MusicTrack:
    track = MusicTrack(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=(title or derive_title_from_url(url))[:255],
        source_type="url",
        url=url[:2048],
        is_public=is_public,
    )
    db.add(track)
    return track


async def create_track_from_upload(
    db: AsyncSession,
    *,
    user_id: str,
    payload: bytes,
    filename: str,
    content_type: str,
    title: str,
    is_public: bool,
) -> MusicTrack:
    mime = normalise_audio_mime(filename, content_type)
    stored_url = store_audio_bytes(payload, mime)
    if not stored_url:
        raise ValueError("upload produced no storable bytes")
    display_title = title or re.sub(r"\.[A-Za-z0-9]{1,5}$", "", filename) or "Untitled"
    track = MusicTrack(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=display_title[:255],
        source_type="upload",
        url=stored_url[:2048],
        is_public=is_public,
    )
    db.add(track)
    return track
