"""Cheap mode transition preview/commit helpers."""

from __future__ import annotations

from typing import Any

from .common import get_value


def preview_mode(profile: Any, state: Any, relationship: Any | None, recent_events: list[Any] | None = None) -> str:
    """Return a suggested mode without mutating state."""

    current = str(get_value(state, "current_mode") or "default")
    mood = get_value(state, "mood") or {}
    goal = get_value(state, "goal_pressure") or {}
    fear = _num(mood, "fear")
    suspicion = _num(mood, "suspicion")
    stress = _num(mood, "stress")
    trust = _num(relationship, "trust", 0.35)
    protect_secret = _num(goal, "protect_secret")
    event_types = {str(get_value(ev, "type") or "") for ev in recent_events or []}

    if "ATTACKED_NPC" in event_types or (fear > 0.8 and stress > 0.7):
        return "cornered_or_fleeing"
    if protect_secret > 0.75 and (suspicion > 0.65 or "ASKED_SENSITIVE_QUESTION" in event_types):
        return "guarding_secret"
    if trust > 0.62 and fear > 0.45:
        return "private_confessor"
    if "PUBLIC_EXPOSURE" in event_types and protect_secret > 0.55:
        return "public_mask_under_pressure"
    return current


def _num(obj: Any, key: str, default: float = 0.0) -> float:
    try:
        return float(get_value(obj, key, default) or default)
    except (TypeError, ValueError):
        return default
