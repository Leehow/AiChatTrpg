"""OCR provider configuration.

Mirrors `admin_config.py` for OCR providers. Stored as JSON under
`backend/data/ocr_config.json` (gitignored), layered on top of `.env`
defaults so the operator can either set things via env vars in production
or click around in the debug panel for local development.

The API never returns the api_key — only `api_key_set: bool`. Saving
with an empty string means "keep current value"; saving with a non-empty
string overwrites. To explicitly clear a key, send the sentinel value
`__clear__`.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from core.config import BACKEND_DIR, get_settings

CONFIG_PATH = BACKEND_DIR / "data" / "ocr_config.json"
_lock = threading.Lock()

CLEAR_SENTINEL = "__clear__"

# Single source of truth for ordering, labels, and how each provider
# sources its defaults from .env.
PROVIDER_KEYS: tuple[str, ...] = ("pdftext_local", "mineru_local", "mineru_cloud")


def _empty() -> dict[str, Any]:
    return {"providers": {}, "active_provider": "pdftext_local"}


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


def get_active_provider() -> str:
    """Return the operator-selected OCR provider, if still known."""
    data = _read()
    provider = str(data.get("active_provider") or "pdftext_local")
    return provider if provider in PROVIDER_KEYS else "pdftext_local"


def set_active_provider(provider: str) -> None:
    if provider not in PROVIDER_KEYS:
        raise ValueError(f"Unknown OCR provider '{provider}'")
    with _lock:
        data = _read()
        data["active_provider"] = provider
        _write(data)


def _env_defaults(provider: str) -> dict[str, Any]:
    """Pull defaults for a provider out of Settings."""
    if provider == "pdftext_local":
        return {
            "enabled": True,
            "use_outline_headings": True,
            "synthesise_headings_from_font_size": True,
        }
    s = get_settings()
    if provider == "mineru_local":
        return {
            "enabled": s.mineru_local_enabled,
            "cli": s.mineru_local_cli,
            "backend": s.mineru_local_backend,
            "lang": s.mineru_local_lang,
            "no_formula": s.mineru_local_no_formula,
            "no_table": s.mineru_local_no_table,
            "timeout_seconds": s.mineru_local_timeout_seconds,
        }
    if provider == "mineru_cloud":
        return {
            "api_key": s.mineru_cloud_api_key,
            "base_url": s.mineru_cloud_base_url,
            "model_version": s.mineru_cloud_model_version,
            "poll_interval_seconds": s.mineru_cloud_poll_interval_seconds,
            "poll_timeout_seconds": s.mineru_cloud_poll_timeout_seconds,
        }
    return {}


def _merge(provider: str, stored: dict[str, Any]) -> dict[str, Any]:
    """Layer admin overrides on top of env defaults."""
    env = _env_defaults(provider)
    merged = dict(env)
    for k, v in (stored or {}).items():
        if v is None or v == "":
            continue
        merged[k] = v
    return merged


def _has_key(provider: str, merged: dict[str, Any]) -> bool:
    """Whether this provider has whatever auth/setup it needs to run."""
    if provider == "pdftext_local":
        # Pure-Python — always ready as long as the venv has pymupdf.
        return bool(merged.get("enabled"))
    if provider == "mineru_local":
        # Local needs no key — we can always *try* to call the CLI; the
        # test endpoint surfaces failures.
        return bool(merged.get("enabled"))
    if provider == "mineru_cloud":
        return bool(merged.get("api_key"))
    return False


def _public_view(provider: str, stored: dict[str, Any]) -> dict[str, Any]:
    """The shape the API returns: secrets stripped, has_key derived."""
    merged = _merge(provider, stored)
    env = _env_defaults(provider)
    out: dict[str, Any] = {}
    for k, v in merged.items():
        if k == "api_key":
            continue  # never expose
        out[k] = v
    out["api_key_set"] = _has_key(provider, merged)
    out["env_has_key"] = bool(env.get("api_key")) if "api_key" in env else False
    return out


def load_all_public() -> dict[str, dict[str, Any]]:
    data = _read()
    stored = data.get("providers", {})
    active = get_active_provider()
    out = {}
    for provider in PROVIDER_KEYS:
        item = _public_view(provider, stored.get(provider) or {})
        item["active"] = provider == active
        out[provider] = item
    return out


def get_resolved(provider: str) -> dict[str, Any] | None:
    """Internal use: returns merged config *including* api_key. Don't
    expose this directly via API."""
    if provider not in PROVIDER_KEYS:
        return None
    data = _read()
    stored = (data.get("providers") or {}).get(provider) or {}
    return _merge(provider, stored)


def save_provider(provider: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist user-supplied overrides. Empty fields preserve existing
    value; the literal string `__clear__` deletes the override (so the
    field falls back to its env default)."""
    if provider not in PROVIDER_KEYS:
        raise ValueError(f"Unknown OCR provider '{provider}'")

    with _lock:
        data = _read()
        existing = (data.get("providers") or {}).get(provider) or {}
        updated = dict(existing)

        for key, value in payload.items():
            if value is None:
                continue
            if isinstance(value, str):
                stripped = value.strip()
                if stripped == CLEAR_SENTINEL:
                    updated.pop(key, None)
                    continue
                if stripped == "":
                    # Empty string = "no change" so users can edit other
                    # fields without re-entering the api_key.
                    continue
                updated[key] = stripped
            else:
                updated[key] = value

        data.setdefault("providers", {})[provider] = updated
        _write(data)

    return _public_view(provider, updated)
