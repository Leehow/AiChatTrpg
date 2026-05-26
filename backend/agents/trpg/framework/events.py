"""TurnEvent variants — what `run_trpg_turn` yields.

Caller wraps these into whatever transport they want (SSE, websocket, in-memory
list for tests). Framework yields raw events; transport layer formats them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .models import Message, TurnResult


@dataclass
class MetadataEvent:
    """First event emitted; carries session/mode metadata for the UI."""

    payload: dict[str, Any]
    type: Literal["metadata"] = "metadata"


@dataclass
class ThinkingEvent:
    """One debug line, e.g. `[BP1 stable] ruleset=... | core_rules=...`. The
    framework emits these in real time so the UI can show progress before the
    LLM stream starts."""

    line: str
    type: Literal["thinking"] = "thinking"


@dataclass
class ContentDeltaEvent:
    """A streaming token from the LLM."""

    delta: str
    type: Literal["content"] = "content"


@dataclass
class BpSnapshotEvent:
    """Full BP1/BP2/BP3 snapshot for the current turn. The frontend "Context"
    tab subscribes to this to mirror exactly what was injected into the prompt."""

    snapshot: Any  # BpSnapshot — loose typing to dodge circular imports
    layered_prompt: Any | None = None  # LayeredPrompt, when IC/BREAK caching applies
    metadata: dict[str, Any] = field(default_factory=dict)
    type: Literal["bp_snapshot"] = "bp_snapshot"


@dataclass
class MarkerEvent:
    """A parsed marker pulled out of the assistant's reply (e.g. [ROLL ...])."""

    marker: Any  # ParsedMarker
    type: Literal["marker"] = "marker"


@dataclass
class SideEffectEvent:
    """A postprocess side effect that the caller may persist or relay
    (mem update, dice consumed, scene set, multimedia synthesized, etc.)."""

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    type: Literal["side_effect"] = "side_effect"


@dataclass
class DoneEvent:
    """Final event. Carries the structured TurnResult including SessionStateDiff."""

    result: TurnResult
    type: Literal["done"] = "done"


@dataclass
class ErrorEvent:
    message: str
    exc_type: str = ""
    type: Literal["error"] = "error"


# Convenience type alias for the event stream.
TurnEvent = (
    MetadataEvent
    | ThinkingEvent
    | ContentDeltaEvent
    | BpSnapshotEvent
    | MarkerEvent
    | SideEffectEvent
    | DoneEvent
    | ErrorEvent
)


__all__ = [
    "BpSnapshotEvent",
    "ContentDeltaEvent",
    "DoneEvent",
    "ErrorEvent",
    "MarkerEvent",
    "Message",
    "MetadataEvent",
    "SideEffectEvent",
    "ThinkingEvent",
    "TurnEvent",
]
