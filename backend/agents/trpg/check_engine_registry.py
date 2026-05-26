"""Registry for deterministic TRPG check engines."""

from __future__ import annotations

from typing import Any, Callable

EngineFn = Callable[[Any, dict[str, Any]], Any]

_ENGINES: dict[str, EngineFn] = {}
_LABELS_BY_ENGINE: dict[str, dict[str, str]] = {}
_BUILTINS_LOADED = False


def register_engine(
    name: str,
    fn: EngineFn,
    *,
    default_labels: dict[str, str] | None = None,
) -> None:
    """Register one deterministic check engine and its optional default labels."""

    key = str(name or "").strip().lower()
    if not key:
        raise ValueError("check engine name cannot be empty")
    _ENGINES[key] = fn
    if default_labels is not None:
        _LABELS_BY_ENGINE[key] = dict(default_labels)


def get_engine(name: str) -> EngineFn:
    """Return a registered engine, falling back to ``custom_llm``."""

    _ensure_builtin_engines()
    key = str(name or "").strip().lower()
    fallback = _ENGINES.get("custom_llm")
    if fallback is None:
        raise RuntimeError("custom_llm check engine is not registered")
    return _ENGINES.get(key) or fallback


def get_default_labels(engine: str) -> dict[str, str]:
    """Return a copy of default labels registered for ``engine``."""

    _ensure_builtin_engines()
    return dict(_LABELS_BY_ENGINE.get(str(engine or "").strip().lower(), {}))


def registered_engine_names() -> list[str]:
    """Return registered engine keys for diagnostics/tests."""

    _ensure_builtin_engines()
    return sorted(_ENGINES)


def _ensure_builtin_engines() -> None:
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    _BUILTINS_LOADED = True
    from . import check_engines  # noqa: F401
    from .check_ir import adapter  # noqa: F401
