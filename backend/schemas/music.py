from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MusicTrackOut(BaseModel):
    id: str
    title: str
    source_type: str
    url: str
    is_public: bool
    owner_id: str
    owner_username: str
    is_mine: bool
    created_at: datetime
    updated_at: datetime


class MusicTrackCreateRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    title: str = Field(default="", max_length=255)
    is_public: bool = True


class MusicTrackUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    is_public: bool | None = None
