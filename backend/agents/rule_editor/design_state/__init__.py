"""Pure DesignState package -- authoring artifact for the rule design agent.

This package is engine-pure: it does not import FastAPI, ORM, or React. It
deals with a plain `dict[str, Any]` artifact (`design_state`), a small typed
patch vocabulary, and pure validator/summary helpers.
"""

from __future__ import annotations

from .defaults import (
    BRIEF_FIELDS,
    CATALOG_NAMES,
    COMPILE_STATUSES,
    PHASES,
    SCHEMA_VERSION,
    SLOT_STATUSES,
    TAXONOMY_FIELDS,
    empty_design_state,
)
from .issues import DesignIssue, Severity
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
    parse_design_ops,
)
from .reducer import apply_design_ops
from .summary import build_summary
from .validator import SlotCompletion, ValidationReport, validate_design_state


__all__ = [
    "SCHEMA_VERSION",
    "PHASES",
    "BRIEF_FIELDS",
    "TAXONOMY_FIELDS",
    "SLOT_STATUSES",
    "CATALOG_NAMES",
    "COMPILE_STATUSES",
    "empty_design_state",
    "DesignIssue",
    "Severity",
    "DesignOp",
    "DesignPatchError",
    "DesignDiffEntry",
    "ApplyDesignResult",
    "AddAssumption",
    "RemoveCatalogEntry",
    "RemoveProcedure",
    "SetBlueprint",
    "SetBriefField",
    "SetCharacterModel",
    "SetCompileStatus",
    "SetCoreLoop",
    "SetPhase",
    "SetResolutionModel",
    "SetSlotStatus",
    "SetTaxonomyField",
    "UpsertCatalogEntry",
    "UpsertProcedure",
    "parse_design_ops",
    "apply_design_ops",
    "SlotCompletion",
    "ValidationReport",
    "validate_design_state",
    "build_summary",
]
