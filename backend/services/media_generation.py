"""Unified image and speech generation adapters.

AiChatTrpg keeps chat models behind one LLM interface, but image generation and
TTS are not truly OpenAI-compatible across providers. This module is the
provider-aware media layer that higher-level TRPG features should call.

Implementation is split across companion modules; this file is the public
facade. Public callers and tests import from ``services.media_generation``
exclusively, so existing names (and a handful of underscore-prefixed helpers
exercised by debug tests) are re-exported here.
"""

from __future__ import annotations

import httpx

from services.media_generation_extract import (
    _IMAGE_DATA_RE,
    _MARKDOWN_IMAGE_RE,
    _URL_RE,
    _download_audio_as_data_uri,
    _download_image_as_data_uri,
    _extract_audio_payload,
    _extract_images_from_response,
    _extract_minimax_audio_bytes,
    _extract_speech_from_response,
    _normalize_image_reference,
    _walk_image_b64,
    _walk_image_urls,
    _walk_inline_data,
    extract_image_url,
)
from services.media_generation_payloads import (
    _dashscope_image_payload,
    _dashscope_minimax_tts_payload,
    _dashscope_tts_payload,
    _doubao_image_payload,
    _gemini_image_payload,
    _gemini_tts_payload,
    _glm_voice_payload,
    _image_request,
    _minimax_image_payload,
    _minimax_tts_payload,
    _openai_image_payload,
    _openai_tts_payload,
    _speech_request,
    _xai_image_payload,
    _xai_tts_payload,
)
from services.media_generation_providers import (
    _provider_image_supported,
    _provider_tts_supported,
    _tts_voices_for,
    all_provider_media_capabilities,
    avatar_image_size_for,
    default_voice_for,
    is_image_generation_model,
    is_tts_model,
    provider_media_capability,
)
from services.media_generation_types import (
    DEFAULT_AUDIO_FORMAT,
    DEFAULT_AVATAR_IMAGE_SIZE,
    DEFAULT_IMAGE_SIZE,
    GeneratedImage,
    ImageGenerationResult,
    MediaGenerationError,
    MediaModelRuntime,
    ProviderMediaCapability,
    SpeechSynthesisResult,
    UnsupportedMediaCapability,
    VoiceInfo,
    VoiceListResult,
)
from services.media_generation_utils import (
    DASHSCOPE_MULTIMODAL_PATH,
    DEFAULT_TIMEOUT_SECONDS,
    GEMINI_BASE_URL,
    MINIMAX_BASE_URL,
    _aspect_ratio_from_size,
    _audio_data_uri,
    _audio_mime_type,
    _bearer_headers,
    _dashscope_multimodal_endpoint,
    _dashscope_size,
    _data_uri,
    _deep_get,
    _docs_for_text_only_provider,
    _doubao_size,
    _ensure_image_data_uri,
    _extract_usage,
    _format_from_mime,
    _gemini_base,
    _http_error,
    _image_mime_from_node,
    _is_minimax_tts_model,
    _looks_like_raw_pcm,
    _mime_from_data_uri,
    _minimax_base,
    _normalize_provider,
    _pixel_dimensions,
    _sample_rate_from_mime,
    _versioned_base,
    _wrap_pcm_as_wav,
)
from services.media_generation_voice_data import (
    DASHSCOPE_TTS_VOICES,
    GEMINI_TTS_VOICES,
    MINIMAX_TTS_VOICES,
    OPENAI_TTS_VOICES,
    XAI_TTS_VOICES,
    _GEMINI_TTS_VOICE_META,
    _MINIMAX_TTS_VOICE_META,
    _XAI_TTS_VOICE_META,
)
from services.media_generation_voices import (
    _catalog_voice_infos,
    _coerce_voice_info,
    _compact_voice_raw,
    _dedupe_voice_infos,
    _first_text,
    _list_minimax_voices,
    _list_xai_voices,
    _normalize_voice_languages,
    _parse_voice_items,
    _stringify_voice_description,
    _voice_id_from_node,
    _walk_voice_items,
    catalog_tts_voices,
    list_tts_voices,
)


MOCK_PNG_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


