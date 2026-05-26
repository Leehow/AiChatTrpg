"""Pydantic models for the SSE event union streamed by chat / IC turns.

The IC runner (``services.trpg_ic_runner``) yields plain dicts by
shape; this module formalises those shapes so ``scripts/compile_api/
export_spec.py`` can emit a JSON Schema (``contracts/sse_events.json``)
that downstream consumers — the React client and any chatlab embedder
— can validate against.

Each event has a literal ``type`` field that the consumer dispatches
on. The discriminated union of all events is what the schema export
serialises.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SseMetadataEvent(BaseModel):
    """Top-of-turn provider metadata + per-turn structured-event re-emits.

    Examples include the model id, latency hints, and structured-event
    payloads forwarded mid-stream when the engine wants the client to
    render a marker before the next chunk lands.
    """
    type: Literal["metadata"] = "metadata"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SseThinkingEvent(BaseModel):
    """One human-readable line of GM "chain of thought" surfaced for
    debug. The frontend stitches consecutive lines into a chain block;
    they are also persisted on the saved message under
    ``metadata.thinking_steps`` so reload still shows the chain."""
    type: Literal["thinking"] = "thinking"
    content: str


class SseContentEvent(BaseModel):
    """A chunk of the GM's prose for the player. The client appends
    these to the streaming bubble verbatim."""
    type: Literal["content"] = "content"
    content: str


class SseMarkerEvent(BaseModel):
    """A parsed in-stream marker (``[ROLL]``, ``[SET_SCENE]``,
    ``[UPDATE_MEMORY]``, …). The ``marker`` payload mirrors the
    backend's ``ParsedMarker`` dict: type, args, body."""
    type: Literal["marker"] = "marker"
    marker: dict[str, Any] = Field(default_factory=dict)


class SseSideEffectEvent(BaseModel):
    """Out-of-band engine effect that doesn't belong inline in prose:
    auto-resolved pending checks, NPC asset queue summary, structured
    state changes, etc. ``kind`` discriminates payload shape."""
    type: Literal["side_effect"] = "side_effect"
    kind: str
    payload: Any = None


class SseDoneEvent(BaseModel):
    """Stream completion. ``result`` carries the final summary the
    server wants the client to surface — assistant text, diff summary,
    counts, etc. Shape varies by stream (chat vs character creation
    vs adventure start) so it's typed loosely; the consumer keys on
    ``type=='done'`` then reads what it needs."""
    type: Literal["done"] = "done"
    result: dict[str, Any] | None = None


class SseErrorEvent(BaseModel):
    """Recoverable error inside a stream. The consumer can surface a
    toast and keep reading subsequent events; a fatal error closes the
    SSE connection from the server side."""
    type: Literal["error"] = "error"
    content: str | None = None
    message: str | None = None
    error: str | None = None
    exc_type: str | None = None


class SseSegmentErrorEvent(BaseModel):
    """Per-segment failure inside a multi-segment stream (TTS streaming
    is the main current consumer). Distinct from ``error`` because the
    overall stream may still complete successfully — just one segment
    failed and the client should fall back."""
    type: Literal["segment_error"] = "segment_error"
    error: str
    segment: int | None = None
