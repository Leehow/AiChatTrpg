"""Utility helpers for the chatrpg NPC runtime.

This module intentionally has no third-party dependencies so it can be
copied into an existing FastAPI / Django / plain asyncio backend without
forcing dependency changes.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Clamp a numeric value into a bounded range."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = low
    if v < low:
        return low
    if v > high:
        return high
    return v


def clamp_signed(value: float) -> float:
    """Clamp to the common signed affect range [-1, 1]."""
    return clamp(value, -1.0, 1.0)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def deep_to_dict(value: Any) -> Any:
    """Serialize dataclasses/enums/lists/dicts into plain JSON-like values."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {k: deep_to_dict(v) for k, v in asdict(value).items()}
    if isinstance(value, list):
        return [deep_to_dict(v) for v in value]
    if isinstance(value, tuple):
        return [deep_to_dict(v) for v in value]
    if isinstance(value, dict):
        return {str(k): deep_to_dict(v) for k, v in value.items()}
    return value


def merge_float_dicts(*items: Mapping[str, float], low: float = 0.0, high: float = 1.0) -> dict[str, float]:
    """Add multiple float dictionaries and clamp the result.

    Useful for merging several mood/relationship deltas.
    """
    out: dict[str, float] = {}
    for item in items:
        for key, value in item.items():
            out[key] = out.get(key, 0.0) + float(value)
    return {k: clamp(v, low, high) for k, v in out.items()}


def weighted_average(current: float, target: float, weight: float) -> float:
    """Move current toward target by weight."""
    return current * (1.0 - weight) + target * weight
