"""Small, dependency-light helpers for NPC liveness modules.

These helpers intentionally work with dataclasses, Pydantic-ish objects and
plain dictionaries because chatrpg currently bridges old session JSON, runtime
models and table rows at the same time.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping


def clamp(value: Any, low: float = 0.0, high: float = 1.0, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default)
    return max(low, min(high, number))


def get_value(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def set_value(obj: Any, key: str, value: Any) -> None:
    if isinstance(obj, dict):
        obj[key] = value
    else:
        setattr(obj, key, value)


def stable_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    return [value]


def to_plain_data(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return value.to_dict()
        except Exception:
            pass
    if isinstance(value, Mapping):
        return {str(k): to_plain_data(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_plain_data(v) for v in value]
    return value


def text_blob(*items: Any) -> str:
    chunks: list[str] = []
    for item in items:
        plain = to_plain_data(item)
        if plain is None:
            continue
        if isinstance(plain, Mapping):
            chunks.extend(str(v) for v in plain.values() if v not in (None, ""))
        elif isinstance(plain, list):
            chunks.extend(str(v) for v in plain if v not in (None, ""))
        else:
            chunks.append(str(plain))
    return " ".join(chunks).lower()


def short_text(value: Any, *, max_len: int = 240, fallback: str = "") -> str:
    text = str(value or fallback or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"
