from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CharacterPoolCreateRequest(BaseModel):
    ruleset_id: str
    character: dict[str, Any]
    source: str = "uploaded"
    source_session_id: str | None = None


class CharacterPoolOut(BaseModel):
    id: str
    ruleset_id: str
    ruleset_title: str
    ruleset_short_name: str | None = None
    name: str
    source: str
    source_session_id: str | None = None
    character: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
