"""Compact summary view of a DesignState for prompts and frontend display.

The summary is intentionally small and stable so it can be embedded in agent
context without consuming a large fraction of the prompt budget.
"""

from __future__ import annotations

from typing import Any

from .validator import ValidationReport, validate_design_state


_PREVIEW_CHARS = 200


def build_summary(
    state: dict[str, Any],
    report: ValidationReport | None = None,
) -> dict[str, Any]:
    """Return a compact dict summarising the current DesignState."""
    if report is None:
        report = validate_design_state(state)

    brief = state.get("brief") or {}
    taxonomy = state.get("taxonomy") or {}
    blueprint = state.get("blueprint") or {}
    core_loop = state.get("core_loop") or {}
    resolution = state.get("resolution_model") or {}
    character = state.get("character_model") or {}
    catalogs = state.get("catalogs") or {}
    procedures = state.get("procedures") or []
    compile_block = state.get("compile") or {}

    summary = {
        "schema_version": state.get("schema_version", 1),
        "phase": state.get("phase", "intake"),
        "brief": {
            "concept_preview": _preview(brief.get("concept", "")),
            "tone": brief.get("tone", ""),
            "complexity": brief.get("complexity", ""),
            "genre": brief.get("genre", ""),
            "assumption_count": len(brief.get("assumptions", []) or []),
        },
        "taxonomy": {
            "genre": taxonomy.get("genre", ""),
            "tone": taxonomy.get("tone", ""),
            "complexity": taxonomy.get("complexity", ""),
            "era": taxonomy.get("era", ""),
            "setting_type": taxonomy.get("setting_type", ""),
        },
        "blueprint": {
            "id": blueprint.get("id", ""),
            "slots_required_count": len(blueprint.get("slots_required") or []),
        },
        "slots": {
            "required": list(report.slots.required),
            "filled": list(report.slots.filled),
            "missing": list(report.slots.missing),
            "drafting": list(report.slots.drafting),
            "progress": report.slots.progress,
        },
        "sections": {
            "core_loop_filled": bool((core_loop.get("summary") or "").strip()),
            "resolution_mechanic_filled": bool(
                (resolution.get("mechanic") or "").strip()
            ),
            "character_attribute_count": len(
                character.get("attributes") or []
            ),
            "procedure_count": len(procedures),
            "catalog_counts": {
                name: len(catalogs.get(name) or [])
                for name in ("skills", "actions", "resources", "gear")
            },
        },
        "issues": {
            "blocking_count": len(report.blocking),
            "warning_count": len(report.warnings),
            "info_count": len(report.info),
            "ready_blockers": list(report.ready_blockers),
            "first_blocking": _first_issue(report.blocking),
        },
        "compile": {
            "status": compile_block.get("status", "idle"),
            "has_error": bool((compile_block.get("error") or "").strip()),
        },
        "can_compile": report.can_compile,
    }
    return summary


def _preview(text: str) -> str:
    if not isinstance(text, str):
        return ""
    if len(text) <= _PREVIEW_CHARS:
        return text
    return text[:_PREVIEW_CHARS].rstrip() + "..."


def _first_issue(issues: list[Any]) -> dict[str, Any] | None:
    if not issues:
        return None
    issue = issues[0]
    if hasattr(issue, "model_dump"):
        return issue.model_dump()
    return dict(issue)


__all__ = ["build_summary"]
