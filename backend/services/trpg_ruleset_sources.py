"""Build grep-searchable sources from a ruleset's ``parsed_v6`` blob.

The grep retrieval agent expects a flat list of
``{id, label, source_type, content}`` records. This module knows how to
walk parsed_v6 and emit:

- ``rule_package:<package_id>`` — one source per rule_package, with the
  full markdown body. The GM searches these for procedures (combat,
  investigation, sanity, etc.).
- ``param_family:<family_id>`` — one source per parameter_family with
  schema-only content (title + indexing fields + safety note). Useful as
  a directory pointer.
- ``param_entry:<family_id>:<entry_id>`` — one source per concrete entry
  (Knife, Small / Reporter / etc.). Content is the entry serialized as
  searchable text plus the pre-built ``search_text`` field when present.
  This is where the agent should land for canonical weapon stats.
- ``companion`` — the world-mode scene guide (worldview).

Entries get serialized with both Chinese and English fields side-by-side
when available so the bilingual grep loop can land hits regardless of
which language the user typed in.
"""

from __future__ import annotations

import json
from typing import Any


def _flatten_value(value: Any) -> str:
    """Render a JSON value as a short, grep-friendly string."""
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return ", ".join(_flatten_value(v) for v in value if v not in (None, ""))
    if isinstance(value, dict):
        # Keep dicts compact but readable.
        return json.dumps(value, ensure_ascii=False)
    return str(value)


# Keys we surface with explicit labels per parameter-family entry. Order
# matters — it's how the rendered text reads top-to-bottom. Keep this
# narrow: the goal is grepability, not full JSON dump.
_ENTRY_LABELED_KEYS: tuple[tuple[str, str], ...] = (
    ("name", "Name"),
    ("display_name", "Display name"),
    ("aliases", "Aliases"),
    ("category", "Category"),
    ("era_group", "Era"),
    ("era_label", "Era label"),
    ("skill", "Skill"),
    ("damage", "Damage"),
    ("range", "Range"),
    ("attacks", "Attacks"),
    ("malfunction", "Malfunction"),
    ("ammo", "Ammo"),
    ("magazine", "Magazine"),
    ("cost", "Cost"),
    ("availability", "Availability"),
    ("tags", "Tags"),
    ("notes", "Notes"),
    ("description", "Description"),
)


def _format_param_entry(family_id: str, entry: dict[str, Any]) -> str:
    """Serialize one parameter_family entry for grep + LLM consumption."""
    out: list[str] = []
    out.append(f"Family: {family_id}")
    for key, label in _ENTRY_LABELED_KEYS:
        if key not in entry:
            continue
        value = entry.get(key)
        rendered = _flatten_value(value)
        if rendered:
            out.append(f"{label}: {rendered}")
    # Pre-built search line (Chinese-language summary the parser ships).
    # Append last so the labelled fields come first.
    search_text = str(entry.get("search_text") or "").strip()
    if search_text:
        out.append(f"Search hint: {search_text}")
    # Any other flat fields (skill_modifier, encumbrance, weight, etc.)
    # we didn't enumerate above. Keep them so the LLM has the full
    # picture if it needs to read_source.
    skip = {k for k, _ in _ENTRY_LABELED_KEYS} | {
        "id", "search_text", "llm_selection_hint", "era_tags", "book_id",
    }
    for key, value in entry.items():
        if key in skip:
            continue
        rendered = _flatten_value(value)
        if rendered:
            out.append(f"{key}: {rendered}")
    return "\n".join(out)


def _entry_label(family_id: str, entry: dict[str, Any]) -> str:
    name = str(entry.get("name") or entry.get("display_name") or entry.get("id") or "").strip()
    return f"{family_id} / {name}" if name else family_id


def _entry_id_part(entry: dict[str, Any], idx: int) -> str:
    raw = str(entry.get("id") or "").strip()
    if raw:
        # Take the trailing slug part of dotted ids
        # (e.g. "<book>.weapon.modern.folding_knife" → "folding_knife").
        last = raw.rsplit(".", 1)[-1]
        return last or raw
    return f"entry_{idx}"


