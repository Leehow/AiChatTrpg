"""apply_design_ops -- pure reducer over a DesignState dict.

The reducer is deterministic, all-or-nothing, and never mutates its input.
Op schemas live in `models.py`; this module owns the imperative apply logic.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .models import (
    AddAssumption,
    ApplyDesignResult,
    DesignDiffEntry,
    DesignOp,
    DesignPatchError,
    RemoveCatalogEntry,
    RemoveProcedure,
    SetBlueprint,
    SetBriefField,
    SetCharacterModel,
    SetCompileStatus,
    SetCoreLoop,
    SetPhase,
    SetResolutionModel,
    SetSlotStatus,
    SetTaxonomyField,
    UpsertCatalogEntry,
    UpsertProcedure,
)


_SAFE_ID = re.compile(r"^[A-Za-z0-9._:\-]+$")


def apply_design_ops(
    design_state: dict[str, Any],
    ops: list[DesignOp],
) -> ApplyDesignResult:
    """Apply ops to a deep copy of `design_state`. Pure function.

    Raises DesignPatchError if any op is invalid against the current state.
    The original `design_state` is never mutated, even on partial failure
    (all-or-nothing semantics -- we work on a deep copy).
    """
    new_state = copy.deepcopy(design_state)
    diff: list[DesignDiffEntry] = []

    for i, op in enumerate(ops):
        try:
            entries = _apply_one(new_state, op)
        except DesignPatchError as e:
            raise DesignPatchError(i, e.code, e.message) from None
        diff.extend(entries)

    return ApplyDesignResult(design_state=new_state, diff=diff)


def _apply_one(
    state: dict[str, Any], op: DesignOp,
) -> list[DesignDiffEntry]:
    if isinstance(op, SetPhase):
        before = state.get("phase", "")
        state["phase"] = op.phase
        return [DesignDiffEntry(path=["phase"], before=before, after=op.phase)]

    if isinstance(op, SetBriefField):
        brief = _ensure_dict(state, "brief")
        before = brief.get(op.field, "")
        brief[op.field] = op.value
        return [DesignDiffEntry(
            path=["brief", op.field], before=before, after=op.value,
        )]

    if isinstance(op, AddAssumption):
        brief = _ensure_dict(state, "brief")
        assumptions = brief.setdefault("assumptions", [])
        if not isinstance(assumptions, list):
            raise DesignPatchError(
                0, "bad_state", "brief.assumptions is not a list",
            )
        assumptions.append(op.assumption)
        return [DesignDiffEntry(
            path=["brief", "assumptions", len(assumptions) - 1],
            before=None, after=op.assumption,
        )]

    if isinstance(op, SetTaxonomyField):
        taxonomy = _ensure_dict(state, "taxonomy")
        before = taxonomy.get(op.field, "")
        taxonomy[op.field] = op.value
        return [DesignDiffEntry(
            path=["taxonomy", op.field], before=before, after=op.value,
        )]

    if isinstance(op, SetBlueprint):
        if not _SAFE_ID.match(op.blueprint_id):
            raise DesignPatchError(
                0, "bad_id",
                f"blueprint_id `{op.blueprint_id}` contains unsafe characters",
            )
        before = state.get("blueprint")
        new_block = {
            "id": op.blueprint_id,
            "slots_required": list(op.slots_required),
            "taxonomy_overrides": dict(op.taxonomy_overrides),
        }
        state["blueprint"] = new_block
        slots = _ensure_dict(state, "slots")
        for slot in op.slots_required:
            slots.setdefault(slot, "missing")
        return [DesignDiffEntry(
            path=["blueprint"], before=before, after=new_block,
        )]

    if isinstance(op, SetSlotStatus):
        slots = _ensure_dict(state, "slots")
        before = slots.get(op.slot, "missing")
        slots[op.slot] = op.status
        return [DesignDiffEntry(
            path=["slots", op.slot], before=before, after=op.status,
        )]

    if isinstance(op, SetCoreLoop):
        return _merge_section(state, "core_loop", {
            "summary": op.summary,
            "phases": op.phases,
            "pacing": op.pacing,
        })

    if isinstance(op, SetCharacterModel):
        return _merge_section(state, "character_model", {
            "archetypes": op.archetypes,
            "attributes": op.attributes,
            "derived_stats": op.derived_stats,
            "progression_model": op.progression_model,
        })

    if isinstance(op, SetResolutionModel):
        return _merge_section(state, "resolution_model", {
            "mechanic": op.mechanic,
            "dice": op.dice,
            "success_thresholds": op.success_thresholds,
            "notes": op.notes,
        })

    if isinstance(op, UpsertProcedure):
        return _upsert_id_list(
            state, "procedures", "id", op.id, op.procedure,
        )

    if isinstance(op, RemoveProcedure):
        return _remove_id_list(state, "procedures", "id", op.id)

    if isinstance(op, UpsertCatalogEntry):
        catalogs = _ensure_dict(state, "catalogs")
        bucket = catalogs.setdefault(op.catalog, [])
        if not isinstance(bucket, list):
            raise DesignPatchError(
                0, "bad_state", f"catalogs.{op.catalog} is not a list",
            )
        return _upsert_into_bucket(
            bucket, op.catalog, op.id, op.entry,
            path_prefix=["catalogs", op.catalog],
        )

    if isinstance(op, RemoveCatalogEntry):
        catalogs = _ensure_dict(state, "catalogs")
        bucket = catalogs.get(op.catalog)
        if not isinstance(bucket, list):
            raise DesignPatchError(
                0, "not_found",
                f"catalogs.{op.catalog} is missing or empty",
            )
        return _remove_from_bucket(
            bucket, op.catalog, op.id,
            path_prefix=["catalogs", op.catalog],
        )

    if isinstance(op, SetCompileStatus):
        before = state.get("compile")
        new_compile = {
            "status": op.status,
            "error": op.error or "",
            "parsed_v6_ref": op.parsed_v6_ref or "",
        }
        state["compile"] = new_compile
        return [DesignDiffEntry(
            path=["compile"], before=before, after=new_compile,
        )]

    raise DesignPatchError(
        0, "unhandled_op", f"unhandled op type: {type(op).__name__}",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_dict(state: dict[str, Any], key: str) -> dict[str, Any]:
    value = state.get(key)
    if value is None:
        new: dict[str, Any] = {}
        state[key] = new
        return new
    if not isinstance(value, dict):
        raise DesignPatchError(0, "bad_state", f"`{key}` is not an object")
    return value


def _merge_section(
    state: dict[str, Any], section: str, fields: dict[str, Any],
) -> list[DesignDiffEntry]:
    target = _ensure_dict(state, section)
    entries: list[DesignDiffEntry] = []
    any_set = False
    for field, value in fields.items():
        if value is None:
            continue
        any_set = True
        before = target.get(field)
        target[field] = value
        entries.append(DesignDiffEntry(
            path=[section, field], before=before, after=value,
        ))
    if not any_set:
        raise DesignPatchError(
            0, "no_fields",
            f"set_{section} requires at least one non-null field",
        )
    return entries


def _upsert_id_list(
    state: dict[str, Any], list_key: str, id_field: str,
    item_id: str, payload: dict[str, Any],
) -> list[DesignDiffEntry]:
    items = state.setdefault(list_key, [])
    if not isinstance(items, list):
        raise DesignPatchError(
            0, "bad_state", f"{list_key} is not a list",
        )
    return _upsert_into_bucket(
        items, list_key, item_id, payload, path_prefix=[list_key],
        id_field=id_field,
    )


def _remove_id_list(
    state: dict[str, Any], list_key: str, id_field: str, item_id: str,
) -> list[DesignDiffEntry]:
    items = state.get(list_key)
    if not isinstance(items, list):
        raise DesignPatchError(
            0, "not_found", f"{list_key} is empty or missing",
        )
    return _remove_from_bucket(
        items, list_key, item_id, path_prefix=[list_key], id_field=id_field,
    )


def _upsert_into_bucket(
    bucket: list[Any], bucket_label: str, item_id: str,
    payload: dict[str, Any], path_prefix: list[Any],
    id_field: str = "id",
) -> list[DesignDiffEntry]:
    if not item_id or not _SAFE_ID.match(item_id):
        raise DesignPatchError(
            0, "bad_id",
            f"id `{item_id}` is empty or contains unsafe characters",
        )
    if not isinstance(payload, dict):
        raise DesignPatchError(
            0, "bad_payload",
            f"{bucket_label} entry must be an object, got {type(payload).__name__}",
        )
    new_item = dict(payload)
    new_item[id_field] = item_id
    for idx, existing in enumerate(bucket):
        if isinstance(existing, dict) and existing.get(id_field) == item_id:
            before = copy.deepcopy(existing)
            bucket[idx] = new_item
            return [DesignDiffEntry(
                path=[*path_prefix, item_id],
                before=before, after=new_item,
            )]
    bucket.append(new_item)
    return [DesignDiffEntry(
        path=[*path_prefix, item_id], before=None, after=new_item,
    )]


def _remove_from_bucket(
    bucket: list[Any], bucket_label: str, item_id: str,
    path_prefix: list[Any], id_field: str = "id",
) -> list[DesignDiffEntry]:
    for idx, existing in enumerate(bucket):
        if isinstance(existing, dict) and existing.get(id_field) == item_id:
            before = copy.deepcopy(existing)
            del bucket[idx]
            return [DesignDiffEntry(
                path=[*path_prefix, item_id], before=before, after=None,
            )]
    raise DesignPatchError(
        0, "not_found",
        f"{bucket_label}[{id_field}={item_id}] not found",
    )


__all__ = ["apply_design_ops"]
