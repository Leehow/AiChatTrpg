"""Stage 0 parameter-family normalization for the v6 ruleset workflow.

`apply_stage0_parameter_plan` reconciles the discovery manifest's
`parameter_families` list with the catalog-like sections that Stage 0's
source preparation already split out, so Stage 5 has the right work units.
"""

from __future__ import annotations

from typing import Any


def apply_stage0_parameter_plan(
    discovery: dict[str, Any],
    *,
    prepared: Any,
) -> dict[str, Any]:
    """Ensure Stage 0's catalog splits survive manifest discovery."""
    out = dict(discovery or {})
    source_families = [
        dict(f)
        for f in (out.get("parameter_families") or [])
        if isinstance(f, dict)
    ]
    stage0_sections = list(getattr(prepared, "parameter_sections", []) or [])
    stage0_by_id = {
        str(section.family_id or "").strip(): section
        for section in stage0_sections
        if str(section.family_id or "").strip()
    }
    aliases = {
        "occupations": {"occupation", "occupations", "role"},
        "skills": {"skill", "skills"},
        "phobias": {"phobia", "phobias"},
        "manias": {"mania", "manias"},
        "mythos_tomes": {"mythos_tome", "mythos_tomes", "book", "tome"},
        "spells": {"spell", "spells"},
        "artifacts": {"artifact", "artifacts"},
        "equipment_1920s": {"equipment_1920s", "equipment", "item_1920s", "items_1920s"},
        "equipment_modern": {"equipment_modern", "item_modern", "items_modern"},
        "weapons": {"weapon", "weapons"},
        "mythos_monsters": {"mythos_monster", "mythos_monsters", "monster"},
        "mythos_deities": {"mythos_deity", "mythos_deities", "deity"},
        "traditional_horrors": {"traditional_horror", "traditional_horrors"},
        "beasts": {"beast", "beasts"},
    }
    alias_to_canonical = _unique_alias_map(aliases)
    banned_mega_ids = {
        "creature",
        "creatures",
        "monsters",
        "monsters_beasts_gods",
    }
    generic_table_ids = {
        "item",
        "items",
        "gear",
        "equipment_catalog",
        "table_price",
        "price_table",
    }

    families: list[dict[str, Any]] = []
    seen: set[str] = set()
    for family in source_families:
        raw_id = str(family.get("family_id") or "").strip()
        if not raw_id or raw_id in banned_mega_ids:
            continue
        canonical = alias_to_canonical.get(raw_id)
        if canonical and canonical in stage0_by_id:
            if canonical in seen:
                continue
            families.append(_stage0_family_descriptor(stage0_by_id[canonical], base=family))
            seen.add(canonical)
            continue
        if raw_id in generic_table_ids and _family_overlaps_stage0(family, stage0_sections):
            continue
        if raw_id in seen:
            continue
        families.append(family)
        seen.add(raw_id)

    for section in stage0_sections:
        family_id = str(section.family_id or "").strip()
        if not family_id or family_id in seen:
            continue
        families.append(_stage0_family_descriptor(section))
        seen.add(family_id)

    out["parameter_families"] = families
    return out


def _unique_alias_map(aliases: dict[str, set[str]]) -> dict[str, str]:
    seen: dict[str, str] = {}
    ambiguous: set[str] = set()
    for canonical, names in aliases.items():
        for name in {*names, canonical}:
            if name in seen and seen[name] != canonical:
                ambiguous.add(name)
            else:
                seen[name] = canonical
    for name in ambiguous:
        seen.pop(name, None)
    return seen


def _stage0_family_descriptor(
    section: Any,
    *,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    family_id = str(section.family_id or "").strip()
    descriptor = dict(base or {})
    descriptor.update({
        "family_id": family_id,
        "title": getattr(section, "title", "") or descriptor.get("title") or family_id,
        "summary": (
            "Stage 0 split this catalog-like source out of the resident "
            "rules so Stage 5 can extract exact entries."
        ),
        "entry_definition": descriptor.get("entry_definition")
        or "Structured lookup entries extracted from the source section.",
        "source_cues": _dedupe_strings([
            getattr(section, "title", "") or "",
            *(descriptor.get("source_cues") or []),
        ]),
        "line_hints": [[section.start_line, section.end_line]],
        "file": f"parameters/{family_id}.json",
    })
    native_labels = _dedupe_strings([
        getattr(section, "title", "") or "",
        *(descriptor.get("native_labels") or []),
    ])
    if native_labels:
        descriptor["native_labels"] = native_labels
    descriptor.setdefault("estimated_count", 0)
    descriptor.setdefault("family_specific_fields", [])
    return descriptor


def _family_overlaps_stage0(
    family: dict[str, Any],
    sections: list[Any],
) -> bool:
    hints = family.get("line_hints") or []
    ranges: list[tuple[int, int]] = []
    if isinstance(hints, list):
        for hint in hints:
            if not isinstance(hint, (list, tuple)) or len(hint) != 2:
                continue
            try:
                start = int(hint[0])
                end = int(hint[1])
            except (TypeError, ValueError):
                continue
            if start > end:
                start, end = end, start
            ranges.append((start, end))
    for start, end in ranges:
        for section in sections:
            if start <= section.end_line and section.start_line <= end:
                return True
    return False


def _dedupe_strings(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        out.append(text)
        seen.add(text)
    return out