def _build_param_family_summary(fam: dict[str, Any]) -> str:
    """Schema-only summary of a parameter family (no entries) — used as
    a directory-style source so the agent can grep the family title."""
    lines: list[str] = []
    family_id = str(fam.get("family_id") or "").strip()
    title = str(fam.get("title") or "").strip()
    if title:
        lines.append(f"Title: {title}")
    if family_id:
        lines.append(f"Family ID: {family_id}")
    indexing = fam.get("indexing_fields")
    if isinstance(indexing, list) and indexing:
        lines.append(f"Indexing fields: {', '.join(str(x) for x in indexing)}")
    note = str(fam.get("safety_note") or "").strip()
    if note:
        lines.append(f"Safety note: {note}")
    sel = str(fam.get("llm_selection_note") or "").strip()
    if sel:
        lines.append(f"Selection note: {sel}")
    entries = fam.get("entries")
    if isinstance(entries, list):
        lines.append(f"Entry count: {len(entries)}")
    return "\n".join(lines)


def _walk_parameter_families(
    parsed_v6: dict[str, Any],
    *,
    max_entries_per_family: int,
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    fams = parsed_v6.get("parameter_families")
    if not isinstance(fams, list):
        return out
    for fam in fams:
        if not isinstance(fam, dict):
            continue
        # Real shape: fam["json"]["entries"] = [...]. Fallback: fam["json"]
        # may itself be a list (older cuts).
        body = fam.get("json")
        family_id = str(fam.get("family_id") or "").strip()
        if not family_id:
            continue

        # Family-level summary source.
        if isinstance(body, dict):
            summary = _build_param_family_summary(body)
        else:
            summary = f"Family ID: {family_id}"
        if summary:
            out.append({
                "id": f"param_family:{family_id}",
                "source_type": "param_family",
                "label": f"Parameter Family / {family_id}",
                "content": summary,
            })

        # Entry-level sources.
        entries: list[Any] = []
        if isinstance(body, dict):
            inner = body.get("entries")
            if isinstance(inner, list):
                entries = inner
        elif isinstance(body, list):
            entries = body
        for idx, entry in enumerate(entries[:max_entries_per_family]):
            if not isinstance(entry, dict):
                continue
            slug = _entry_id_part(entry, idx)
            content = _format_param_entry(family_id, entry)
            if not content:
                continue
            out.append({
                "id": f"param_entry:{family_id}:{slug}",
                "source_type": "param_entry",
                "label": f"Parameter Entry / {_entry_label(family_id, entry)}",
                "content": content,
            })
    return out


def _walk_rule_packages(parsed_v6: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    packs = parsed_v6.get("rule_packages")
    if not isinstance(packs, list):
        return out
    for pack in packs:
        if not isinstance(pack, dict):
            continue
        package_id = str(pack.get("package_id") or "").strip()
        if not package_id:
            continue
        title = str(pack.get("title") or "").strip()
        # Body. v6 cuts have either `content` (full markdown) or just a
        # `summary`. Concatenate both so grep has the most surface.
        parts: list[str] = []
        if title:
            parts.append(f"# {title}")
        summary = str(pack.get("summary") or "").strip()
        if summary:
            parts.append(summary)
        content = str(pack.get("content") or "").strip()
        if content:
            parts.append(content)
        body = "\n\n".join(parts).strip()
        if not body:
            continue
        out.append({
            "id": f"rule_package:{package_id}",
            "source_type": "rule_package",
            "label": f"Rule Package / {package_id}{' / ' + title if title else ''}",
            "content": body,
        })
    return out


def _walk_companion(parsed_v6: dict[str, Any]) -> list[dict[str, str]]:
    comp = parsed_v6.get("companion")
    if not isinstance(comp, dict):
        return []
    content = str(comp.get("content") or "").strip()
    if not content:
        return []
    return [{
        "id": "companion",
        "source_type": "companion",
        "label": "Worldview / Companion",
        "content": content,
    }]


def build_ruleset_sources(
    parsed_v6: dict[str, Any] | None,
    *,
    max_entries_per_family: int = 200,
) -> list[dict[str, str]]:
    """Return a flat list of grep-searchable sources from a parsed_v6 blob.

    Order: rule_packages first (procedures), then param_family directory
    entries, then per-entry records, then the companion worldview text.
    The agent grep-search results show the first hit per source so the
    ordering matters when multiple sources contain similar wording —
    procedure context should land before raw catalog entries.
    """
    if not isinstance(parsed_v6, dict) or not parsed_v6:
        return []
    sources: list[dict[str, str]] = []
    sources.extend(_walk_rule_packages(parsed_v6))
    sources.extend(
        _walk_parameter_families(parsed_v6, max_entries_per_family=max_entries_per_family)
    )
    sources.extend(_walk_companion(parsed_v6))
    return sources
