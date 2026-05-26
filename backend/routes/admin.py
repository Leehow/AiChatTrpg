"""Admin routes — single-user settings panel for provider keys + model lists."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from llm import list_providers
from services import admin_config

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ProviderView(BaseModel):
    provider: str
    api_key: str = ""
    api_key_set: bool = False
    base_url: str = ""
    models: list[str] = Field(default_factory=list)
    default_model: str = ""
    env_has_key: bool = False


class ProviderUpdate(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    models: list[str] = Field(default_factory=list)


def _mask(view: dict[str, Any], provider: str) -> ProviderView:
    api_key = view.get("api_key", "")
    return ProviderView(
        provider=provider,
        api_key="",
        api_key_set=bool(api_key),
        base_url=view.get("base_url", ""),
        models=list(view.get("models") or []),
        default_model=view.get("default_model", ""),
        env_has_key=bool(view.get("env_has_key")),
    )


@router.get("/providers", response_model=list[ProviderView])
async def get_providers() -> list[ProviderView]:
    merged = admin_config.load_all()
    order = [p for p in list_providers() if p != "mock"]
    return [_mask(merged[p], p) for p in order if p in merged]


@router.put("/providers/{provider}", response_model=ProviderView)
async def update_provider(provider: str, body: ProviderUpdate) -> ProviderView:
    try:
        # Pull existing so a None api_key means "leave it alone" rather than wipe.
        existing = admin_config.get_provider(provider) or {}
        payload = {
            "api_key": body.api_key if body.api_key is not None else existing.get("api_key", ""),
            "base_url": body.base_url if body.base_url is not None else existing.get("base_url", ""),
            "models": body.models,
        }
        merged = admin_config.save_provider(provider, payload)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _mask(merged, provider)


@router.get("/models")
async def get_models() -> dict[str, list[str]]:
    """Map provider → admin-added model list. Used by the session creator."""
    return admin_config.list_models()
