"""Structured event markers for IC turns.

The GM can emit a hidden block at the end of a reply:

    [STRUCTURED_EVENTS]{"events": [...]}[/STRUCTURED_EVENTS]

The visible chat text must not include this JSON. This module handles both
stream-time suppression and final parsing into NPC Runtime V2 `GameEvent`s.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from services.trpg_npc.models import GameEvent
from services.trpg_npc.utils import new_id


_OPEN_RE = re.compile(r"\[STRUCTURED[\s_]?EVENTS\b[^\]]*\]", re.IGNORECASE)
_CLOSE_RE = re.compile(r"\[/STRUCTURED[\s_]?EVENTS\]", re.IGNORECASE)
_BLOCK_RE = re.compile(
    r"\[STRUCTURED[\s_]?EVENTS\b[^\]]*\](.*?)\[/STRUCTURED[\s_]?EVENTS\]",
    re.IGNORECASE | re.DOTALL,
)
_STREAM_TAIL_KEEP = len("[STRUCTURED_EVENTS]") + 8


@dataclass(slots=True)
class StructuredEventParseResult:
    events: list[GameEvent] = field(default_factory=list)
    raw_payloads: list[Any] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "events": [event.to_dict() for event in self.events],
            "raw_payloads": self.raw_payloads,
            "errors": list(self.errors),
        }


class StructuredEventsStreamFilter:
    """Suppress `[STRUCTURED_EVENTS]...[/STRUCTURED_EVENTS]` while streaming."""

    def __init__(self) -> None:
        self._buffer = ""
        self._suppressing = False

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        self._buffer += chunk
        return self._drain(allow_partial=True)

    def flush(self) -> str:
        return self._drain(allow_partial=False)

    def _drain(self, *, allow_partial: bool) -> str:
        out: list[str] = []
        while self._buffer:
            if self._suppressing:
                close = _CLOSE_RE.search(self._buffer)
                if close is None:
                    if not allow_partial:
                        self._buffer = ""
                        self._suppressing = False
                    return "".join(out)
                self._buffer = self._buffer[close.end():]
                self._suppressing = False
                continue

            open_match = _OPEN_RE.search(self._buffer)
            if open_match is not None:
                out.append(self._buffer[:open_match.start()])
                self._buffer = self._buffer[open_match.end():]
                self._suppressing = True
                continue

            if allow_partial and len(self._buffer) > _STREAM_TAIL_KEEP:
                emit_len = len(self._buffer) - _STREAM_TAIL_KEEP
                out.append(self._buffer[:emit_len])
                self._buffer = self._buffer[emit_len:]
                return "".join(out)
            if not allow_partial:
                out.append(self._buffer)
                self._buffer = ""
            return "".join(out)
        return "".join(out)


def strip_structured_events(text: str) -> str:
    """Remove structured event marker blocks from visible/saved GM text."""

    if not text:
        return text
    return _BLOCK_RE.sub("", text).strip()


def parse_structured_events(
    text: str,
    *,
    scene_id: str,
    turn_id: int,
) -> StructuredEventParseResult:
    result = StructuredEventParseResult()
    if not text:
        return result

    for match in _BLOCK_RE.finditer(text):
        body = match.group(1).strip()
        if not body:
            continue
        try:
            payload = json.loads(body)
        except (TypeError, ValueError) as exc:
            result.errors.append(f"json_error: {exc}")
            continue
        result.raw_payloads.append(payload)
        for item in _payload_events(payload):
            event = _event_from_payload(item, scene_id=scene_id, turn_id=turn_id)
            if event is not None:
                result.events.append(event)
    return result


def _payload_events(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        events = payload.get("events")
        if isinstance(events, list):
            return [item for item in events if isinstance(item, dict)]
        # Accept a single-event object for robustness.
        if payload.get("type") or payload.get("content"):
            return [payload]
    return []


def _event_from_payload(
    item: dict[str, Any],
    *,
    scene_id: str,
    turn_id: int,
) -> GameEvent | None:
    content = str(item.get("content") or item.get("summary") or "").strip()
    event_type = str(item.get("type") or "").strip() or "GM_STRUCTURED_EVENT"
    if not content and event_type == "GM_STRUCTURED_EVENT":
        return None
    raw_visibility = item.get("visibility")
    visibility = raw_visibility if isinstance(raw_visibility, dict) else {
        "player_visible": True,
        "gm_visible": True,
    }
    raw_targets = item.get("target_ids") or item.get("targets") or []
    target_ids = (
        [str(v).strip() for v in raw_targets if str(v).strip()]
        if isinstance(raw_targets, list)
        else []
    )
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    return GameEvent(
        event_id=str(item.get("event_id") or "") or new_id("event"),
        type=event_type,
        scene_id=str(item.get("scene_id") or scene_id),
        turn_id=_int(item.get("turn_id"), turn_id),
        actor_id=str(item.get("actor_id") or item.get("actor") or "").strip() or None,
        target_ids=target_ids,
        content=content[:800],
        payload=payload,
        visibility=visibility,
    )


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
