"""Audio synthesis, ffmpeg-based combination, and message-audio persistence.

The streaming flow in `services.trpg_tts` calls into these helpers to:
- split long-text segments before synthesis
- synthesize each segment via the media-generation adapter
- merge per-segment audio into a single MP3 for cached playback
- persist the combined URL onto the GM message
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import subprocess
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from orm.models import Message
from services.media_generation import MediaGenerationError, synthesize_speech
from services.media_storage import (
    resolve_media_path,
    store_audio_bytes,
    store_audio_reference,
)
from services.trpg_tts_segments import TtsSegment
from services.trpg_tts_text import _split_text

logger = logging.getLogger("chatrpg.trpg.tts.audio")

_GEMINI_TTS_MAX_CHARS = 1000
_OTHER_TTS_MAX_CHARS = 420
_AUDIO_SAMPLE_RATE = 24000
_SEGMENT_SILENCE_MS = 180


def _split_long_segments(segments: list[TtsSegment]) -> list[TtsSegment]:
    out: list[TtsSegment] = []
    for seg in segments:
        max_chars = _GEMINI_TTS_MAX_CHARS if _is_gemini_tts(seg.provider, seg.model) else _OTHER_TTS_MAX_CHARS
        parts = _split_text(seg.text, max_chars=max_chars)
        for part in parts:
            clone = TtsSegment(
                index=0,
                speaker=seg.speaker,
                text=part,
                emotion=seg.emotion,
                npc_key=seg.npc_key,
                voice=seg.voice,
                kind=seg.kind,
                model=seg.model,
                provider=seg.provider,
                performance_notes=seg.performance_notes,
            )
            out.append(clone)
    for idx, seg in enumerate(out, start=1):
        seg.index = idx
    return out


async def _synthesize_segment(
    seg: TtsSegment,
    narration_runtime,
    dialogue_runtime,
    user_id: str,
    message_id: str,
) -> dict[str, Any]:
    runtime = narration_runtime if seg.kind == "narrator" else dialogue_runtime
    result = None
    for attempt in range(3):
        try:
            result = await synthesize_speech(
                runtime.media_runtime(),
                seg.text,
                voice=seg.voice,
                audio_format="mp3" if _is_minimax_tts(runtime.model) else "wav",
                instructions=seg.performance_notes,
                language="auto",
            )
            break
        except MediaGenerationError as exc:
            if attempt >= 2 or "returned no audio" not in str(exc).lower():
                raise
            await asyncio.sleep(1.5 * (attempt + 1))
    if result is None:
        raise MediaGenerationError(f"{runtime.provider}:{runtime.model} returned no audio")
    reference = result.audio_data_uri or result.audio_url
    audio_url = await store_audio_reference(reference)
    return {
        "type": "tts_segment",
        "message_id": message_id,
        "segment": seg.index,
        "speaker": seg.speaker,
        "kind": seg.kind,
        "voice": seg.voice,
        "provider": runtime.provider,
        "model": runtime.model,
        "audio_url": audio_url or result.audio_url,
        "mime_type": result.mime_type,
        "format": result.format,
        "bytes_cached": bool(audio_url),
        "signature": _segment_signature(seg, user_id),
    }


def _public_tts_event(event: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in event.items() if not str(k).startswith("_")}


async def _persist_combined_message_audio(
    db: AsyncSession,
    message: Message,
    segment_events: list[dict[str, Any]],
    segments: list[TtsSegment],
    *,
    user_id: str,
) -> str:
    if not segment_events:
        return ""
    try:
        mp3_bytes = await asyncio.to_thread(_combine_segment_events_to_mp3, segment_events)
    except Exception:
        logger.warning("TRPG TTS final MP3 merge failed", exc_info=True)
        return ""
    if not mp3_bytes:
        return ""

    audio_url = store_audio_bytes(mp3_bytes, "audio/mpeg")
    if not audio_url:
        return ""

    metadata = dict(message.metadata_json or {})
    metadata["audio_url"] = audio_url
    metadata["trpg_audio_url"] = audio_url
    metadata["trpg_audio_expires_at"] = None
    metadata["tts_cache_expires_at"] = None
    metadata["trpg_tts_local"] = True
    metadata["trpg_tts_format"] = "mp3"
    metadata["trpg_tts_segment_count"] = len(segments)
    metadata["trpg_tts_signature"] = _message_tts_signature(segments, user_id)
    metadata["trpg_tts_segments"] = [
        {
            "segment": seg.index,
            "speaker": seg.speaker,
            "kind": seg.kind,
            "voice": seg.voice,
            "provider": seg.provider,
            "model": seg.model,
        }
        for seg in segments
    ]
    message.metadata_json = metadata
    flag_modified(message, "metadata_json")
    await db.commit()
    logger.info("TRPG TTS saved combined message audio: %s", audio_url)
    return audio_url


def _combine_segment_events_to_mp3(segment_events: list[dict[str, Any]]) -> bytes:
    ordered = sorted(segment_events, key=lambda item: int(item.get("segment") or 0))
    pcm_parts: list[bytes] = []
    silence = _make_pcm_silence(_SEGMENT_SILENCE_MS)
    for event in ordered:
        payload = _read_segment_audio_bytes(event)
        if not payload:
            return b""
        pcm = _decode_audio_to_pcm(payload)
        if not pcm:
            return b""
        if pcm_parts:
            pcm_parts.append(silence)
        pcm_parts.append(pcm)
    return _encode_pcm_to_mp3(b"".join(pcm_parts))


def _read_segment_audio_bytes(event: dict[str, Any]) -> bytes:
    url = str(event.get("audio_url") or "")
    if not url.startswith("/api/media/files/"):
        return b""
    filename = url.rsplit("/", 1)[-1]
    path = resolve_media_path(filename)
    if path is None:
        return b""
    return path.read_bytes()


def _make_pcm_silence(ms: int) -> bytes:
    return b"\x00\x00" * (_AUDIO_SAMPLE_RATE * ms // 1000)


def _decode_audio_to_pcm(payload: bytes) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            str(_AUDIO_SAMPLE_RATE),
            "pipe:1",
        ],
        input=payload,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        logger.warning("TRPG TTS audio decode failed: %s", result.stderr[:240])
        return b""
    return result.stdout or b""


def _encode_pcm_to_mp3(pcm: bytes) -> bytes:
    if not pcm:
        return b""
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            str(_AUDIO_SAMPLE_RATE),
            "-i",
            "pipe:0",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "128k",
            "-f",
            "mp3",
            "pipe:1",
        ],
        input=pcm,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        logger.warning("TRPG TTS MP3 encode failed: %s", result.stderr[:240])
        return b""
    return result.stdout or b""


def _is_gemini_tts(provider: str, model: str) -> bool:
    return provider == "gemini" or ("gemini" in (model or "").lower() and "tts" in (model or "").lower())


def _is_minimax_tts(model: str) -> bool:
    model_l = (model or "").lower()
    return "minimax" in model_l or "speech-2" in model_l


def _segment_signature(seg: TtsSegment, user_id: str) -> str:
    raw = "|".join([user_id, seg.provider, seg.model, seg.voice, seg.speaker, seg.text])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _message_tts_signature(segments: list[TtsSegment], user_id: str) -> str:
    raw = "|".join(_segment_signature(seg, user_id) for seg in segments)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
