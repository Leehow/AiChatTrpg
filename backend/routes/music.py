"""Music tracks: per-user library with public/private sharing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from orm.models import MusicTrack, User
from routes.deps import current_user, db_session
from schemas.common import OkResponse
from schemas.music import (
    MusicTrackCreateRequest,
    MusicTrackOut,
    MusicTrackUpdateRequest,
)
from services.music import (
    create_track_from_upload,
    create_track_from_url,
    list_visible_tracks,
)

router = APIRouter(prefix="/api/music", tags=["music"])

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB


def _to_out(track: MusicTrack, owner: User, viewer: User) -> MusicTrackOut:
    return MusicTrackOut(
        id=track.id,
        title=track.title,
        source_type=track.source_type,
        url=track.url,
        is_public=track.is_public,
        owner_id=owner.id,
        owner_username=owner.username,
        is_mine=owner.id == viewer.id,
        created_at=track.created_at,
        updated_at=track.updated_at,
    )


@router.get("", response_model=list[MusicTrackOut])
async def list_tracks(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> list[MusicTrackOut]:
    rows = await list_visible_tracks(db, user_id=user.id)
    return [_to_out(track, owner, user) for track, owner in rows]


@router.post("", response_model=MusicTrackOut)
async def create_track(
    body: MusicTrackCreateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> MusicTrackOut:
    url = body.url.strip()
    if not url.startswith(("http://", "https://", "/api/media/files/")):
        raise HTTPException(400, "url must start with http://, https:// or /api/media/files/")
    track = await create_track_from_url(
        db,
        user_id=user.id,
        url=url,
        title=body.title.strip(),
        is_public=body.is_public,
    )
    await db.commit()
    await db.refresh(track)
    return _to_out(track, user, user)


@router.post("/upload", response_model=MusicTrackOut)
async def upload_track(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    is_public: bool = Form(default=True),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> MusicTrackOut:
    if not file.filename:
        raise HTTPException(400, "filename required")
    payload = await file.read()
    if not payload:
        raise HTTPException(400, "empty upload")
    if len(payload) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, "audio file exceeds 25 MB limit")
    try:
        track = await create_track_from_upload(
            db,
            user_id=user.id,
            payload=payload,
            filename=file.filename,
            content_type=file.content_type or "",
            title=title.strip(),
            is_public=is_public,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.commit()
    await db.refresh(track)
    return _to_out(track, user, user)


@router.put("/{track_id}", response_model=MusicTrackOut)
async def update_track(
    track_id: str,
    body: MusicTrackUpdateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> MusicTrackOut:
    track = await db.get(MusicTrack, track_id)
    if track is None or track.user_id != user.id:
        raise HTTPException(404, "track not found")
    if body.title is not None:
        track.title = body.title.strip()[:255] or track.title
    if body.is_public is not None:
        track.is_public = body.is_public
    await db.commit()
    await db.refresh(track)
    return _to_out(track, user, user)


@router.delete("/{track_id}", response_model=OkResponse)
async def delete_track(
    track_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> OkResponse:
    track = await db.get(MusicTrack, track_id)
    if track is None or track.user_id != user.id:
        raise HTTPException(404, "track not found")
    await db.delete(track)
    await db.commit()
    return OkResponse()
