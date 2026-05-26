"""Character-sheet helpers for the design-state compiler.

Engine-pure: no FastAPI / ORM / React imports. Same input -> same output.
The public surface is consumed only by `compile_design.py` and the
markdown helpers in `compile_design_markdown.py`; nothing else should
import from here directly.
"""

from __future__ import annotations

from typing import Any


def has_character_content(character: dict[str, Any]) -> bool:
    """Return True when the character_model carries enough to compile.

    Used both by the core-rules markdown builder (to decide whether to
    emit a "Character Model" section) and the character_sheet builder.
    """
    if not isinstance(character, dict):
        return False
    if character.get("attributes"):
        return True
    if character.get("derived_stats"):
        return True
    if character.get("archetypes"):
        return True
    if (character.get("progression_model") or "").strip():
        return True
    return False


def build_character_sheet(state: dict[str, Any]) -> dict[str, Any] | None:
    """Build the runtime character_sheet dict, or None when empty."""
    character = state.get("character_model") or {}
    if not has_character_content(character):
        return None

    template_json: dict[str, Any] = {
        "identity": {"name": "", "archetype": ""},
        "attributes": {},
        "derived": {},
        "skills": [],
    }

    for entry in character.get("attributes") or []:
        if not isinstance(entry, dict):
            continue
        eid = str(entry.get("id") or "").strip()
        if not eid:
            continue
        template_json["attributes"][eid] = {
            "name": str(entry.get("name") or eid),
            "default": entry.get("default"),
        }
    for entry in character.get("derived_stats") or []:
        if not isinstance(entry, dict):
            continue
        eid = str(entry.get("id") or "").strip()
        if not eid:
            continue
        template_json["derived"][eid] = {
            "name": str(entry.get("name") or eid),
        }

    catalogs = state.get("catalogs") or {}
    skills = catalogs.get("skills") if isinstance(catalogs, dict) else []
    if isinstance(skills, list):
        for entry in skills:
            if not isinstance(entry, dict):
                continue
            sid = str(entry.get("id") or "").strip()
            if not sid:
                continue
            template_json["skills"].append({
                "id": sid,
                "name": str(entry.get("name") or sid),
            })

    archetypes = [
        a for a in (character.get("archetypes") or [])
        if isinstance(a, str) and a
    ]
    if archetypes:
        template_json["identity"]["archetype_options"] = list(archetypes)

    return {
        "template_json": template_json,
        "template_filename": "character_sheet.json",
        "guide_content": _render_character_guide(character),
        "guide_filename": "character_guide.md",
    }


def _render_character_guide(character: dict[str, Any]) -> str:
    lines: list[str] = ["# Character Guide", ""]
    archetypes = [
        a for a in (character.get("archetypes") or [])
        if isinstance(a, str) and a
    ]
    if archetypes:
        lines.append("## Archetypes")
        lines.append("")
        for a in archetypes:
            lines.append(f"- {a}")
        lines.append("")
    attrs = character.get("attributes") or []
    if attrs:
        lines.append("## Attributes")
        lines.append("")
        for entry in attrs:
            if not isinstance(entry, dict):
                continue
            eid = str(entry.get("id") or "").strip()
            name = str(entry.get("name") or eid).strip()
            desc = str(entry.get("description") or "").strip()
            if eid:
                head = f"- **{name or eid}** (`{eid}`)"
                lines.append(f"{head} -- {desc}" if desc else head)
        lines.append("")
    derived = character.get("derived_stats") or []
    if derived:
        lines.append("## Derived Stats")
        lines.append("")
        for entry in derived:
            if not isinstance(entry, dict):
                continue
            eid = str(entry.get("id") or "").strip()
            name = str(entry.get("name") or eid).strip()
            if eid:
                lines.append(f"- **{name or eid}** (`{eid}`)")
        lines.append("")
    progression = (character.get("progression_model") or "").strip()
    if progression:
        lines.append("## Progression")
        lines.append("")
        lines.append(progression)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["has_character_content", "build_character_sheet"]
