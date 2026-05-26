from fastapi import APIRouter, Depends

from core.config import Settings, get_settings
from llm import list_providers
from services import admin_config

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health(settings: Settings = Depends(get_settings)) -> dict:
    env_keyed = set(settings.configured_providers())
    admin_keyed = set(admin_config.configured_providers())
    configured = sorted(env_keyed | admin_keyed)
    return {
        "ok": True,
        "single_user_id": settings.single_user_id,
        "configured_providers": configured,
        "all_providers": list_providers(),
        "default_provider": settings.trpg_default_provider,
        "default_model": settings.trpg_default_model,
    }
