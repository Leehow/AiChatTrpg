"""TRPG message-level text-to-speech streaming.

The model-pool media layer knows how to call each provider. This module adds
the TRPG-specific layer above it: parse GM prose into narrator/dialogue
segments, resolve character voices from session memory, add hidden Gemini
performance notes, and emit synthesized segments as SSE-friendly events.

The bulk of the logic lives in sibling helper modules
(`trpg_tts_text`, `trpg_tts_segments`, `trpg_tts_voices`, `trpg_tts_audio`).
This module wires them together behind the long-standing public surface:
`TtsRuntime`, `TtsSegment`, `stream_message_tts_events`, and the
underscore-prefixed helpers consumed by tests and other routes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from llm import ChatMessage, build_client
from orm.models import GameSession, Message, ModelPoolEntry
from routes.llm_test import PROVIDER_DEFAULTS
from services import admin_config, model_pool
from services.media_generation import (
    MediaGenerationError,
    MediaModelRuntime,
    is_tts_model,
)
from services.trpg_tts_audio import (
    _combine_segment_events_to_mp3,
    _persist_combined_message_audio,
    _public_tts_event,
    _split_long_segments,
    _synthesize_segment,
)
from services.trpg_tts_segments import (
    TtsSegment,
    _needs_llm_speaker_parse,
    _parse_segments,
    _segment_public_payload,
    _segments_from_llm_payload,
    _speaker_parse_prompt,
    _speaker_parse_roster,
)
from services.trpg_tts_text import (
    _prepare_tts_source,
    _strip_json_fence,
)
from services.trpg_tts_voices import (
    _assign_segments,
    _attach_performance_notes,
)

logger = logging.getLogger("chatrpg.trpg.tts")

_SYNTH_CONCURRENCY = 3


@dataclass(frozen=True)
class TtsRuntime:
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""

    def media_runtime(self) -> MediaModelRuntime:
        return MediaModelRuntime(
            provider=self.provider,
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
        )


async def stream_message_tts_events(
    db: AsyncSession,
    session: GameSession,
    message: Message,
    *,
    user_id: str,
    request_text: str = "",
) -> AsyncIterator[dict[str, Any]]:
    """Yield event dictionaries for one GM message TTS playback."""
    if message.role != "gm":
        yield {"type": "error", "message": "Only GM messages can be read aloud"}
        return

    content = message.content or request_text or ""
    clean = _prepare_tts_source(content)
    if not clean.strip():
        yield {"type": "error", "message": "No speakable text in this message"}
        return

    dialogue_runtime = await _resolve_tts_runtime(db, "dialogue")
    narration_runtime = await _resolve_tts_runtime(db, "narration")
    if narration_runtime is None:
        narration_runtime = dialogue_runtime
    if dialogue_runtime is None:
        dialogue_runtime = narration_runtime
    if dialogue_runtime is None or narration_runtime is None:
        yield {"type": "error", "message": "No TTS model configured in the model pool"}
        return

    raw_segments = _parse_segments(clean)
    if _needs_llm_speaker_parse(clean, raw_segments):
        raw_segments = await _parse_segments_with_llm_fallback(db, clean, session)
    if not raw_segments:
        yield {"type": "error", "message": "No TTS segments parsed"}
        return

    segments = _assign_segments(
        raw_segments,
        session=session,
        dialogue_runtime=dialogue_runtime,
        narration_runtime=narration_runtime,
    )
    segments = _attach_performance_notes(segments, session)
    segments = _split_long_segments(segments)

    yield {
        "type": "tts_plan",
        "message_id": message.id,
        "total": len(segments),
        "segments": [_segment_public_payload(seg) for seg in segments],
    }

    sem = asyncio.Semaphore(_SYNTH_CONCURRENCY)

    async def synth(seg: TtsSegment) -> dict[str, Any]:
        async with sem:
            try:
                return await _synthesize_segment(
                    seg,
                    narration_runtime,
                    dialogue_runtime,
                    user_id,
                    message.id,
                )
            except Exception as exc:  # pragma: no cover - defensive stream guard
                logger.warning("TRPG TTS segment failed", exc_info=True)
                return {
                    "type": "segment_error",
                    "segment": seg.index,
                    "speaker": seg.speaker,
                    "message": _error_message(exc),
                    "fatal": isinstance(exc, MediaGenerationError),
                }

    tasks = [asyncio.create_task(synth(seg)) for seg in segments]
    segment_events: list[dict[str, Any]] = []
    failed_segments: list[int] = []
    try:
        for task in asyncio.as_completed(tasks):
            event = await task
            if event.get("type") == "tts_segment":
                segment_events.append(event)
            elif event.get("type") == "segment_error":
                index = int(event.get("segment") or 0)
                if index:
                    failed_segments.append(index)
            yield _public_tts_event(event)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    audio_url = ""
    if not failed_segments and len(segment_events) == len(segments):
        audio_url = await _persist_combined_message_audio(
            db,
            message,
            segment_events,
            segments,
            user_id=user_id,
        )

    yield {
        "type": "done",
        "message_id": message.id,
        "total": len(segments),
        "audio_url": audio_url,
        "audio_expires_at": None,
        "failed_segments": sorted(dict.fromkeys(failed_segments)),
    }


async def _resolve_tts_runtime(db: AsyncSession, role: str) -> TtsRuntime | None:
    getter = model_pool.get_dialogue if role == "dialogue" else model_pool.get_narration
    entry = await getter(db)
    if entry is None or not is_tts_model(entry.provider, entry.model):
        return None
    return _runtime_from_entry(entry)


def _runtime_from_entry(entry: ModelPoolEntry) -> TtsRuntime:
    if entry.provider == "mock":
        return TtsRuntime(provider="mock", model=entry.model or "mock-tts")
    saved = admin_config.get_provider(entry.provider) or {}
    defaults = PROVIDER_DEFAULTS.get(entry.provider, {})
    return TtsRuntime(
        provider=entry.provider,
        model=entry.model,
        api_key=saved.get("api_key", "") or str(defaults.get("default_api_key", "")),
        base_url=saved.get("base_url", "") or str(defaults.get("base_url", "")),
    )


async def _parse_segments_with_llm_fallback(
    db: AsyncSession,
    text: str,
    session: GameSession,
) -> list[TtsSegment]:
    """ChatLab-style fallback for legacy GM output that forgot `[speak]` tags."""
    try:
        entry = await model_pool.get_fast(db) or await model_pool.get_default(db)
        if entry is None:
            return _parse_segments(text)
        runtime = _runtime_from_entry(entry)
        roster = _speaker_parse_roster(session)
        prompt = _speaker_parse_prompt(text, roster)
        client = build_client(runtime.provider, runtime.model, runtime.api_key, runtime.base_url)
        chunks: list[str] = []
        async for chunk in client.stream_chat(
            [
                ChatMessage(
                    role="system",
                    content=(
                        "You split TRPG narration into narrator and spoken dialogue segments. "
                        "Return strict JSON only."
                    ),
                ),
                ChatMessage(role="user", content=prompt),
            ],
            temperature=0,
        ):
            if chunk.delta:
                chunks.append(chunk.delta)
        raw = _strip_json_fence("".join(chunks))
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return _parse_segments(text)
        segments = _segments_from_llm_payload(parsed)
        if segments:
            logger.info(
                "TRPG TTS used LLM speaker fallback for untagged corner-quote dialogue: %d segments",
                len(segments),
            )
            return segments
    except Exception:
        logger.warning("TRPG TTS LLM speaker fallback failed", exc_info=True)
    return _parse_segments(text)


def _error_message(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    return str(detail or exc or type(exc).__name__)


__all__ = [
    "TtsRuntime",
    "TtsSegment",
    "stream_message_tts_events",
    "_resolve_tts_runtime",
    "_runtime_from_entry",
    "_parse_segments_with_llm_fallback",
    "_error_message",
    # Re-exports of helpers that external callers / tests import directly:
    "_assign_segments",
    "_attach_performance_notes",
    "_combine_segment_events_to_mp3",
    "_needs_llm_speaker_parse",
    "_parse_segments",
    "_prepare_tts_source",
    "_segments_from_llm_payload",
]
