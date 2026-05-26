"""Deterministic compiler from `design_state` to runtime `parsed_v6`.

Engine-pure facade: no FastAPI / ORM / React imports. Same input -> same
output. Heavy section builders live in sibling helper modules so the
public surface here stays small.

The compiler is intentionally minimal in P0:

- It refuses to compile when the validator surfaces blocking issues.
- It emits the runtime-compatible V6 sections requested by the epic
  (`meta`, `core_rules`, `companion`, `rule_packages`,
  `parameter_families`, `character_sheet`) from a `design_state` dict.
- Existing draft meta (`book_id`, `book_title`, `world_mode`,
  `output_language`) is preserved from `base_v6` when the design state
  does not carry an inferable replacement.

P1 will extend this with `dice_ir`, action-resolution metadata, and
playtest evidence -- those are explicitly out of scope here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .compile_design_character import build_character_sheet
from .compile_design_markdown import build_companion, build_core_rules
from .compile_design_sections import (
    build_parameter_families,
    build_rule_packages,
)
from .design_state import ValidationReport, validate_design_state
from .template import empty_v6


_TITLE_MAX = 60


class CompileBlocked(Exception):
    """Raised when the validator reports any blocking issues.

    Carries the full `ValidationReport` so the caller can persist the
    report and surface a structured response without re-running the
    validator.
    """

    def __init__(self, report: ValidationReport) -> None:
        super().__init__("compile blocked by validator")
        self.report = report


@dataclass
class CompileResult:
    """Outcome of a successful compile."""

    parsed_v6: dict[str, Any]
    report: ValidationReport
    needs_dice_compile: bool = False
    needs_character_ui_compile: bool = False
    sections_emitted: list[str] = field(default_factory=list)


def compile_design_state(
    design_state: dict[str, Any],
    base_v6: dict[str, Any] | None = None,
) -> CompileResult:
    """Compile a DesignState into a runtime `parsed_v6` artifact.

    Raises `CompileBlocked` (with the full `ValidationReport`) when the
    validator surfaces any blocking issues; the caller is responsible
    for persisting the report and not mutating the existing
    `parsed_v6`.
    """
    if not isinstance(design_state, dict):
        raise TypeError("design_state must be a dict")

    report = validate_design_state(design_state)
    if not report.can_compile:
        raise CompileBlocked(report)

    base = base_v6 if isinstance(base_v6, dict) else None
    new_v6: dict[str, Any] = empty_v6()

    sections: list[str] = []
    _emit_meta(new_v6, design_state, base)
    sections.append("meta")

    new_v6["core_rules"] = build_core_rules(design_state)
    sections.append("core_rules")

    new_v6["companion"] = {
        "filename": "world_guide.md",
        "content": build_companion(design_state, new_v6.get("book_title", "")),
    }
    sections.append("companion")

    rule_packages = build_rule_packages(design_state)
    new_v6["rule_packages"] = rule_packages
    if rule_packages:
        sections.append("rule_packages")

    parameter_families = build_parameter_families(design_state)
    new_v6["parameter_families"] = parameter_families
    if parameter_families:
        sections.append("parameter_families")

    character_sheet = build_character_sheet(design_state)
    new_v6["character_sheet"] = character_sheet
    if character_sheet is not None:
        sections.append("character_sheet")

    needs_dice = bool(rule_packages) or bool(parameter_families)
    needs_char_ui = character_sheet is not None

    return CompileResult(
        parsed_v6=new_v6,
        report=report,
        needs_dice_compile=needs_dice,
        needs_character_ui_compile=needs_char_ui,
        sections_emitted=sections,
    )


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


def _emit_meta(
    v6: dict[str, Any],
    state: dict[str, Any],
    base: dict[str, Any] | None,
) -> None:
    base_meta = base or {}
    v6["book_id"] = str(base_meta.get("book_id") or "")

    book_title = _infer_book_title(state) or str(base_meta.get("book_title") or "")
    v6["book_title"] = book_title

    taxonomy = state.get("taxonomy") or {}
    world_mode = (taxonomy.get("setting_type") or "").strip()
    if not world_mode:
        world_mode = str(base_meta.get("world_mode") or "")
    v6["world_mode"] = world_mode

    v6["output_language"] = str(base_meta.get("output_language") or "")


def _infer_book_title(state: dict[str, Any]) -> str:
    brief = state.get("brief") or {}
    concept = (brief.get("concept") or "").strip()
    if not concept:
        return ""
    first_line = concept.splitlines()[0].strip()
    if not first_line:
        return ""
    if len(first_line) <= _TITLE_MAX:
        return first_line
    return first_line[:_TITLE_MAX].rstrip() + "..."


__all__ = ["CompileBlocked", "CompileResult", "compile_design_state"]
