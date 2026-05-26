"""Provider response decoders for images and audio.

Walks heterogeneous JSON shapes returned by image and TTS providers and
normalizes them into the `GeneratedImage` / `SpeechSynthesisResult` types.
Also hosts `extract_image_url`, which the rest of the system uses to pull a
single image reference out of free-form GM text.
"""

from __future__ import annotations

import base64
import re
from typing import Any

import httpx

from services.media_generation_types import (
    GeneratedImage,
    MediaGenerationError,
    SpeechSynthesisResult,
)
from services.media_generation_utils import (
    _audio_data_uri,
    _data_uri,
    _deep_get,
    _ensure_image_data_uri,
    _extract_usage,
    _format_from_mime,
    _image_mime_from_node,
    _looks_like_raw_pcm,
    _mime_from_data_uri,
    _sample_rate_from_mime,
    _wrap_pcm_as_wav,
)


_IMAGE_DATA_RE = re.compile(
    r"data:image/(?:png|jpe?g|webp);base64,[A-Za-z0-9+/=\s]+",
    re.I,
)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\(([^)]+)\)")
_URL_RE = re.compile(r"https?://[^\s)\"']+")


async def _extract_images_from_response(
    data: Any,
    client: httpx.AsyncClient,
) -> list[GeneratedImage]:
    images: list[GeneratedImage] = []

    for b64, mime in _walk_image_b64(data):
        data_uri = _ensure_image_data_uri(b64, mime)
        if data_uri:
            images.append(GeneratedImage(data_uri=data_uri, mime_type=mime or "image/png"))
    for url in _walk_image_urls(data):
        normalized = await _normalize_image_reference(url, client)
        if normalized.startswith("data:image/"):
            images.append(GeneratedImage(data_uri=normalized, mime_type=_mime_from_data_uri(normalized, "image/png")))
        elif normalized:
            images.append(GeneratedImage(url=normalized))

    if not images and isinstance(data, str):
        normalized = await _normalize_image_reference(data, client)
        if normalized.startswith("data:image/"):
            images.append(GeneratedImage(data_uri=normalized, mime_type=_mime_from_data_uri(normalized, "image/png")))
        elif normalized:
            images.append(GeneratedImage(url=normalized))

    seen: set[str] = set()
    deduped: list[GeneratedImage] = []
    for image in images:
        ref = image.reference
        if ref and ref not in seen:
            seen.add(ref)
            deduped.append(image)
    return deduped


async def _extract_speech_from_response(
    *,
    provider: str,
    model: str,
    response: httpx.Response,
    client: httpx.AsyncClient,
    fallback_mime: str,
    fallback_format: str,
) -> SpeechSynthesisResult:
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type.startswith("audio/"):
        return SpeechSynthesisResult(
            provider=provider,
            model=model,
            audio_data_uri=_audio_data_uri(response.content, content_type),
            mime_type=content_type,
            format=_format_from_mime(content_type, fallback_format),
        )

    data = response.json()
    audio = _extract_audio_payload(data, fallback_mime=fallback_mime)
    if audio.get("url"):
        url = str(audio["url"])
        downloaded = await _download_audio_as_data_uri(url, client)
        return SpeechSynthesisResult(
            provider=provider,
            model=model,
            audio_data_uri=downloaded,
            audio_url=url,
            mime_type=_mime_from_data_uri(downloaded, fallback_mime) if downloaded else fallback_mime,
            format=fallback_format,
            usage=_extract_usage(data),
        )
    audio_bytes = audio.get("bytes") or b""
    mime = str(audio.get("mime") or fallback_mime)
    if audio_bytes:
        return SpeechSynthesisResult(
            provider=provider,
            model=model,
            audio_data_uri=_audio_data_uri(audio_bytes, mime),
            mime_type=mime,
            format=_format_from_mime(mime, fallback_format),
            usage=_extract_usage(data),
        )
    raise MediaGenerationError(f"{provider}:{model} returned no audio")


