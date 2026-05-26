"""Unified media-generation HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from llm import list_providers
from orm.models import User
from routes.deps import current_user, db_session
from routes.llm_test import PROVIDER_DEFAULTS
from services import admin_config, model_pool
from services.media_generation import (
    MediaGenerationError,
    MediaModelRuntime,
    all_provider_media_capabilities,
    default_voice_for,
    generate_image,
    is_image_generation_model,
    is_tts_model,
    list_tts_voices,
    provider_media_capability,
    synthesize_speech,
)
from services.media_storage import (
    resolve_media_path,
    store_audio_reference,
    store_image_reference,
)

router = APIRouter(prefix="/api/media", tags=["media"])


class CapabilityView(BaseModel):
    provider: str
    image: bool = False
    tts: bool = False
    image_endpoint: str = ""
    tts_endpoint: str = ""
    image_models_hint: list[str] = Field(default_factory=list)
    tts_models_hint: list[str] = Field(default_factory=list)
    voices: list[str] = Field(default_factory=list)
    docs: list[str] = Field(default_factory=list)
    notes: str = ""


class PoolMediaEntry(BaseModel):
    provider: str
    model: str
    image: bool = False
    tts: bool = False
    default_voice: str = ""
    roles: list[str] = Field(default_factory=list)


class MediaCapabilitiesResponse(BaseModel):
    providers: list[CapabilityView] = Field(default_factory=list)
    pool: list[PoolMediaEntry] = Field(default_factory=list)


class MediaRuntimeRequest(BaseModel):
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""


class ImageGenerateRequest(MediaRuntimeRequest):
    prompt: str
    size: str = "1024x1024"
    n: int = Field(default=1, ge=1, le=9)


class SpeechGenerateRequest(MediaRuntimeRequest):
    text: str
    voice: str = ""
    audio_format: str = "mp3"
    instructions: str = ""
    language: str = "auto"


class VoiceListRequest(MediaRuntimeRequest):
    live: bool = True


class GeneratedImageView(BaseModel):
    data_uri: str = ""
    url: str = ""
    mime_type: str = "image/png"


class ImageGenerateResponse(BaseModel):
    provider: str
    model: str
    images: list[GeneratedImageView] = Field(default_factory=list)


class SpeechGenerateResponse(BaseModel):
    provider: str
    model: str
    audio_data_uri: str = ""
    audio_url: str = ""
    mime_type: str = "audio/mpeg"
    format: str = "mp3"
    usage: dict[str, Any] = Field(default_factory=dict)


class VoiceView(BaseModel):
    id: str
    name: str = ""
    gender: str = ""
    description: str = ""
    languages: list[str] = Field(default_factory=list)
    source: str = "catalog"
    raw: dict[str, Any] = Field(default_factory=dict)


class VoiceListResponse(BaseModel):
    provider: str
    model: str
    voices: list[VoiceView] = Field(default_factory=list)
    source: str = "catalog"
    live: bool = False
    error: str = ""


class NarrationVoiceSetting(BaseModel):
    provider: str = ""
    model: str = ""
    voice: str = ""


class MediaSettingsResponse(BaseModel):
    narration_voice: NarrationVoiceSetting | None = None


@router.get("/capabilities", response_model=MediaCapabilitiesResponse)
async def get_media_capabilities(
    db: AsyncSession = Depends(db_session),
) -> MediaCapabilitiesResponse:
    rows = await model_pool.list_entries(db)
    pool: list[PoolMediaEntry] = []
    for row in rows:
        roles = [
            role for role, flag in model_pool.ROLES.items()
            if bool(getattr(row, flag, False))
        ]
        pool.append(
            PoolMediaEntry(
                provider=row.provider,
                model=row.model,
                image=is_image_generation_model(row.provider, row.model),
                tts=is_tts_model(row.provider, row.model),
                default_voice=default_voice_for(row.provider, row.model),
                roles=roles,
            )
        )
    return MediaCapabilitiesResponse(
        providers=[
            CapabilityView(**cap.to_dict())
            for cap in all_provider_media_capabilities()
        ],
        pool=pool,
    )


@router.get("/capabilities/{provider}", response_model=CapabilityView)
async def get_provider_media_capability(
    provider: str,
    model: str = "",
) -> CapabilityView:
    if provider not in list_providers():
        raise HTTPException(status_code=400, detail=f"unknown provider '{provider}'")
    return CapabilityView(**provider_media_capability(provider, model).to_dict())


@router.get("/voices", response_model=VoiceListResponse)
async def get_media_voices(
    provider: str,
    model: str = "",
    live: bool = True,
    base_url: str = "",
    _: User = Depends(current_user),
) -> VoiceListResponse:
    runtime = _resolve_runtime(
        MediaRuntimeRequest(provider=provider, model=model, base_url=base_url)
    )
    return await _voice_list_response(runtime, live=live)


@router.post("/voices", response_model=VoiceListResponse)
async def list_media_voices(
    body: VoiceListRequest,
    _: User = Depends(current_user),
) -> VoiceListResponse:
    runtime = _resolve_runtime(body)
    return await _voice_list_response(runtime, live=body.live)


@router.get("/settings", response_model=MediaSettingsResponse)
async def get_media_settings(
    _: User = Depends(current_user),
) -> MediaSettingsResponse:
    return _media_settings_response(admin_config.get_media_settings())


@router.put("/settings", response_model=MediaSettingsResponse)
async def update_media_settings(
    body: MediaSettingsResponse,
    _: User = Depends(current_user),
) -> MediaSettingsResponse:
    return _media_settings_response(
        admin_config.save_media_settings(body.model_dump())
    )


@router.post("/image", response_model=ImageGenerateResponse)
async def generate_media_image(
    body: ImageGenerateRequest,
    _: User = Depends(current_user),
) -> ImageGenerateResponse:
    runtime = _resolve_runtime(body)
    try:
        result = await generate_image(
            runtime,
            body.prompt,
            size=body.size,
            n=body.n,
        )
    except MediaGenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    images: list[GeneratedImageView] = []
    for image in result.images:
        reference = image.data_uri or image.url
        try:
            stored_url = await store_image_reference(reference)
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        images.append(
            GeneratedImageView(
                data_uri="",
                url=stored_url or image.url,
                mime_type=image.mime_type,
            )
        )
    return ImageGenerateResponse(
        provider=result.provider,
        model=result.model,
        images=images,
    )


@router.post("/tts", response_model=SpeechGenerateResponse)
async def generate_media_tts(
    body: SpeechGenerateRequest,
    _: User = Depends(current_user),
) -> SpeechGenerateResponse:
    runtime = _resolve_runtime(body)
    voice = body.voice or _configured_narration_voice(runtime)
    try:
        result = await synthesize_speech(
            runtime,
            body.text,
            voice=voice,
            audio_format=body.audio_format,
            instructions=body.instructions,
            language=body.language,
        )
    except MediaGenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    reference = result.audio_data_uri or result.audio_url
    try:
        stored_url = await store_audio_reference(reference)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SpeechGenerateResponse(
        provider=result.provider,
        model=result.model,
        audio_data_uri="",
        audio_url=stored_url or result.audio_url,
        mime_type=result.mime_type,
        format=result.format,
        usage=result.usage,
    )


@router.get("/files/{filename}")
async def serve_media_file(filename: str) -> FileResponse:
    path = resolve_media_path(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="media file not found")
    return FileResponse(path)


def _resolve_runtime(body: MediaRuntimeRequest) -> MediaModelRuntime:
    provider = body.provider.strip()
    if provider not in list_providers():
        raise HTTPException(status_code=400, detail=f"unknown provider '{provider}'")
    if provider == "mock":
        return MediaModelRuntime(provider="mock", model=body.model or "mock")

    saved = admin_config.get_provider(provider) or {}
    defaults = PROVIDER_DEFAULTS.get(provider, {})
    api_key = (
        body.api_key.strip()
        or saved.get("api_key", "")
        or str(defaults.get("default_api_key", ""))
    )
    base_url = (
        body.base_url.strip()
        or saved.get("base_url", "")
        or str(defaults.get("base_url", ""))
    )
    return MediaModelRuntime(
        provider=provider,
        model=body.model.strip(),
        api_key=api_key,
        base_url=base_url,
    )


async def _voice_list_response(
    runtime: MediaModelRuntime,
    *,
    live: bool,
) -> VoiceListResponse:
    result = await list_tts_voices(runtime, live=live)
    return VoiceListResponse(
        provider=result.provider,
        model=result.model,
        voices=[VoiceView(**voice.to_dict()) for voice in result.voices],
        source=result.source,
        live=result.live,
        error=result.error,
    )


def _media_settings_response(settings: dict[str, Any]) -> MediaSettingsResponse:
    narration = settings.get("narration_voice")
    if not isinstance(narration, dict):
        return MediaSettingsResponse(narration_voice=None)
    return MediaSettingsResponse(
        narration_voice=NarrationVoiceSetting(
            provider=str(narration.get("provider") or ""),
            model=str(narration.get("model") or ""),
            voice=str(narration.get("voice") or ""),
        )
    )


def _configured_narration_voice(runtime: MediaModelRuntime) -> str:
    settings = admin_config.get_media_settings()
    narration = settings.get("narration_voice")
    if not isinstance(narration, dict):
        return ""
    if (
        str(narration.get("provider") or "").strip() == runtime.provider
        and str(narration.get("model") or "").strip() == runtime.model
    ):
        return str(narration.get("voice") or "").strip()
    return ""
