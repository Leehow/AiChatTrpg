"""Stable-text slicing helpers for the chatrpg ruleset adapter.

Pure functions that read a parsed_v6 dict and produce the substrings the
framework's BP1 renderer expects: the chargen pack (template + creation
guide), the Stage-2 companion content (worldview / style guide), and the
knowledge manifest index pointing to `rule_packages` / `parameter_families`
the GM can query via `[SEARCH_RULES]`.

Split out of `trpg_framework_adapter.py` purely for file-size hygiene; this
module is private to the adapter.
"""

from __future__ import annotations

import json
from typing import Any


def _json_dumps(value: Any) -> str:
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(value)


def _compose_chargen(parsed_v6: dict[str, Any]) -> str:
    """Join the character sheet template with the creation guide. Both ship
    full text — see module-level note on truncation."""
    sheet = parsed_v6.get("character_sheet") if isinstance(parsed_v6.get("character_sheet"), dict) else {}
    template = (
        sheet.get("template_content")
        or _json_dumps(sheet.get("template_json"))
        or ""
    )
    guide = str(sheet.get("guide_content") or "")
    return "\n\n".join([s for s in (template, guide) if s])


def _companion_content(parsed_v6: dict[str, Any]) -> str:
    """Read the v6 parser's Stage-2 companion block. For `world_mode=worldview`
    this is `world_guide.md` (worldview text); for `world_mode=style_only`
    this is `style_guide.md`. Either way it's the GM-facing setting text."""
    companion = parsed_v6.get("companion") if isinstance(parsed_v6.get("companion"), dict) else {}
    return str(companion.get("content") or "")


def _entry_count(family: dict[str, Any]) -> int:
    """Count entries in a parameter family. v6 stores them under `.json`
    (parsed structured form) or `.content` (markdown fallback). When `.json`
    is a list we count it directly; when it's a dict we look for the typical
    nesting keys before falling back to top-level keys."""
    blob = family.get("json")
    if isinstance(blob, list):
        return len(blob)
    if isinstance(blob, dict):
        for key in ("entries", "items", "options", "tables", "rows", "values"):
            nested = blob.get(key)
            if isinstance(nested, list):
                return len(nested)
        # dict-of-dicts shape (e.g. {weapon_id: {...}, ...})
        return sum(1 for v in blob.values() if isinstance(v, dict))
    return 0


def _build_manifest_index(parsed_v6: dict[str, Any]) -> str:
    """Compact directory of available `rule_packages` and `parameter_families`
    so the GM can target a specific package_id / family_id via
    `[SEARCH_RULES]`. Bodies stay out of BP1; only ids + titles + counts ship.

    This is chatrpg's port of chatlab's `Knowledge Manifest Index` (see
    `ruleset_runtime_bridge.build_v6_resident_prompt`). Without it, the GM
    has no way to know which family/package to query."""
    parts: list[str] = []

    pkgs = parsed_v6.get("rule_packages") if isinstance(parsed_v6.get("rule_packages"), list) else []
    if pkgs:
        manifest_pkgs = parsed_v6.get("discovery_manifest", {}) or {}
        if isinstance(manifest_pkgs, dict):
            descs = manifest_pkgs.get("detailed_rule_packages") or []
            desc_by_id = {
                str(d.get("package_id") or "").strip(): d
                for d in descs if isinstance(d, dict)
            }
        else:
            desc_by_id = {}
        lines = []
        for pkg in pkgs:
            if not isinstance(pkg, dict):
                continue
            pid = str(pkg.get("package_id") or "").strip()
            if not pid:
                continue
            d = desc_by_id.get(pid) or {}
            title = str(d.get("title") or pid)
            summary = str(d.get("summary") or d.get("load_when") or "").strip()
            line = f"- `{pid}` — {title}"
            if summary:
                line += f": {summary}"
            lines.append(line)
        if lines:
            parts.append("### Rule Packages\n" + "\n".join(lines))

    fams = parsed_v6.get("parameter_families") if isinstance(parsed_v6.get("parameter_families"), list) else []
    if fams:
        lines = []
        for fam in fams:
            if not isinstance(fam, dict):
                continue
            fid = str(fam.get("family_id") or "").strip()
            if not fid:
                continue
            count = _entry_count(fam)
            line = f"- `{fid}`"
            if count:
                line += f" ({count} entries)"
            lines.append(line)
        if lines:
            parts.append("### Parameter Families\n" + "\n".join(lines))

    if not parts:
        return ""
    return (
        "Use `[SEARCH_RULES query=\"<keywords>\"]` to look up package "
        "or family content on demand. The bodies are NOT in this prompt — "
        "you must request the ones you need.\n\n"
        + "\n\n".join(parts)
    )
