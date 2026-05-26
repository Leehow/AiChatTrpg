"""Patch op schemas + parser. The actual mutation logic lives in `apply.py`.

The agent emits a list of `PatchOp` Pydantic models per turn. Apply path:
1. `parse_ops(raw)` validates raw dicts → typed ops, raising PatchError on
   the first invalid op (with op_index).
2. `apply_ops(parsed_v6, ops)` (in apply.py) mutates a deep copy and
   returns the new artifact + structured diff.

All-or-nothing: if any op is invalid (e.g. removing an unknown package id),
the whole batch is rejected. Caller surfaces the error to the LLM so it
can correct.
"""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field, ValidationError


# ---------------------------------------------------------------------------
# Op schemas
# ---------------------------------------------------------------------------

META_FIELDS = ("book_id", "book_title", "world_mode", "output_language")


class SetMeta(BaseModel):
    op: Literal["set_meta"]
    field: Literal["book_id", "book_title", "world_mode", "output_language"]
    value: str


class SetCoreRules(BaseModel):
    op: Literal["set_core_rules"]
    content: str


class PatchCoreRules(BaseModel):
    """Find/replace inside core_rules. `find` must occur exactly once."""
    op: Literal["patch_core_rules"]
    find: str
    replace: str


class SetCompanion(BaseModel):
    op: Literal["set_companion"]
    filename: str
    content: str


class UpsertRulePackage(BaseModel):
    op: Literal["upsert_rule_package"]
    id: str
    package: dict[str, Any] = Field(
        ...,
        description=(
            "Full package dict; `package_id` is overwritten with `id`. "
            "Required keys: content (markdown). Optional: filename, raw, "
            "excerpt_stats."
        ),
    )


class RemoveRulePackage(BaseModel):
    op: Literal["remove_rule_package"]
    id: str


class UpsertParameterFamily(BaseModel):
    op: Literal["upsert_parameter_family"]
    id: str
    family: dict[str, Any] = Field(
        ...,
        description=(
            "Full family dict; `family_id` is overwritten with `id`. "
            "Either `content` (markdown) or `json` (structured) is "
            "expected. Optional: filename, raw, should_remain_markdown."
        ),
    )


class RemoveParameterFamily(BaseModel):
    op: Literal["remove_parameter_family"]
    id: str


class SetCharacterSheet(BaseModel):
    op: Literal["set_character_sheet"]
    template_json: dict[str, Any] | None = None
    template_content: str | None = None
    template_filename: str | None = None
    guide_content: str | None = None
    guide_filename: str | None = None


class PatchCharacterSheetField(BaseModel):
    """Set a single field inside `character_sheet` by JSON-pointer-like path.

    `path` is a list of keys / array indices. Example to rename the first
    skill in `template_json.skills[0].name`:
      path=["template_json", "skills", 0, "name"], value="Athletics"
    """
    op: Literal["patch_character_sheet_field"]
    path: list[Union[str, int]]
    value: Any


class MarkRecompile(BaseModel):
    op: Literal["mark_recompile"]
    dice: bool = False
    character_ui: bool = False


PatchOp = Union[
    SetMeta,
    SetCoreRules,
    PatchCoreRules,
    SetCompanion,
    UpsertRulePackage,
    RemoveRulePackage,
    UpsertParameterFamily,
    RemoveParameterFamily,
    SetCharacterSheet,
    PatchCharacterSheetField,
    MarkRecompile,
]


_OP_MODELS: dict[str, type[BaseModel]] = {
    "set_meta": SetMeta,
    "set_core_rules": SetCoreRules,
    "patch_core_rules": PatchCoreRules,
    "set_companion": SetCompanion,
    "upsert_rule_package": UpsertRulePackage,
    "remove_rule_package": RemoveRulePackage,
    "upsert_parameter_family": UpsertParameterFamily,
    "remove_parameter_family": RemoveParameterFamily,
    "set_character_sheet": SetCharacterSheet,
    "patch_character_sheet_field": PatchCharacterSheetField,
    "mark_recompile": MarkRecompile,
}


# ---------------------------------------------------------------------------
# Errors and result types
# ---------------------------------------------------------------------------


class PatchError(Exception):
    """Raised when a batch of ops fails validation. Carries the index of
    the offending op so the agent can correct."""

    def __init__(self, op_index: int, code: str, message: str) -> None:
        super().__init__(f"op[{op_index}] {code}: {message}")
        self.op_index = op_index
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {"op_index": self.op_index, "code": self.code, "message": self.message}


class DiffEntry(BaseModel):
    """One field change. `path` is a logical path that survives reorders
    (e.g. `["rule_packages", "<id>"]` rather than array index)."""
    path: list[Union[str, int]]
    before: Any = None
    after: Any = None


# ---------------------------------------------------------------------------
# Op parsing
# ---------------------------------------------------------------------------


def parse_ops(raw: list[dict[str, Any]]) -> list[PatchOp]:
    """Validate raw dicts into typed ops. Raises PatchError on first bad op."""
    parsed: list[PatchOp] = []
    for i, item in enumerate(raw or []):
        if not isinstance(item, dict):
            raise PatchError(i, "bad_shape", "op must be an object")
        op_name = item.get("op")
        if not isinstance(op_name, str):
            raise PatchError(i, "missing_op", "missing or non-string `op` field")
        model = _OP_MODELS.get(op_name)
        if model is None:
            raise PatchError(i, "unknown_op", f"unknown op `{op_name}`")
        try:
            parsed.append(model(**item))
        except ValidationError as e:
            raise PatchError(i, "invalid_args", str(e)) from e
    return parsed


# Re-export apply_ops + ApplyResult so existing callers keep working.
from .apply import ApplyResult, apply_ops  # noqa: E402, F401
