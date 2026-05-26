"""Provider capability discovery and provider/model classification.

Functions here decide whether a given (provider, model) pair supports image
generation or TTS, what the default voice should be, and the smallest valid
square avatar size. They depend only on shared types, voice catalogs, and
generic utility helpers.
"""

from __future__ import annotations

from llm import list_providers

from services.media_generation_types import (
    DEFAULT_AVATAR_IMAGE_SIZE,
    ProviderMediaCapability,
)
from services.media_generation_utils import (
    DASHSCOPE_MULTIMODAL_PATH,
    _docs_for_text_only_provider,
    _is_minimax_tts_model,
    _normalize_provider,
)
from services.media_generation_voice_data import (
    DASHSCOPE_TTS_VOICES,
    GEMINI_TTS_VOICES,
    MINIMAX_TTS_VOICES,
    OPENAI_TTS_VOICES,
    XAI_TTS_VOICES,
)


def provider_media_capability(provider: str, model: str = "") -> ProviderMediaCapability:
    p = _normalize_provider(provider)
    if p in {"openai", "openai_compat", "debug"}:
        return ProviderMediaCapability(
            provider=p,
            image=_provider_image_supported(p, model),
            tts=_provider_tts_supported(p, model),
            image_endpoint="/images/generations",
            tts_endpoint="/audio/speech",
            image_models_hint=["gpt-image-2", "gpt-image-1.5", "gpt-image-1", "dall-e-3"],
            tts_models_hint=["gpt-4o-mini-tts", "tts-1", "tts-1-hd"],
            voices=OPENAI_TTS_VOICES,
            docs=[
                "https://platform.openai.com/docs/guides/images/image-generation",
                "https://platform.openai.com/docs/guides/text-to-speech",
            ],
            notes="OpenAI-compatible media endpoints are only enabled for media-looking model IDs.",
        )
    if p == "grok":
        return ProviderMediaCapability(
            provider=p,
            image=_provider_image_supported(p, model),
            tts=_provider_tts_supported(p, model),
            image_endpoint="/images/generations",
            tts_endpoint="/tts",
            image_models_hint=["grok-imagine-image", "grok-imagine-image-pro"],
            tts_models_hint=["xai-tts"],
            voices=XAI_TTS_VOICES,
            docs=[
                "https://docs.x.ai/developers/model-capabilities/images/generation",
                "https://docs.x.ai/developers/model-capabilities/audio/text-to-speech",
            ],
        )
    if p == "gemini":
        return ProviderMediaCapability(
            provider=p,
            image=_provider_image_supported(p, model),
            tts=_provider_tts_supported(p, model),
            image_endpoint="/v1beta/models/{model}:predict",
            tts_endpoint="/v1beta/models/{model}:generateContent",
            image_models_hint=["imagen-4.0-generate-001"],
            tts_models_hint=["gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts"],
            voices=GEMINI_TTS_VOICES,
            docs=[
                "https://ai.google.dev/gemini-api/docs/imagen",
                "https://ai.google.dev/gemini-api/docs/speech-generation",
            ],
        )
    if p == "qwen":
        return ProviderMediaCapability(
            provider=p,
            image=_provider_image_supported(p, model),
            tts=_provider_tts_supported(p, model),
            image_endpoint=DASHSCOPE_MULTIMODAL_PATH,
            tts_endpoint=DASHSCOPE_MULTIMODAL_PATH,
            image_models_hint=["qwen-image-2.0-pro", "qwen-image-2.0", "qwen-image-max", "qwen-image-plus"],
            tts_models_hint=["qwen3-tts-flash", "qwen3-tts-instruct-flash", "qwen-tts", "MiniMax/speech-2.8-hd"],
            voices=_tts_voices_for(p, model, DASHSCOPE_TTS_VOICES),
            docs=[
                "https://help.aliyun.com/zh/model-studio/qwen-image-api",
                "https://help.aliyun.com/zh/model-studio/qwen-tts-api",
                "https://platform.minimax.io/docs/api-reference/speech-t2a-http",
            ],
            notes="Qwen models use DashScope Qwen-TTS; MiniMax speech-2 models are sent with MiniMax payload shape when this role is configured that way.",
        )
    if p == "minimax":
        return ProviderMediaCapability(
            provider=p,
            image=_provider_image_supported(p, model),
            tts=_provider_tts_supported(p, model),
            image_endpoint="/image_generation",
            tts_endpoint="/t2a_v2",
            image_models_hint=["image-01", "image-01-live"],
            tts_models_hint=["speech-2.8-hd", "speech-2.8-turbo"],
            voices=MINIMAX_TTS_VOICES,
            docs=[
                "https://platform.minimax.io/docs/api-reference/image-generation-t2i",
                "https://platform.minimax.io/docs/api-reference/speech-t2a-http",
            ],
        )
    if p == "glm":
        return ProviderMediaCapability(
            provider=p,
            image=_provider_image_supported(p, model),
            tts=_provider_tts_supported(p, model),
            image_endpoint="/images/generations",
            tts_endpoint="/chat/completions",
            image_models_hint=["glm-image"],
            tts_models_hint=["glm-4-voice"],
            docs=[
                "https://docs.bigmodel.cn/cn/guide/models/image-generation/glm-image",
                "https://docs.bigmodel.cn/cn/guide/models/sound-and-video/glm-4-voice",
            ],
            notes="GLM TTS is exposed by GLM-4-Voice chat completions, not a generic audio/speech endpoint.",
        )
    if p == "doubao":
        return ProviderMediaCapability(
            provider=p,
            image=_provider_image_supported(p, model),
            tts=False,
            image_endpoint="/images/generations",
            image_models_hint=["doubao-seedream-4-5", "doubao-seedream-4-0", "doubao-seedream-3-0-t2i"],
            docs=[
                "https://www.volcengine.com/docs/82379/1541523",
                "https://www.volcengine.com/docs/6561/1096680",
            ],
            notes=(
                "Ark image generation is OpenAI-style. Doubao speech uses Volcengine "
                "speech/realtime APIs with different credentials, so it is not enabled "
                "through the Ark chat provider yet."
            ),
        )
    if p in {"deepseek", "kimi", "claude"}:
        return ProviderMediaCapability(
            provider=p,
            image=False,
            tts=False,
            docs=_docs_for_text_only_provider(p),
            notes="Official provider API is text or vision-input oriented here; no native image output or TTS adapter is enabled.",
        )
    return ProviderMediaCapability(
        provider=p,
        image=False,
        tts=False,
        notes="Unknown or mock provider has no external media adapter.",
    )


