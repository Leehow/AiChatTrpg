from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RulesetSummary(BaseModel):
    id: str
    owner_id: str
    is_shared: bool
    book_id: str
    book_title: str
    world_mode: str
    has_dice_ir: bool
    has_check_spec: bool
    has_character_ui: bool = False
    created_at: datetime
    updated_at: datetime


class RulesetDetail(RulesetSummary):
    parsed_v6: dict[str, Any]
    dice_ir: dict[str, Any] | None = None
    check_spec: dict[str, Any] | None = None
    character_ui: dict[str, Any] | None = None


class RulesetShareRequest(BaseModel):
    is_shared: bool


class CompileCharacterUIRequest(BaseModel):
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    output_language: str | None = None
    save: bool = True


class CompileCharacterUIResponse(BaseModel):
    ok: bool
    ruleset_id: str
    artifact_saved: bool
    package: dict[str, Any]
    output_language: str | None = None


class RulesetUploadRequest(BaseModel):
    """Caller posts the raw v6 JSON artifact verbatim."""

    artifact: dict[str, Any] = Field(..., description="raw v6 JSON")


class CompileDiceIRRequest(BaseModel):
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    output_language: str | None = None
    save: bool = True


class CompileDiceIRResponse(BaseModel):
    ok: bool
    ruleset_id: str
    artifact_saved: bool
    package: dict[str, Any]
    output_language: str | None = None


class ApplyCheckSpecRequest(BaseModel):
    procedure_id: str | None = None
    check_spec: dict[str, Any] | None = None