async def generate_image(
    runtime: MediaModelRuntime,
    prompt: str,
    *,
    size: str = DEFAULT_IMAGE_SIZE,
    n: int = 1,
    response_format: str = "b64_json",
) -> ImageGenerationResult:
    provider = _normalize_provider(runtime.provider)
    model = (runtime.model or "").strip()
    if not prompt.strip():
        raise MediaGenerationError("image prompt is required")
    if provider == "mock":
        return ImageGenerationResult(
            provider=provider,
            model=model or "mock-image",
            images=[GeneratedImage(data_uri=MOCK_PNG_DATA_URI)],
            raw_provider=provider,
        )
    if not is_image_generation_model(provider, model):
        raise UnsupportedMediaCapability(f"{provider}:{model} is not an image generation model")
    if not runtime.api_key:
        raise MediaGenerationError(f"{provider}:{model} has no API key configured")

    endpoint, payload = _image_request(
        endpoint_provider=provider,
        runtime=runtime,
        prompt=prompt,
        size=size,
        n=n,
        response_format=response_format,
    )
    headers = _bearer_headers(runtime.api_key)
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = await client.post(endpoint, headers=headers, json=payload)
        if response.status_code >= 400:
            raise MediaGenerationError(_http_error("image generation", response))
        images = await _extract_images_from_response(response.json(), client)
    if not images:
        raise MediaGenerationError(f"{provider}:{model} returned no image")
    return ImageGenerationResult(provider=provider, model=model, images=images, raw_provider=provider)


async def synthesize_speech(
    runtime: MediaModelRuntime,
    text: str,
    *,
    voice: str = "",
    audio_format: str = DEFAULT_AUDIO_FORMAT,
    instructions: str = "",
    language: str = "auto",
) -> SpeechSynthesisResult:
    provider = _normalize_provider(runtime.provider)
    model = (runtime.model or "").strip()
    text = text.strip()
    if not text:
        raise MediaGenerationError("speech text is required")
    if provider == "mock":
        return SpeechSynthesisResult(provider=provider, model=model or "mock-tts")
    if not is_tts_model(provider, model):
        raise UnsupportedMediaCapability(f"{provider}:{model} is not a TTS model")
    if not runtime.api_key:
        raise MediaGenerationError(f"{provider}:{model} has no API key configured")

    endpoint, payload, response_mime = _speech_request(
        endpoint_provider=provider,
        runtime=runtime,
        text=text,
        voice=voice or default_voice_for(provider, model),
        audio_format=audio_format,
        instructions=instructions,
        language=language,
    )
    headers = _bearer_headers(runtime.api_key)
    if provider == "gemini":
        headers = {"x-goog-api-key": runtime.api_key, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = await client.post(endpoint, headers=headers, json=payload)
        if response.status_code >= 400:
            raise MediaGenerationError(_http_error("speech synthesis", response))
        return await _extract_speech_from_response(
            provider=provider,
            model=model,
            response=response,
            client=client,
            fallback_mime=response_mime,
            fallback_format=audio_format,
        )


__all__ = [
    "DASHSCOPE_MULTIMODAL_PATH",
    "DASHSCOPE_TTS_VOICES",
    "DEFAULT_AUDIO_FORMAT",
    "DEFAULT_AVATAR_IMAGE_SIZE",
    "DEFAULT_IMAGE_SIZE",
    "DEFAULT_TIMEOUT_SECONDS",
    "GEMINI_BASE_URL",
    "GEMINI_TTS_VOICES",
    "GeneratedImage",
    "ImageGenerationResult",
    "MINIMAX_BASE_URL",
    "MINIMAX_TTS_VOICES",
    "MOCK_PNG_DATA_URI",
    "MediaGenerationError",
    "MediaModelRuntime",
    "OPENAI_TTS_VOICES",
    "ProviderMediaCapability",
    "SpeechSynthesisResult",
    "UnsupportedMediaCapability",
    "VoiceInfo",
    "VoiceListResult",
    "XAI_TTS_VOICES",
    "all_provider_media_capabilities",
    "avatar_image_size_for",
    "catalog_tts_voices",
    "default_voice_for",
    "extract_image_url",
    "generate_image",
    "is_image_generation_model",
    "is_tts_model",
    "list_tts_voices",
    "provider_media_capability",
    "synthesize_speech",
]
