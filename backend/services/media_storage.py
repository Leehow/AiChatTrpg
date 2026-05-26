"""Persisted media storage for generated portraits and TTS audio.

The provider adapters in ``media_generation`` return either a remote URL or
a base64 data URI. Embedding base64 blobs in JSON columns inflates rows by
~30% and turns simple session reads into multi-megabyte payloads, so any
generated asset that ChatRPG wants to keep is materialised to disk here
and the database stores the relative URL only.

Files live under ``data/media/`` (image PNG/JPEG, audio MP3/WAV) and are
served by the route registered in :mod:`routes.media` at
``/api/media/files/{filename}``.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
from pathlib import Path
from typing import Iterable

import httpx

from core.config import BACKEND_DIR

logger = logging.getLogger("chatrpg.media_storage")


MEDIA_DIR = BACKEND_DIR / "data" / "media"
MEDIA_URL_PREFIX = "/api/media/files"

_ALLOWED_IMAGE_MIMES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}
_ALLOWED_AUDIO_MIMES = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/opus": "opus",
    "audio/ogg": "ogg",
    "audio/aac": "aac",
    "audio/flac": "flac",
}

_DATA_URI_RE = re.compile(r"^data:([^;]+);base64,(.*)$", re.S)
_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def media_root() -> Path:
    """Absolute on-disk root for stored media. Created on first call."""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return MEDIA_DIR


def resolve_media_path(filename: str) -> Path | None:
    """Map an external filename back to its on-disk path.

    Rejects anything that doesn't look like a hash-style filename to avoid
    path traversal. Returns ``None`` when the file is missing or unsafe.
    """
    if not filename or not _FILENAME_RE.match(filename):
        return None
    candidate = (media_root() / filename).resolve()
    try:
        candidate.relative_to(media_root().resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


async def store_image_reference(
    reference: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Persist an image data URI or http URL and return ``/api/media/files/...``.

    Already-served URLs (anything starting with ``MEDIA_URL_PREFIX``) are
    returned as-is so this function is idempotent.
    """
    return await _store_reference(
        reference,
        allowed=_ALLOWED_IMAGE_MIMES,
        default_mime="image/png",
        client=client,
    )


async def store_audio_reference(
    reference: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Persist an audio data URI or http URL and return its serving URL."""
    return await _store_reference(
        reference,
        allowed=_ALLOWED_AUDIO_MIMES,
        default_mime="audio/mpeg",
        client=client,
    )


def store_image_bytes(payload: bytes, mime_type: str = "image/png") -> str:
    return _store_bytes(payload, mime_type or "image/png", _ALLOWED_IMAGE_MIMES, "image/png")


def store_audio_bytes(payload: bytes, mime_type: str = "audio/mpeg") -> str:
    return _store_bytes(payload, mime_type or "audio/mpeg", _ALLOWED_AUDIO_MIMES, "audio/mpeg")


async def _store_reference(
    reference: str,
    *,
    allowed: dict[str, str],
    default_mime: str,
    client: httpx.AsyncClient | None,
) -> str:
    raw = (reference or "").strip()
    if not raw:
        return ""
    if raw.startswith(MEDIA_URL_PREFIX):
        return raw

    if raw.startswith("data:"):
        match = _DATA_URI_RE.match(re.sub(r"\s+", "", raw))
        if not match:
            raise ValueError("invalid data URI")
        mime = match.group(1).strip().lower() or default_mime
        try:
            payload = base64.b64decode(match.group(2), validate=False)
        except Exception as exc:
            raise ValueError(f"invalid base64 payload: {exc}") from exc
        return _store_bytes(payload, mime, allowed, default_mime)

    if raw.startswith(("http://", "https://")):
        owns_client = client is None
        client = client or httpx.AsyncClient(timeout=60.0, follow_redirects=True)
        try:
            response = await client.get(raw)
            response.raise_for_status()
            mime = (
                response.headers.get("content-type", default_mime)
                .split(";")[0]
                .strip()
                .lower()
                or default_mime
            )
            return _store_bytes(response.content, mime, allowed, default_mime)
        finally:
            if owns_client:
                await client.aclose()

    # Bare base64 (no data: prefix) — assume default mime.
    try:
        payload = base64.b64decode(re.sub(r"\s+", "", raw), validate=True)
    except Exception as exc:
        raise ValueError(f"unrecognised media reference: {exc}") from exc
    return _store_bytes(payload, default_mime, allowed, default_mime)


def _store_bytes(
    payload: bytes,
    mime_type: str,
    allowed: dict[str, str],
    default_mime: str,
) -> str:
    if not payload:
        return ""
    mime = (mime_type or default_mime).strip().lower()
    extension = allowed.get(mime) or allowed.get(default_mime, "bin")
    digest = hashlib.sha256(payload).hexdigest()[:24]
    filename = f"{digest}.{extension}"
    target = media_root() / filename
    if not target.exists():
        target.write_bytes(payload)
    return f"{MEDIA_URL_PREFIX}/{filename}"


def is_managed_media_url(value: str) -> bool:
    return bool(value) and value.startswith(MEDIA_URL_PREFIX)


def list_filenames() -> Iterable[str]:
    root = media_root()
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_file())
