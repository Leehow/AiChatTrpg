"""Primitive coercion + vector-from-dict helpers for the NPC runtime adapter."""

from __future__ import annotations

from typing import Any

from services.trpg_npc.models import MoodVector, RelationshipVector


def _plain_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _float_dict(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, float] = {}
    for key, raw in value.items():
        out[str(key)] = _float(raw, 0.0)
    return out


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _list_strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _mood_vector_from_dict(value: Any, *, fallback: MoodVector) -> MoodVector:
    data = fallback.to_dict()
    if isinstance(value, dict):
        for key in data:
            if key in value:
                data[key] = _float(value.get(key), data[key])
    return MoodVector(**data).normalized()


def _relationship_vector_from_dict(
    value: Any,
    *,
    fallback: RelationshipVector,
) -> RelationshipVector:
    data = fallback.to_dict()
    if isinstance(value, dict):
        for key in data:
            if key in value:
                data[key] = _float(value.get(key), data[key])
    return RelationshipVector(**data).normalized()
