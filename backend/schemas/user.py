from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class UserOut(BaseModel):
    id: str
    name: str
    username: str
    role: str
    preferences: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=255)
    name: str | None = None
    role: str = "player"


class UserUpdateRequest(BaseModel):
    """Admin can change name/password/role on a user. All optional."""
    name: str | None = None
    password: str | None = Field(default=None, min_length=1, max_length=255)
    role: str | None = None


class InviteCodeOut(BaseModel):
    id: str
    label: str
    max_uses: int
    use_count: int
    remaining_uses: int
    disabled: bool
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class InviteCodeCreateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=128)
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_at: datetime | None = None
