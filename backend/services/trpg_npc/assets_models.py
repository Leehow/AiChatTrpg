"""Model runtime resolution for NPC asset workflows.

Owns ``ModelRuntime``, the role→provider resolver that talks to
``admin_config`` + ``model_pool``, and the image-capability check used
to decide whether the configured avatar model can actually render a
portrait.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from services import admin_config, model_pool
from services.media_generation import is_image_generation_model


@dataclass
class ModelRuntime:
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""


async def _resolve_role_model(
    db: AsyncSession,
    role: str,
) -> ModelRuntime | None:
    getter = {
        "dialogue": model_pool.get_dialogue,
        "avatar": model_pool.get_avatar,
        "narration": model_pool.get_narration,
        "default": model_pool.get_default,
    }.get(role)
    if getter is None:
        return None
    entry = await getter(db)
    if entry is None:
        return None
    if entry.provider == "mock":
        return ModelRuntime(provider="mock", model=entry.model or "mock")
    saved = admin_config.get_provider(entry.provider) or {}
    return ModelRuntime(
        provider=entry.provider,
        model=entry.model,
        api_key=saved.get("api_key", "") or _provider_default_key(entry.provider),
        base_url=saved.get("base_url", "") or _provider_default_base_url(entry.provider),
    )


def _provider_default_key(provider: str) -> str:
    if provider == "debug":
        return "codex-relay-local"
    return ""


def _provider_default_base_url(provider: str) -> str:
    if provider == "debug":
        return "http://127.0.0.1:18888/v1"
    return ""


def _is_probable_image_model(model: str, provider: str | None = None) -> bool:
    return is_image_generation_model(provider or "", model)