def _extract_audio_payload(data: Any, *, fallback_mime: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}

    minimax = _extract_minimax_audio_bytes(data)
    if minimax:
        return {"bytes": minimax, "mime": "audio/mpeg"}

    for inline in _walk_inline_data(data):
        raw = inline.get("data")
        if not raw:
            continue
        try:
            payload = base64.b64decode(str(raw))
        except Exception:
            continue
        mime = inline.get("mimeType") or inline.get("mime_type") or fallback_mime
        if _looks_like_raw_pcm(mime):
            sample_rate = _sample_rate_from_mime(mime, 24000)
            payload = _wrap_pcm_as_wav(payload, sample_rate=sample_rate)
            mime = "audio/wav"
        return {"bytes": payload, "mime": mime}

    audio = _deep_get(data, ("output", "audio"))
    if isinstance(audio, dict):
        if audio.get("url"):
            return {"url": audio["url"]}
        if audio.get("data"):
            try:
                return {"bytes": base64.b64decode(str(audio["data"])), "mime": fallback_mime}
            except Exception:
                return {}

    message_audio = _deep_get(data, ("choices", 0, "message", "audio"))
    if isinstance(message_audio, dict) and message_audio.get("data"):
        try:
            pcm = base64.b64decode(str(message_audio["data"]))
            return {"bytes": _wrap_pcm_as_wav(pcm, sample_rate=44100), "mime": "audio/wav"}
        except Exception:
            return {}
    return {}


def _walk_image_b64(value: Any) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key in ("b64_json", "base64", "image_base64", "bytesBase64Encoded", "imageBytes"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                found.append((raw.strip(), _image_mime_from_node(value)))
        image = value.get("image")
        if isinstance(image, str) and image.strip() and not image.startswith(("http://", "https://")):
            found.append((image.strip(), _image_mime_from_node(value)))
        images = value.get("image_base64")
        if isinstance(images, list):
            for item in images:
                if isinstance(item, str) and item.strip():
                    found.append((item.strip(), _image_mime_from_node(value)))
        for child in value.values():
            found.extend(_walk_image_b64(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_image_b64(child))
    return found


def _walk_image_urls(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key in ("url", "image_url", "image"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip().startswith(("http://", "https://", "data:image/")):
                found.append(raw.strip())
            elif isinstance(raw, dict):
                nested = raw.get("url")
                if isinstance(nested, str) and nested.strip():
                    found.append(nested.strip())
        image_urls = value.get("image_urls")
        if isinstance(image_urls, list):
            for item in image_urls:
                if isinstance(item, str) and item.strip():
                    found.append(item.strip())
        for child in value.values():
            found.extend(_walk_image_urls(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_image_urls(child))
    return found


def _walk_inline_data(value: Any):
    if isinstance(value, dict):
        inline = value.get("inlineData") or value.get("inline_data")
        if isinstance(inline, dict) and inline.get("data"):
            yield inline
        for child in value.values():
            yield from _walk_inline_data(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_inline_data(child)


async def _normalize_image_reference(value: str, client: httpx.AsyncClient) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    extracted = extract_image_url(raw)
    if extracted:
        raw = extracted
    if raw.startswith("data:image/"):
        return re.sub(r"\s+", "", raw)
    if raw.startswith(("http://", "https://")):
        return await _download_image_as_data_uri(raw, client)
    try:
        return _ensure_image_data_uri(raw, "image/png")
    except Exception:
        return ""


def extract_image_url(text: str) -> str:
    match = _IMAGE_DATA_RE.search(text or "")
    if match:
        return re.sub(r"\s+", "", match.group(0))
    md = _MARKDOWN_IMAGE_RE.search(text or "")
    if md:
        value = md.group(1).strip()
        if value.startswith("data:image/"):
            return re.sub(r"\s+", "", value)
        if value.startswith(("http://", "https://")):
            return value
    url = _URL_RE.search(text or "")
    return url.group(0) if url else ""


async def _download_image_as_data_uri(url: str, client: httpx.AsyncClient) -> str:
    response = await client.get(url)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "image/png").split(";")[0].strip()
    if not content_type.startswith("image/"):
        content_type = "image/png"
    return _data_uri(response.content, content_type)


async def _download_audio_as_data_uri(url: str, client: httpx.AsyncClient) -> str:
    response = await client.get(url)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "audio/mpeg").split(";")[0].strip()
    if not content_type.startswith("audio/"):
        content_type = "audio/mpeg"
    return _data_uri(response.content, content_type)


def _extract_minimax_audio_bytes(data: dict[str, Any]) -> bytes | None:
    root = data.get("output") if isinstance(data.get("output"), dict) else data
    candidate = _deep_get(root, ("data", "audio"))
    if not candidate:
        return None
    try:
        return bytes.fromhex(str(candidate))
    except ValueError:
        return None
