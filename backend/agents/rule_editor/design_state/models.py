"""Pydantic op schemas, errors, and result types for the DesignState reducer.

The vocabulary is intentionally small: each op corresponds to a section of the
DesignState dict. Imperative apply logic lives in `reducer.py` so this module
stays declarative and easy for tools/tests to import.
"""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field, ValidationError

from .defaults import (
    BRIEF_FIELDS,
    CATALOG_NAMES,
    COMPILE_STATUSES,
    PHASES,
    SLOT_STATUSES,
    TAXONOMY_FIELDS,
)


PhaseName = Literal[
    "intake",
    "blueprint_selection",
    "core_loop",
    "character_model",
    "resolution_model",
    "procedures",
    "catalogs",
    "playtest",
    "ready",
]


SlotStatus = Literal["missing", "drafting", "filled"]


CompileStatus = Literal["idle", "running", "success", "failed"]


CatalogName = Literal["skills", "actions", "resources", "gear"]


BriefField = Literal["concept", "tone", "complexity", "genre"]


TaxonomyField = Literal["genre", "tone", "complexity", "era", "setting_type"]


# ---------------------------------------------------------------------------
# Op schemas
# ---------------------------------------------------------------------------


class SetPhase(BaseModel):
    op: Literal["set_phase"]
    phase: PhaseName


class SetBriefField(BaseModel):
    op: Literal["set_brief_field"]
    field: BriefField
    value: str


class AddAssumption(BaseModel):
    op: Literal["add_assumption"]
    assumption: str = Field(min_length=1)


class SetTaxonomyField(BaseModel):
    op: Literal["set_taxonomy_field"]
    field: TaxonomyField
    value: str


class SetBlueprint(BaseModel):
    """Set the blueprint reference. Does not merge defaults -- section ops do.

    Use the higher-level `apply_blueprint` from `blueprints/loader.py` to
    compose this with `set_taxonomy_field` and section-setting ops.
    """
    op: Literal["set_blueprint"]
    blueprint_id: str = Field(min_length=1)
    slots_required: list[str] = Field(default_factory=list)
    taxonomy_overrides: dict[str, str] = Field(default_factory=dict)


class SetSlotStatus(BaseModel):
    op: Literal["set_slot_status"]
    slot: str = Field(min_length=1)
    status: SlotStatus


class SetCoreLoop(BaseModel):
    op: Literal["set_core_loop"]
    summary: str | None = None
    phases: list[str] | None = None
    pacing: str | None = None


class SetCharacterModel(BaseModel):
    op: Literal["set_character_model"]
    archetypes: list[str] | None = None
    attributes: list[dict[str, Any]] | None = None
    derived_stats: list[dict[str, Any]] | None = None
    progression_model: str | None = None


class SetResolutionModel(BaseModel):
    op: Literal["set_resolution_model"]
    mechanic: str | None = None
    dice: str | None = None
    success_thresholds: list[dict[str, Any]] | None = None
    notes: str | None = None


class UpsertProcedure(BaseModel):
    op: Literal["upsert_procedure"]
    id: str = Field(min_length=1)
    procedure: dict[str, Any]


class RemoveProcedure(BaseModel):
    op: Literal["remove_procedure"]
    id: str


class UpsertCatalogEntry(BaseModel):
    op: Literal["upsert_catalog_entry"]
    catalog: CatalogName
    id: str = Field(min_length=1)
    entry: dict[str, Any]


class RemoveCatalogEntry(BaseModel):
    op: Literal["remove_catalog_entry"]
    catalog: CatalogName
    id: str


class SetCompileStatus(BaseModel):
    op: Literal["set_compile_status"]
    status: CompileStatus
    error: str | None = None
    parsed_v6_ref: str | None = None


DesignOp = Union[
    SetPhase,
    SetBriefField,
    AddAssumption,
    SetTaxonomyField,
    SetBlueprint,
    SetSlotStatus,
    SetCoreLoop,
    SetCharacterModel,
    SetResolutionModel,
    UpsertProcedure,
    RemoveProcedure,
    UpsertCatalogEntry,
    RemoveCatalogEntry,
    SetCompileStatus,
]


_OP_MODELS: dict[str, type[BaseModel]] = {
    "set_phase": SetPhase,
    "set_brief_field": SetBriefField,
    "add_assumption": AddAssumption,
    "set_taxonomy_field": SetTaxonomyField,
    "set_blueprint": SetBlueprint,
    "set_slot_status": SetSlotStatus,
    "set_core_loop": SetCoreLoop,
    "set_character_model": SetCharacterModel,
    "set_resolution_model": SetResolutionModel,
    "upsert_procedure": UpsertProcedure,
    "remove_procedure": RemoveProcedure,
    "upsert_catalog_entry": UpsertCatalogEntry,
    "remove_catalog_entry": RemoveCatalogEntry,
    "set_compile_status": SetCompileStatus,
}


# ---------------------------------------------------------------------------
# Errors and result types
# ---------------------------------------------------------------------------


class DesignPatchError(Exception):
    """Raised when a batch of design ops fails validation. Carries the index
    of the offending op so the agent can correct."""

    def __init__(self, op_index: int, code: str, message: str) -> None:
        super().__init__(f"op[{op_index}] {code}: {message}")
        self.op_index = op_index
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {
            "op_index": self.op_index,
            "code": self.code,
            "message": self.message,
        }


class DesignDiffEntry(BaseModel):
    """One field change. `path` is a logical path (e.g.
    `["catalogs", "skills", "<id>"]`)."""

    path: list[Union[str, int]]
    before: Any = None
    after: Any = None


class ApplyDesignResult(BaseModel):
    design_state: dict[str, Any]
    diff: list[DesignDiffEntry]


# ---------------------------------------------------------------------------
# Op parsing
# ---------------------------------------------------------------------------


def parse_design_ops(raw: list[dict[str, Any]]) -> list[DesignOp]:
    """Validate raw dicts into typed ops. Raises DesignPatchError on first bad op."""
    parsed: list[DesignOp] = []
    for i, item in enumerate(raw or []):
        if not isinstance(item, dict):
            raise DesignPatchError(i, "bad_shape", "op must be an object")
        op_name = item.get("op")
        if not isinstance(op_name, str):
            raise DesignPatchError(
                i, "missing_op", "missing or non-string `op` field",
            )
        model = _OP_MODELS.get(op_name)
        if model is None:
            raise DesignPatchError(i, "unknown_op", f"unknown op `{op_name}`")
        try:
            parsed.append(model(**item))
        except ValidationError as e:
            raise DesignPatchError(i, "invalid_args", str(e)) from e
    return parsed


__all__ = [
    "PhaseName",
    "SlotStatus",
    "CompileStatus",
    "CatalogName",
    "BriefField",
    "TaxonomyField",
    "SetPhase",
    "SetBriefField",
    "AddAssumption",
    "SetTaxonomyField",
    "SetBlueprint",
    "SetSlotStatus",
    "SetCoreLoop",
    "SetCharacterModel",
    "SetResolutionModel",
    "UpsertProcedure",
    "RemoveProcedure",
    "UpsertCatalogEntry",
    "RemoveCatalogEntry",
    "SetCompileStatus",
    "DesignOp",
    "DesignPatchError",
    "DesignDiffEntry",
    "ApplyDesignResult",
    "parse_design_ops",
    "PHASES",
    "BRIEF_FIELDS",
    "TAXONOMY_FIELDS",
    "SLOT_STATUSES",
    "CATALOG_NAMES",
    "COMPILE_STATUSES",
]
