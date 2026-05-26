"""Admin-managed provider configuration.

Stored as a JSON file so we don't need an alembic migration for a feature that's
fundamentally a single-user settings panel. Layered on top of `.env`: the admin
file wins when both define the same field.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from core.config import BACKEND_DIR, get_settings
from llm import list_providers

CONFIG_PATH = BACKEND_DIR / "data" / "admin_config.json"
_lock = threading.Lock()


def _empty() -> dict[str, Any]:
    return {"providers": {}}


def _read() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return _empty()
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _empty()
    if not isinstance(data, dict) or not isinstance(data.get("providers"), dict):
        return _empty()
    return data


def _write(data: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def _normalize_provider(raw: dict[str, Any]) -> dict[str, Any]:
    api_key = (raw.get("api_key") or "").strip()
    base_url = (raw.get("base_url") or "").strip()
    raw_models = raw.get("models") or []
    models: list[str] = []
    seen: set[str] = set()
    for m in raw_models:
        if not isinstance(m, str):
            continue
        name = m.strip()
        if name and name not in seen:
            seen.add(name)
            models.append(name)
    return {"api_key": api_key, "base_url": base_url, "models": models}


def _normalize_media_settings(raw: dict[str, Any]) -> dict[str, Any]:
    narration = raw.get("narration_voice")
    if not isinstance(narration, dict):
        return {"narration_voice": None}
    provider = str(narration.get("provider") or "").strip()
    model = str(narration.get("model") or "").strip()
    voice = str(narration.get("voice") or "").strip()
    if not provider or not model or not voice:
        return {"narration_voice": None}
    return {
        "narration_voice": {
            "provider": provider,
            "model": model,
            "voice": voice,
        },
    }


def load_all() -> dict[str, dict[str, Any]]:
    """Return every known provider with admin overrides merged on top of env."""
    data = _read()
    stored = data.get("providers", {})
    settings = get_settings()
    result: dict[str, dict[str, Any]] = {}
    for name in list_providers():
        if name == "mock":
            continue
        env_cfg = settings.provider_config(name)
        admin_cfg = stored.get(name) or {}
        result[name] = {
            "api_key": admin_cfg.get("api_key") or env_cfg.get("api_key", ""),
            "base_url": admin_cfg.get("base_url") or env_cfg.get("base_url", ""),
            "models": list(admin_cfg.get("models") or []),
            "default_model": env_cfg.get("default_model", ""),
            "env_has_key": bool(env_cfg.get("api_key")),
        }
    return result


def save_provider(provider: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Replace one provider's stored config. Empty fields fall back to env."""
    if provider not in list_providers() or provider == "mock":
        raise ValueError(f"Unknown provider '{provider}'")
    normalized = _normalize_provider(payload)
    with _lock:
        data = _read()
        data.setdefault("providers", {})[provider] = normalized
        _write(data)
    return load_all()[provider]


def get_provider(provider: str) -> dict[str, Any] | None:
    """Return merged env + admin config for one provider, or None for unknown."""
    if provider == "mock" or provider not in list_providers():
        return None
    return load_all().get(provider)


def list_models() -> dict[str, list[str]]:
    """Map provider → user-added model list. Skips providers without an API key."""
    out: dict[str, list[str]] = {}
    for name, cfg in load_all().items():
        if not cfg.get("api_key"):
            continue
        models = cfg.get("models") or []
        if models:
            out[name] = list(models)
    return out


def configured_providers() -> list[str]:
    """Providers that have a usable API key from either env or admin file."""
    return [name for name, cfg in load_all().items() if cfg.get("api_key")]


def get_media_settings() -> dict[str, Any]:
    """Return persisted media runtime choices such as narration voice."""
    data = _read()
    media = data.get("media") if isinstance(data.get("media"), dict) else {}
    return _normalize_media_settings(media)


def save_media_settings(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_media_settings(payload)
    with _lock:
        data = _read()
        data["media"] = normalized
        _write(data)
    return normalized
