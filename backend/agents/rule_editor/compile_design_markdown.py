"""Markdown builders for the design-state compiler.

Engine-pure: no FastAPI / ORM / React imports. Same input -> same output.
Owned by the compiler facade; nothing else should import from here.
"""

from __future__ import annotations

from typing import Any

from .compile_design_character import has_character_content


CATALOG_NAMES: tuple[str, ...] = ("skills", "actions", "resources", "gear")


def build_core_rules(state: dict[str, Any]) -> str:
    """Render the `core_rules` markdown from the design state."""
    lines: list[str] = ["# Core Rules", ""]

    brief = state.get("brief") or {}
    concept = (brief.get("concept") or "").strip()
    if concept:
        lines.append("## Concept")
        lines.append("")
        lines.append(concept)
        lines.append("")

    core_loop = state.get("core_loop") or {}
    cl_summary = (core_loop.get("summary") or "").strip()
    if cl_summary:
        lines.append("## Core Loop")
        lines.append("")
        lines.append(cl_summary)
        lines.append("")
        phases = [
            p for p in (core_loop.get("phases") or [])
            if isinstance(p, str) and p
        ]
        if phases:
            lines.append("Phases: " + ", ".join(phases))
            lines.append("")
        pacing = (core_loop.get("pacing") or "").strip()
        if pacing:
            lines.append(f"Pacing: {pacing}")
            lines.append("")

    resolution = state.get("resolution_model") or {}
    mechanic = (resolution.get("mechanic") or "").strip()
    if mechanic:
        lines.append("## Resolution")
        lines.append("")
        lines.append(f"Mechanic: {mechanic}")
        dice = (resolution.get("dice") or "").strip()
        if dice:
            lines.append(f"Dice: {dice}")
        thresholds = resolution.get("success_thresholds") or []
        if isinstance(thresholds, list) and thresholds:
            lines.append("")
            lines.append("Thresholds:")
            for entry in thresholds:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("name") or "").strip()
                rule = str(entry.get("rule") or "").strip()
                if name or rule:
                    lines.append(f"- **{name or 'rule'}**: {rule}")
        notes = (resolution.get("notes") or "").strip()
        if notes:
            lines.append("")
            lines.append(f"Notes: {notes}")
        lines.append("")

    character = state.get("character_model") or {}
    if has_character_content(character):
        lines.extend(_character_section(character))

    procedures = state.get("procedures") or []
    if procedures:
        lines.append("## Procedures")
        lines.append("")
        for proc in procedures:
            if not isinstance(proc, dict):
                continue
            pid = str(proc.get("id") or "").strip()
            label = str(proc.get("name") or "").strip() or pid
            if pid or label:
                lines.append(f"- **{label or pid}** (`{pid}`)")
        lines.append("")

    catalogs = state.get("catalogs") or {}
    catalog_lines = _summarize_catalogs(catalogs)
    if catalog_lines:
        lines.append("## Catalogs")
        lines.append("")
        lines.extend(catalog_lines)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_companion(state: dict[str, Any], book_title: str) -> str:
    """Render the companion (world / style guide) markdown."""
    lines: list[str] = []
    title = (book_title or "").strip()
    lines.append(f"# {title or 'World Guide'}")
    lines.append("")

    brief = state.get("brief") or {}
    concept = (brief.get("concept") or "").strip()
    if concept:
        lines.append("## Concept")
        lines.append("")
        lines.append(concept)
        lines.append("")

    taxonomy = state.get("taxonomy") or {}
    taxo_lines: list[str] = []
    for key in ("genre", "tone", "complexity", "era", "setting_type"):
        value = (taxonomy.get(key) or "").strip()
        if value:
            taxo_lines.append(f"- **{key}**: {value}")
    if taxo_lines:
        lines.append("## Taxonomy")
        lines.append("")
        lines.extend(taxo_lines)
        lines.append("")

    assumptions = brief.get("assumptions") or []
    assumption_lines = [
        f"- {item.strip()}" for item in assumptions
        if isinstance(item, str) and item.strip()
    ]
    if assumption_lines:
        lines.append("## Assumptions")
        lines.append("")
        lines.extend(assumption_lines)
        lines.append("")

    blueprint = state.get("blueprint") or {}
    bp_id = (blueprint.get("id") or "").strip()
    if bp_id:
        lines.append("## Blueprint")
        lines.append("")
        lines.append(f"- id: `{bp_id}`")
        slots_required = blueprint.get("slots_required") or []
        if isinstance(slots_required, list) and slots_required:
            slot_strs = [str(s) for s in slots_required if isinstance(s, str)]
            if slot_strs:
                lines.append("- slots_required: " + ", ".join(slot_strs))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _summarize_catalogs(catalogs: dict[str, Any]) -> list[str]:
    if not isinstance(catalogs, dict):
        return []
    out: list[str] = []
    for name in CATALOG_NAMES:
        entries = catalogs.get(name) or []
        if not isinstance(entries, list) or not entries:
            continue
        out.append(f"- **{name}**: {len(entries)} entries")
    return out


def _character_section(character: dict[str, Any]) -> list[str]:
    lines: list[str] = ["## Character Model", ""]
    archetypes = [
        a for a in (character.get("archetypes") or [])
        if isinstance(a, str) and a
    ]
    if archetypes:
        lines.append("Archetypes: " + ", ".join(archetypes))
        lines.append("")
    attrs = character.get("attributes") or []
    if attrs:
        lines.append("Attributes:")
        for entry in attrs:
            if not isinstance(entry, dict):
                continue
            eid = str(entry.get("id") or "").strip()
            name = str(entry.get("name") or "").strip()
            if eid and name:
                lines.append(f"- {name} ({eid})")
            elif eid:
                lines.append(f"- {eid}")
            elif name:
                lines.append(f"- {name}")
        lines.append("")
    derived = character.get("derived_stats") or []
    if derived:
        lines.append("Derived stats:")
        for entry in derived:
            if not isinstance(entry, dict):
                continue
            eid = str(entry.get("id") or "").strip()
            name = str(entry.get("name") or "").strip()
            if eid and name:
                lines.append(f"- {name} ({eid})")
            elif eid:
                lines.append(f"- {eid}")
            elif name:
                lines.append(f"- {name}")
        lines.append("")
    progression = (character.get("progression_model") or "").strip()
    if progression:
        lines.append(f"Progression: {progression}")
        lines.append("")
    return lines


__all__ = ["CATALOG_NAMES", "build_core_rules", "build_companion"]
