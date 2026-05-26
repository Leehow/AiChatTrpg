"""Voice catalog lookup and live provider voice listing."""

from __future__ import annotations

import re
from typing import Any

import httpx

from services.media_generation_types import (
    MediaGenerationError,
    MediaModelRuntime,
    VoiceInfo,
    VoiceListResult,
)
from services.media_generation_utils import (
    DEFAULT_TIMEOUT_SECONDS,
    _bearer_headers,
    _http_error,
    _is_minimax_tts_model,
    _minimax_base,
    _normalize_provider,
    _versioned_base,
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


def catalog_tts_voices(
    provider: str | None,
    model: str | None = "",
    *,
    source: str = "catalog",
) -> list[VoiceInfo]:
    """Return the locally known voice catalog for a provider/model pair."""
    p = _normalize_provider(provider)
    model_text = model or ""
    if p in {"openai", "openai_compat", "debug"}:
        return _catalog_voice_infos(OPENAI_TTS_VOICES, source=source)
    if p == "grok":
        return _catalog_voice_infos(XAI_TTS_VOICES, source=source, meta=_XAI_TTS_VOICE_META)
    if p == "gemini":
        return _catalog_voice_infos(GEMINI_TTS_VOICES, source=source, meta=_GEMINI_TTS_VOICE_META)
    if p == "qwen":
        if _is_minimax_tts_model(model_text):
            return _catalog_voice_infos(MINIMAX_TTS_VOICES, source=source, meta=_MINIMAX_TTS_VOICE_META)
        return _catalog_voice_infos(DASHSCOPE_TTS_VOICES, source=source)
    if p == "minimax":
        return _catalog_voice_infos(MINIMAX_TTS_VOICES, source=source, meta=_MINIMAX_TTS_VOICE_META)
    if p == "mock":
        return [VoiceInfo(id="mock-voice", name="Mock Voice", source=source)]
    return []


async def list_tts_voices(
    runtime: MediaModelRuntime,
    *,
    live: bool = True,
) -> VoiceListResult:
    """List voices through provider APIs when available, else catalog fallback."""
    provider = _normalize_provider(runtime.provider)
    model = (runtime.model or "").strip()
    catalog = catalog_tts_voices(provider, model)

    if provider == "mock":
        return VoiceListResult(
            provider=provider,
            model=model or "mock-tts",
            voices=catalog,
            source="mock",
            live=False,
        )
    if not live:
        return VoiceListResult(provider=provider, model=model, voices=catalog)
    if provider in {"deepseek", "kimi", "claude", "doubao"}:
        return VoiceListResult(
            provider=provider,
            model=model,
            voices=[],
            source="unsupported",
            live=False,
            error=f"{provider} has no enabled native TTS voice catalog",
        )
    if provider == "qwen" and _is_minimax_tts_model(model):
        return VoiceListResult(
            provider=provider,
            model=model,
            voices=catalog_tts_voices(provider, model, source="catalog"),
            source="catalog",
            live=False,
            error="MiniMax speech bridge is configured under qwen; live MiniMax voice listing requires a MiniMax provider key.",
        )
    if provider not in {"grok", "minimax"}:
        return VoiceListResult(provider=provider, model=model, voices=catalog)
    if not runtime.api_key:
        return VoiceListResult(
            provider=provider,
            model=model,
            voices=catalog_tts_voices(provider, model, source="fallback"),
            source="fallback",
            live=False,
            error="api_key required for live voice listing",
        )

    try:
        if provider == "grok":
            voices = await _list_xai_voices(runtime)
        else:
            voices = await _list_minimax_voices(runtime)
        if voices:
            return VoiceListResult(
                provider=provider,
                model=model,
                voices=voices,
                source="live",
                live=True,
            )
        return VoiceListResult(
            provider=provider,
            model=model,
            voices=catalog_tts_voices(provider, model, source="fallback"),
            source="fallback",
            live=False,
            error="provider returned no voices",
        )
    except Exception as exc:
        return VoiceListResult(
            provider=provider,
            model=model,
            voices=catalog_tts_voices(provider, model, source="fallback"),
            source="fallback",
            live=False,
            error=str(exc),
        )


def _catalog_voice_infos(
    voice_ids: list[str],
    *,
    source: str,
    meta: dict[str, dict[str, Any]] | None = None,
) -> list[VoiceInfo]:
    seen: set[str] = set()
    voices: list[VoiceInfo] = []
    for voice_id in voice_ids:
        vid = str(voice_id or "").strip()
        if not vid or vid in seen:
            continue
        seen.add(vid)
        item = (meta or {}).get(vid, {})
        voices.append(
            VoiceInfo(
                id=vid,
                name=str(item.get("name") or vid),
                gender=str(item.get("gender") or ""),
                description=str(item.get("description") or ""),
                languages=[
                    str(lang) for lang in item.get("languages", [])
                    if str(lang).strip()
                ],
                source=source,
            )
        )
    return voices


async def _list_xai_voices(runtime: MediaModelRuntime) -> list[VoiceInfo]:
    endpoint = f"{_versioned_base(runtime.base_url or 'https://api.x.ai/v1')}/tts/voices"
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = await client.get(endpoint, headers=_bearer_headers(runtime.api_key))
        if response.status_code >= 400:
            raise MediaGenerationError(_http_error("voice listing", response))
        return _parse_voice_items(response.json(), source="live")


async def _list_minimax_voices(runtime: MediaModelRuntime) -> list[VoiceInfo]:
    endpoint = f"{_minimax_base(runtime.base_url)}/get_voice"
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = await client.post(
            endpoint,
            headers=_bearer_headers(runtime.api_key),
            json={"voice_type": "all"},
        )
        if response.status_code >= 400:
            raise MediaGenerationError(_http_error("voice listing", response))
        return _parse_voice_items(response.json(), source="live")


def _parse_voice_items(data: Any, *, source: str) -> list[VoiceInfo]:
    voices: list[VoiceInfo] = []
    for item in _walk_voice_items(data):
        voice = _coerce_voice_info(item, source=source)
        if voice:
            voices.append(voice)
    return _dedupe_voice_infos(voices)


def _walk_voice_items(value: Any):
    if isinstance(value, str):
        if value.strip():
            yield value
        return
    if isinstance(value, list):
        for child in value:
            yield from _walk_voice_items(child)
        return
    if not isinstance(value, dict):
        return

    if _voice_id_from_node(value):
        yield value
    for key in (
        "voices", "voice_list", "voiceList", "system_voice", "systemVoice",
        "voice_clone", "voiceClone", "voice_generation", "voiceGeneration",
        "custom_voice", "customVoice", "data", "items", "list",
    ):
        child = value.get(key)
        if child is not None:
            yield from _walk_voice_items(child)


def _coerce_voice_info(item: Any, *, source: str) -> VoiceInfo | None:
    if isinstance(item, str):
        voice_id = item.strip()
        return VoiceInfo(id=voice_id, name=voice_id, source=source) if voice_id else None
    if not isinstance(item, dict):
        return None

    voice_id = _voice_id_from_node(item)
    if not voice_id:
        return None
    name = _first_text(item, ("voice_name", "voiceName", "display_name", "displayName", "name", "label")) or voice_id
    description = _stringify_voice_description(
        item.get("description")
        or item.get("desc")
        or item.get("tone")
        or item.get("prompt")
    )
    gender = _first_text(item, ("gender", "sex", "speaker_gender", "speakerGender"))
    languages = _normalize_voice_languages(
        item.get("languages")
        or item.get("language")
        or item.get("supported_languages")
        or item.get("supportedLanguages")
        or item.get("locale")
    )
    return VoiceInfo(
        id=voice_id,
        name=name,
        gender=gender,
        description=description,
        languages=languages,
        source=source,
        raw=_compact_voice_raw(item),
    )


def _voice_id_from_node(item: dict[str, Any]) -> str:
    return _first_text(
        item,
        (
            "voice_id", "voiceId", "voiceID", "id", "voice",
            "voice_key", "voiceKey", "value", "key",
        ),
    )


def _first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        raw = item.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return ""


def _stringify_voice_description(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(part).strip() for part in value if str(part).strip())
    if isinstance(value, dict):
        return "; ".join(
            f"{key}: {val}" for key, val in value.items()
            if isinstance(val, (str, int, float, bool))
        )
    return str(value).strip()


def _normalize_voice_languages(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,;/|]", value) if part.strip()]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def _compact_voice_raw(item: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in item.items():
        if key.lower() in {"authorization", "api_key", "apikey", "token"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[key] = value
        elif isinstance(value, list) and all(isinstance(v, (str, int, float, bool)) for v in value[:20]):
            compact[key] = value[:20]
    return compact


def _dedupe_voice_infos(voices: list[VoiceInfo]) -> list[VoiceInfo]:
    seen: set[str] = set()
    deduped: list[VoiceInfo] = []
    for voice in voices:
        key = voice.id.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(voice)
    return deduped
