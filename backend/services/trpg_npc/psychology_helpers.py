"""Text-cleaning and small utility helpers for NPC psychology.

These were the trailing private helpers in ``psychology.py``. They are
extracted so the facade module can stay close to the 400-line soft target
while the public API and the higher-level logic remain co-located. Behavior
is unchanged — these are still meant to be private to the psychology layer.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


def _text_blob(npc: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "key", "name", "role", "title", "description", "brief",
        "personality", "import_hint", "relationship_dynamic",
        "goal", "objective", "agenda",
    ):
        value = npc.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    return " ".join(parts)


def _inner_state_blob(npc: dict[str, Any]) -> str:
    inner = npc.get("inner_state")
    if not isinstance(inner, dict):
        return ""
    parts: list[str] = []
    for key in ("motivation", "emotional_state", "secret_agenda"):
        value = inner.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    log = inner.get("thought_log")
    if isinstance(log, list):
        parts.extend(str(item) for item in log if str(item).strip())
    return " ".join(parts)


def _pc_display_name(pc: dict[str, Any] | None) -> str:
    if not isinstance(pc, dict):
        return ""
    for key in ("name", "character_name", "agent_name", "full_name", "callsign"):
        value = _clean_text(pc.get(key), 80)
        if value:
            return value
    identity = pc.get("identity")
    if isinstance(identity, dict):
        for key in ("name", "character_name", "agent_name", "full_name", "callsign"):
            value = _clean_text(identity.get(key), 80)
            if value:
                return value
    return ""


def _first_clause(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.split(r"[，,;；。.]\s*", text, maxsplit=1)[0].strip()


def _clean_text(value: Any, max_len: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > max_len:
        return text[:max_len].rstrip() + "..."
    return text


def _clamp_int(value: Any, low: int, high: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(low, min(high, parsed))


def _split_topic_text(value: Any) -> list[str]:
    text = str(value or "")
    return [chunk.strip() for chunk in re.split(r"[,;；，、/|]\s*", text) if chunk.strip()]


def _unique_strings(values: Iterable[Any], *, limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        text = _clean_text(raw)
        if not text:
            continue
        key = re.sub(r"\s+", "", text).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out
