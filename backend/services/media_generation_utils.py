"""Generic helpers shared by the media generation modules.

Holds endpoint/URL builders, size/MIME conversions, WAV/PCM packaging, deep-get
and HTTP error formatting. Kept dependency-free except for the small set of
types and defaults it pulls from `media_generation_types`.
"""

from __future__ import annotations

import base64
import re
import struct
from typing import Any
from urllib.parse import urlsplit

import httpx

from services.media_generation_types import (
    DEFAULT_AUDIO_FORMAT,
    DEFAULT_IMAGE_SIZE,
    MediaGenerationError,
)


DEFAULT_TIMEOUT_SECONDS = 180.0
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DASHSCOPE_MULTIMODAL_PATH = "/api/v1/services/aigc/multimodal-generation/generation"
MINIMAX_BASE_URL = "https://api.minimax.io/v1"


def _normalize_provider(provider: str | None) -> str:
    return (provider or "").strip().lower()


def _is_minimax_tts_model(model: str) -> bool:
    m = (model or "").lower()
    return "speech-2" in m or "minimax" in m


def _docs_for_text_only_provider(provider: str) -> list[str]:
    if provider == "deepseek":
        return ["https://api-docs.deepseek.com/quick_start/pricing/"]
    if provider == "kimi":
        return ["https://platform.moonshot.cn/docs/introduction"]
    if provider == "claude":
        return ["https://docs.anthropic.com/en/docs/models-overview"]
    return []


def _bearer_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _versioned_base(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise MediaGenerationError("base_url is required")
    if re.search(r"/v\d(?:beta)?$", base):
        return base
    return f"{base}/v1"


def _gemini_base(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/") or GEMINI_BASE_URL
    if ":generateContent" in base or ":predict" in base:
        return base.rsplit("/models/", 1)[0] if "/models/" in base else GEMINI_BASE_URL
    if base.endswith("/v1"):
        base = base[:-3] + "/v1beta"
    elif "generativelanguage.googleapis.com" in base and not base.endswith("/v1beta"):
        base = f"{base}/v1beta"
    return base


def _dashscope_multimodal_endpoint(base_url: str) -> str:
    candidate = (base_url or "").strip().rstrip("/")
    if not candidate:
        return f"https://dashscope.aliyuncs.com{DASHSCOPE_MULTIMODAL_PATH}"
    lowered = candidate.lower()
    if DASHSCOPE_MULTIMODAL_PATH in lowered:
        return candidate
    parsed = urlsplit(candidate)
    if parsed.scheme and parsed.netloc:
        host = f"{parsed.scheme}://{parsed.netloc}"
        return f"{host}{DASHSCOPE_MULTIMODAL_PATH}"
    return f"{candidate}{DASHSCOPE_MULTIMODAL_PATH}"


def _minimax_base(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base or "minimax.chat" in base:
        return MINIMAX_BASE_URL
    if not re.search(r"/v\d$", base):
        return f"{base}/v1"
    return base


def _aspect_ratio_from_size(size: str) -> str:
    raw = (size or DEFAULT_IMAGE_SIZE).lower().replace("x", "*").replace(" ", "")
    try:
        width_text, height_text = raw.split("*", 1)
        width = max(1, int(float(width_text)))
        height = max(1, int(float(height_text)))
    except Exception:
        return "1:1"
    if width == height:
        return "1:1"
    ratio = width / height
    candidates = {
        "16:9": 16 / 9,
        "9:16": 9 / 16,
        "4:3": 4 / 3,
        "3:4": 3 / 4,
        "3:2": 3 / 2,
        "2:3": 2 / 3,
        "21:9": 21 / 9,
    }
    return min(candidates, key=lambda key: abs(candidates[key] - ratio))


def _pixel_dimensions(size: str) -> tuple[int, int] | None:
    raw = (size or "").lower().replace("x", "*").replace(" ", "")
    try:
        width_text, height_text = raw.split("*", 1)
        width = int(float(width_text))
        height = int(float(height_text))
    except Exception:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _dashscope_size(size: str) -> str:
    return (size or "1024x1024").lower().replace("x", "*")


def _doubao_size(size: str) -> str:
    raw = (size or DEFAULT_IMAGE_SIZE).lower()
    if raw in {"1k", "2k", "4k", "adaptive"}:
        return raw.upper() if raw.endswith("k") else raw
    return raw


def _ensure_image_data_uri(value: str, mime_type: str = "image/png") -> str:
    raw = re.sub(r"\s+", "", value or "")
    if not raw:
        return ""
    if raw.startswith("data:image/"):
        return raw
    base64.b64decode(raw, validate=True)
    return f"data:{mime_type or 'image/png'};base64,{raw}"


def _image_mime_from_node(value: dict[str, Any]) -> str:
    for key in ("mimeType", "mime_type", "mediaType", "content_type"):
        raw = value.get(key)
        if isinstance(raw, str) and raw.startswith("image/"):
            return raw
    return "image/png"


def _audio_data_uri(audio_bytes: bytes, mime_type: str) -> str:
    return _data_uri(audio_bytes, mime_type or "audio/mpeg")


def _data_uri(payload: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _audio_mime_type(fmt: str) -> str:
    normalized = (fmt or DEFAULT_AUDIO_FORMAT).lower().lstrip(".")
    return {
        "mp3": "audio/mpeg",
        "mpeg": "audio/mpeg",
        "wav": "audio/wav",
        "pcm": "audio/pcm",
        "opus": "audio/opus",
        "aac": "audio/aac",
        "flac": "audio/flac",
        "mulaw": "audio/basic",
        "alaw": "audio/alaw",
    }.get(normalized, "audio/mpeg")


def _format_from_mime(mime_type: str, fallback: str) -> str:
    return {
        "audio/mpeg": "mp3",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/pcm": "pcm",
        "audio/opus": "opus",
        "audio/aac": "aac",
        "audio/flac": "flac",
        "audio/basic": "mulaw",
    }.get((mime_type or "").lower(), fallback or DEFAULT_AUDIO_FORMAT)


def _mime_from_data_uri(data_uri: str, fallback: str) -> str:
    match = re.match(r"data:([^;]+);base64,", data_uri or "")
    return match.group(1) if match else fallback


def _wrap_pcm_as_wav(pcm: bytes, sample_rate: int = 24000, channels: int = 1) -> bytes:
    byte_rate = sample_rate * channels * 2
    block_align = channels * 2
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        16,
        b"data",
        len(pcm),
    )
    return header + pcm


def _looks_like_raw_pcm(mime_type: str) -> bool:
    mime = (mime_type or "").lower()
    return not mime or "pcm" in mime or "l16" in mime or "rate=" in mime


def _sample_rate_from_mime(mime_type: str, default: int) -> int:
    match = re.search(r"rate=(\d+)", mime_type or "")
    if match:
        return int(match.group(1))
    return default


def _extract_usage(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    usage = data.get("usage") or data.get("usageMetadata") or {}
    return usage if isinstance(usage, dict) else {}


def _deep_get(value: Any, path: tuple[Any, ...]) -> Any:
    current = value
    for part in path:
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                return None
            current = current[part]
        else:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
    return current


def _http_error(action: str, response: httpx.Response) -> str:
    body = (response.text or "").strip()
    if len(body) > 500:
        body = body[:500]
    return f"{action} failed with HTTP {response.status_code}: {body}"
