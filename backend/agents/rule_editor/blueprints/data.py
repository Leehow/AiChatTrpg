"""Read-only starter blueprint catalogue for the rule design agent.

The five starter blueprints live as JSON assets under `assets/`. Each file
contains a single blueprint dict with keys:

- `id`              short slug, must match `[A-Za-z0-9._:-]+`.
- `name`            human-readable label.
- `summary`         one-paragraph pitch for recommendation UIs.
- `taxonomy`        default taxonomy values to merge into design_state.
- `slots_required`  slots the validator gates compile on.
- `defaults`        default content for sections (core_loop, resolution_model,
                    character_model). The blueprint loader merges these into
                    a fresh DesignState only when the target section is empty.
- `keywords`        recommendation hints. Lower-cased substrings the loader
                    matches against the user's brief / taxonomy.

This module is import-only: stdlib JSON + pathlib, no FastAPI / ORM / IO
beyond reading the bundled asset files. Parsed assets are cached on first
access and deep-copied on every public call so callers cannot mutate the
catalogue in place.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


_ASSETS_DIR = Path(__file__).resolve().parent / "assets"

_EXPECTED_IDS = (
    "d20_heroic_adventure",
    "d100_investigation_horror",
    "traditional_fantasy_adventure",
    "mission_anomaly_containment",
    "cyberpunk_job_based",
)

_REQUIRED_KEYS = (
    "id", "name", "summary", "taxonomy",
    "slots_required", "defaults", "keywords",
)

_cache: list[dict[str, Any]] | None = None


def _load_one(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(
            f"blueprint asset `{path.name}` is not a JSON object"
        )
    for key in _REQUIRED_KEYS:
        if key not in data:
            raise ValueError(
                f"blueprint asset `{path.name}` missing required key `{key}`"
            )
    return data


def _load_all() -> list[dict[str, Any]]:
    if not _ASSETS_DIR.is_dir():
        raise FileNotFoundError(
            f"blueprint assets directory missing: {_ASSETS_DIR}"
        )
    paths = sorted(_ASSETS_DIR.glob("*.json"), key=lambda p: p.name)
    blueprints = [_load_one(p) for p in paths]
    seen_ids = {bp["id"] for bp in blueprints}
    missing = [bid for bid in _EXPECTED_IDS if bid not in seen_ids]
    if missing:
        raise ValueError(
            f"blueprint catalogue is missing expected ids: {missing!r}"
        )
    return blueprints


def all_blueprints() -> list[dict[str, Any]]:
    """Return a fresh list of blueprint dicts. Each call produces deep copies."""
    global _cache
    if _cache is None:
        _cache = _load_all()
    return [copy.deepcopy(bp) for bp in _cache]


__all__ = ["all_blueprints"]
