from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class MusicTrack(Base, TimestampMixin):
    """A music track owned by a user, sharable to other players when public.

    `source_type` distinguishes externally-hosted URLs from files uploaded
    into `data/media/` and served via `/api/media/files/{filename}`.
    `is_public` defaults to True so other logged-in users can see and
    play the track in the bottom-left music player.
    """

    __tablename__ = "music_tracks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="url")
    url: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
