"""Model pool HTTP routes — DB-backed.

Adding to the pool also writes any user-supplied api_key / base_url
through to admin_config so chat sessions and the dice-IR compiler
pick up the same credentials. The pool itself only stores
(provider, model) pairs plus a `is_default` flag.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from llm import list_providers
from orm.models import ModelPoolEntry
from routes.deps import db_session
from services import admin_config, model_pool

router = APIRouter(prefix="/api/llm/pool", tags=["llm"])


class PoolEntryView(BaseModel):
    provider: str
    model: str


class PoolView(BaseModel):
    entries: list[PoolEntryView] = Field(default_factory=list)
    default_index: int = -1
    default: PoolEntryView | None = None
    fast_index: int = -1
    fast: PoolEntryView | None = None
    dialogue_index: int = -1
    dialogue: PoolEntryView | None = None
    avatar_index: int = -1
    avatar: PoolEntryView | None = None
    illustration_index: int = -1
    illustration: PoolEntryView | None = None
    narration_index: int = -1
    narration: PoolEntryView | None = None


class AddRequest(BaseModel):
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""


def _to_view(rows: list[ModelPoolEntry]) -> PoolView:
    entries = [PoolEntryView(provider=r.provider, model=r.model) for r in rows]
    role_fields: dict[str, tuple[int, PoolEntryView | None]] = {}
    for role, flag in model_pool.ROLES.items():
        idx = next((i for i, r in enumerate(rows) if getattr(r, flag)), -1)
        entry = entries[idx] if 0 <= idx < len(entries) else None
        role_fields[role] = (idx, entry)
    return PoolView(
        entries=entries,
        default_index=role_fields["default"][0],
        default=role_fields["default"][1],
        fast_index=role_fields["fast"][0],
        fast=role_fields["fast"][1],
        dialogue_index=role_fields["dialogue"][0],
        dialogue=role_fields["dialogue"][1],
        avatar_index=role_fields["avatar"][0],
        avatar=role_fields["avatar"][1],
        illustration_index=role_fields["illustration"][0],
        illustration=role_fields["illustration"][1],
        narration_index=role_fields["narration"][0],
        narration=role_fields["narration"][1],
    )


def _persist_auth(
    provider: str, model: str, api_key: str, base_url: str
) -> None:
    """Mirror api_key/base_url and the model name into admin_config."""
    if provider == "mock":
        return
    api_key = api_key.strip()
    base_url = base_url.strip()
    existing = admin_config.get_provider(provider) or {}
    models = list(existing.get("models") or [])
    if model and model not in models:
        models.append(model)
    if api_key or base_url or models != list(existing.get("models") or []):
        admin_config.save_provider(
            provider,
            {
                "api_key": api_key or existing.get("api_key", ""),
                "base_url": base_url or existing.get("base_url", ""),
                "models": models,
            },
        )


@router.get("", response_model=PoolView)
async def get_pool(
    db: AsyncSession = Depends(db_session),
) -> PoolView:
    rows = await model_pool.list_entries(db)
    return _to_view(rows)


@router.post("/add", response_model=PoolView)
async def add_entry(
    body: AddRequest,
    db: AsyncSession = Depends(db_session),
) -> PoolView:
    if body.provider not in list_providers():
        raise HTTPException(400, f"unknown provider '{body.provider}'")
    _persist_auth(body.provider, body.model, body.api_key, body.base_url)
    try:
        rows = await model_pool.add_entry(db, body.provider, body.model)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _to_view(rows)


@router.post("/remove", response_model=PoolView)
async def remove_entry(
    body: PoolEntryView,
    db: AsyncSession = Depends(db_session),
) -> PoolView:
    rows = await model_pool.remove_entry(db, body.provider, body.model)
    return _to_view(rows)


async def _set_role(
    role: str, body: PoolEntryView, db: AsyncSession
) -> PoolView:
    try:
        rows = await model_pool.set_role(db, role, body.provider, body.model)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _to_view(rows)


@router.post("/default", response_model=PoolView)
async def set_default(
    body: PoolEntryView, db: AsyncSession = Depends(db_session)
) -> PoolView:
    return await _set_role("default", body, db)


@router.post("/fast", response_model=PoolView)
async def set_fast(
    body: PoolEntryView, db: AsyncSession = Depends(db_session)
) -> PoolView:
    return await _set_role("fast", body, db)


@router.post("/dialogue", response_model=PoolView)
async def set_dialogue(
    body: PoolEntryView, db: AsyncSession = Depends(db_session)
) -> PoolView:
    return await _set_role("dialogue", body, db)


@router.post("/avatar", response_model=PoolView)
async def set_avatar(
    body: PoolEntryView, db: AsyncSession = Depends(db_session)
) -> PoolView:
    return await _set_role("avatar", body, db)


@router.post("/illustration", response_model=PoolView)
async def set_illustration(
    body: PoolEntryView, db: AsyncSession = Depends(db_session)
) -> PoolView:
    return await _set_role("illustration", body, db)


@router.post("/narration", response_model=PoolView)
async def set_narration(
    body: PoolEntryView, db: AsyncSession = Depends(db_session)
) -> PoolView:
    return await _set_role("narration", body, db)
