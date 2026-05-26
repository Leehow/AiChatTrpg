from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    id: str
    name: str
    username: str
    role: str
    preferences: dict[str, Any] = Field(default_factory=dict)


class LoginResponse(BaseModel):
    token: str
    user: UserInfo


class RegistrationStatusResponse(BaseModel):
    enabled: bool
    invite_required: bool


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8, max_length=255)
    name: str | None = Field(default=None, max_length=128)
    invite_code: str | None = Field(default=None, max_length=128)

    @field_validator("username")
    @classmethod
    def clean_username(cls, value: str) -> str:
        username = value.strip()
        if not username:
            raise ValueError("username required")
        return username

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("invite_code")
    @classmethod
    def clean_invite_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class PreferencesUpdateRequest(BaseModel):
    """Partial-merge update. Keys present here overwrite existing keys;
    other keys are preserved. To delete a key, send it with value null."""
    patch: dict[str, Any]
