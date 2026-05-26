"""Small compatibility helpers used by the NPC Runtime V2 hardening layer."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping, MutableMapping


_MISSING = object()


def get_value(obj: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from either a mapping or an object.

    The current codebase uses a mix of plain dictionaries, Pydantic-like
    models and SimpleNamespace objects in tests.  These helpers keep the new
    hardening utilities independent from a single model implementation.
    """

    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def set_value(obj: Any, key: str, value: Any) -> None:
    """Set ``key`` on a mapping or object."""

    if isinstance(obj, MutableMapping):
        obj[key] = value
    else:
        setattr(obj, key, value)


def to_plain_data(value: Any) -> Any:
    """Convert dataclasses / Pydantic-style objects into plain data."""

    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [to_plain_data(v) for v in value]
    if isinstance(value, tuple):
        return [to_plain_data(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_plain_data(v) for k, v in value.items()}
    if is_dataclass(value):
        return to_plain_data(asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return to_plain_data(model_dump())
    dict_method = getattr(value, "dict", None)
    if callable(dict_method):
        return to_plain_data(dict_method())
    if hasattr(value, "__dict__"):
        return {
            str(k): to_plain_data(v)
            for k, v in vars(value).items()
            if not k.startswith("_")
        }
    return str(value)


def first_non_empty(*values: Any, default: Any = None) -> Any:
    """Return the first value that is not None and not an empty string/list/dict."""

    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple, dict)) and not value:
            continue
        return value
    return default


def clamp(value: Any, lower: float = 0.0, upper: float = 1.0) -> float:
    """Best-effort numeric clamp for mood / score fields."""

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = lower
    return max(lower, min(upper, numeric))


def stable_list(value: Any) -> list[Any]:
    """Normalize nullable/list/singleton values into a list."""

    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]
