"""Adapter registry — the open-core boundary.

Open-source code in `agents/trpg/` only ever calls into adapters via this
registry, never importing closed implementations directly. AiChatTrpg installs
no-op or stub implementations at startup; ChatLab overrides them with the
real closed-source services.
"""

from __future__ import annotations

from typing import Any


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, Any] = {}

    def register(self, name: str, adapter: Any) -> None:
        self._adapters[name] = adapter

    def get(self, name: str) -> Any:
        if name not in self._adapters:
            raise KeyError(
                f"Adapter '{name}' is not registered. "
                f"Known adapters: {sorted(self._adapters)}"
            )
        return self._adapters[name]

    def has(self, name: str) -> bool:
        return name in self._adapters


_registry = AdapterRegistry()


def register(name: str, adapter: Any) -> None:
    _registry.register(name, adapter)


def get(name: str) -> Any:
    return _registry.get(name)


def has(name: str) -> bool:
    return _registry.has(name)
