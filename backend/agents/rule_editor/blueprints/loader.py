"""Deterministic blueprint loader, recommender, and applier.

These functions are pure: same input -> same output, no IO, no clock, no DB.
The loader operates on the read-only catalogue declared in `data.py`.

`apply_blueprint` builds a list of design ops and runs them through the
DesignState reducer. It does **not** overwrite sections the user has already
filled -- it only seeds defaults for empty sections.
"""

from __future__ import annotations

import copy
from typing import Any

from ..design_state import (
    ApplyDesignResult,
    DesignOp,
    SetBlueprint,
    SetCharacterModel,
    SetCoreLoop,
    SetResolutionModel,
    SetTaxonomyField,
    apply_design_ops,
)
from .data import all_blueprints


class BlueprintNotFoundError(Exception):
    """Raised when a blueprint id cannot be resolved."""


def list_blueprints() -> list[dict[str, Any]]:
    """Return all blueprints as a list of fresh deep copies."""
    return all_blueprints()


def get_blueprint(blueprint_id: str) -> dict[str, Any] | None:
    """Return a deep copy of the blueprint with the given id, or None."""
    for bp in all_blueprints():
        if bp.get("id") == blueprint_id:
            return copy.deepcopy(bp)
    return None


def recommend_blueprints(
    text: str = "",
    taxonomy: dict[str, str] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return the top-N blueprint candidates for a free-text brief / taxonomy.

    Scoring is intentionally simple and deterministic:

    - +2 for each keyword that occurs in the lower-cased input text.
    - +3 for each taxonomy field that matches the blueprint's defaults.

    Returns blueprints sorted by descending score, then by id (for stability).
    Score 0 candidates are still returned at the tail so callers always have
    a non-empty list when blueprints exist.
    """
    if limit <= 0:
        return []
    haystack = (text or "").lower()
    taxonomy = taxonomy or {}
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for bp in all_blueprints():
        score = 0
        for kw in bp.get("keywords", []) or []:
            if isinstance(kw, str) and kw.lower() in haystack:
                score += 2
        defaults_taxonomy = bp.get("taxonomy") or {}
        for field, value in taxonomy.items():
            if not isinstance(value, str) or not value:
                continue
            if defaults_taxonomy.get(field) == value:
                score += 3
        scored.append((score, bp.get("id", ""), bp))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [bp for _, _, bp in scored[:limit]]


def apply_blueprint(
    design_state: dict[str, Any],
    blueprint_id: str,
) -> ApplyDesignResult:
    """Apply a blueprint to a DesignState copy.

    Steps:
    1. Set the `blueprint` reference (id, slots_required, taxonomy_overrides).
    2. Merge each non-empty taxonomy default via set_taxonomy_field, but only
       when the target field is currently empty.
    3. Seed default sections (core_loop, resolution_model, character_model)
       only when those sections are empty in the current design state.

    Returns the ApplyDesignResult. The input dict is not mutated.

    Raises BlueprintNotFoundError if the id is unknown.
    """
    bp = get_blueprint(blueprint_id)
    if bp is None:
        raise BlueprintNotFoundError(
            f"unknown blueprint id `{blueprint_id}`"
        )

    ops: list[DesignOp] = []
    taxonomy_defaults = bp.get("taxonomy") or {}
    ops.append(SetBlueprint(
        op="set_blueprint",
        blueprint_id=bp["id"],
        slots_required=list(bp.get("slots_required") or []),
        taxonomy_overrides=dict(taxonomy_defaults),
    ))

    current_taxonomy = design_state.get("taxonomy") or {}
    for field, value in taxonomy_defaults.items():
        if not isinstance(value, str) or not value:
            continue
        if (current_taxonomy.get(field) or "").strip():
            continue
        ops.append(SetTaxonomyField(
            op="set_taxonomy_field", field=field, value=value,
        ))

    defaults = bp.get("defaults") or {}
    if _section_empty(design_state, "core_loop", "summary"):
        cl = defaults.get("core_loop") or {}
        if cl:
            ops.append(SetCoreLoop(
                op="set_core_loop",
                summary=cl.get("summary"),
                phases=cl.get("phases"),
                pacing=cl.get("pacing"),
            ))
    if _section_empty(design_state, "resolution_model", "mechanic"):
        rm = defaults.get("resolution_model") or {}
        if rm:
            ops.append(SetResolutionModel(
                op="set_resolution_model",
                mechanic=rm.get("mechanic"),
                dice=rm.get("dice"),
                success_thresholds=rm.get("success_thresholds"),
                notes=rm.get("notes"),
            ))
    if _character_empty(design_state):
        cm = defaults.get("character_model") or {}
        if cm:
            ops.append(SetCharacterModel(
                op="set_character_model",
                archetypes=cm.get("archetypes"),
                attributes=cm.get("attributes"),
                derived_stats=cm.get("derived_stats"),
                progression_model=cm.get("progression_model"),
            ))

    return apply_design_ops(design_state, ops)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _section_empty(
    state: dict[str, Any], section: str, sentinel_field: str,
) -> bool:
    sec = state.get(section) or {}
    if not isinstance(sec, dict):
        return True
    return not (sec.get(sentinel_field) or "").strip()


def _character_empty(state: dict[str, Any]) -> bool:
    cm = state.get("character_model") or {}
    if not isinstance(cm, dict):
        return True
    if cm.get("attributes"):
        return False
    if (cm.get("progression_model") or "").strip():
        return False
    if cm.get("archetypes"):
        return False
    return True


__all__ = [
    "BlueprintNotFoundError",
    "list_blueprints",
    "get_blueprint",
    "recommend_blueprints",
    "apply_blueprint",
]