def all_provider_media_capabilities() -> list[ProviderMediaCapability]:
    return [provider_media_capability(provider) for provider in list_providers()]


def is_image_generation_model(provider: str | None, model: str | None) -> bool:
    p = _normalize_provider(provider)
    m = (model or "").lower()
    if p == "mock":
        return True
    if p == "gemini":
        return "imagen" in m or "image" in m or "nano-banana" in m
    if p == "qwen":
        return any(token in m for token in ("qwen-image", "wanx", "wan2", "flux", "image"))
    if p == "minimax":
        return "image" in m or m in {"image-01", "image-01-live"}
    if p == "grok":
        return "imagine" in m or "image" in m
    if p == "glm":
        return "glm-image" in m or "image" in m
    if p == "doubao":
        return "seedream" in m or "seededit" in m or "image" in m or "jimeng" in m
    if p in {"deepseek", "kimi", "claude"}:
        return False
    return any(
        token in m
        for token in (
            "image", "imagine", "portrait", "draw", "gpt-image", "dall",
            "wanx", "flux", "sdxl", "stable", "seedream", "jimeng", "z-image",
        )
    )


def _provider_image_supported(provider: str, model: str | None) -> bool:
    if (model or "").strip():
        return is_image_generation_model(provider, model)
    return provider in {
        "openai",
        "openai_compat",
        "debug",
        "grok",
        "gemini",
        "qwen",
        "minimax",
        "glm",
        "doubao",
        "mock",
    }


def is_tts_model(provider: str | None, model: str | None) -> bool:
    p = _normalize_provider(provider)
    m = (model or "").lower()
    if p == "mock":
        return True
    if p == "gemini":
        return "tts" in m and "gemini" in m
    if p == "qwen":
        return "tts" in m or "cosyvoice" in m or "speech-2" in m or "minimax" in m
    if p == "minimax":
        return "speech-2" in m or "tts" in m or "t2a" in m
    if p == "grok":
        return "tts" in m or "voice" in m or not m
    if p == "glm":
        return "voice" in m
    if p in {"deepseek", "kimi", "claude", "doubao"}:
        return False
    return any(token in m for token in ("tts", "speech", "audio"))


def _provider_tts_supported(provider: str, model: str | None) -> bool:
    if (model or "").strip():
        return is_tts_model(provider, model)
    return provider in {
        "openai",
        "openai_compat",
        "debug",
        "grok",
        "gemini",
        "qwen",
        "minimax",
        "glm",
        "mock",
    }


def default_voice_for(provider: str | None, model: str | None = "") -> str:
    p = _normalize_provider(provider)
    voices = provider_media_capability(p, model or "").voices
    if voices:
        return voices[0]
    if p == "openai" or p == "openai_compat" or p == "debug":
        return "coral"
    return ""


def avatar_image_size_for(provider: str | None, model: str | None = "") -> str:
    """Return the smallest provider-valid square-ish size for avatar portraits."""
    p = _normalize_provider(provider)
    m = (model or "").strip().lower().replace("_", "-")

    if p == "mock":
        return "1x1"
    if p == "openai" and "gpt-image-2" in m:
        # gpt-image-2 accepts arbitrary sizes with >=655,360 total pixels,
        # edges as multiples of 16. 816 square is the smallest valid square.
        return "816x816"
    if p in {"openai", "openai_compat", "debug"}:
        if "dall-e-2" in m:
            return "256x256"
        return DEFAULT_AVATAR_IMAGE_SIZE
    if p == "gemini":
        return "1024x1024"  # Imagen imageSize=1K + aspectRatio=1:1.
    if p == "grok":
        return "1024x1024"  # xAI resolution=1k + aspectRatio=1:1.
    if p == "qwen":
        if "qwen-image-max" in m or "qwen-image-plus" in m:
            return "1328x1328"
        if "qwen-image-2" in m:
            return "512x512"
        return DEFAULT_AVATAR_IMAGE_SIZE
    if p == "minimax":
        return "512x512"
    if p == "glm":
        return "512x512"
    if p == "doubao":
        if "seedream-3" in m:
            return "512x512"
        if "seedream-4-5" in m or "seedream-4.5" in m:
            return "2K"
        if "seedream" in m:
            return "1K"
        return DEFAULT_AVATAR_IMAGE_SIZE
    return DEFAULT_AVATAR_IMAGE_SIZE


def _tts_voices_for(provider: str, model: str | None, fallback: list[str]) -> list[str]:
    if provider == "qwen" and _is_minimax_tts_model(model or ""):
        return MINIMAX_TTS_VOICES
    return fallback
