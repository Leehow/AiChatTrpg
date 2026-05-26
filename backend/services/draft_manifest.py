"""Slim, always-loaded draft manifest — chatrpg's analogue of chatlab's
`knowledge_manifest`.

Why this exists:
    Both rule editor agents (the design agent + the dice agent) used to
    work blind to each other. The design agent could pick a Cyberpunk
    1-5 attribute scale while the dice agent compiled CoC d100
    procedures against those tiny values, producing a ruleset where
    every roll fails. The fix is the same as chatlab's: bake a slim
    index of EVERYTHING already in the draft (scenarios, families,
    character_sheet attribute scale, dice procedures) into both agents'
    system prompts at the start of every turn.

Output is also durable: `promote_draft` copies the manifest into
`Ruleset.parsed_v6.knowledge_manifest`, so the export path can ship it
alongside the published artifact (matching chatlab's
`knowledge_manifest.json`).

This file is pure (parsed_v6 in → dict out). Caching is per-call via
`functools.lru_cache` keyed on (draft_id, draft.updated_at). Drafts
mutate often, so the cache turns over fast — keep it small.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_draft_manifest(parsed_v6: dict[str, Any] | None) -> dict[str, Any]:
    """Slim runtime index of a draft's `parsed_v6` artifact.

    Used by the rule editor / dice agents at turn start, and stashed on
    promoted rulesets so the export pipeline can ship it.
    """
    parsed = parsed_v6 or {}
    return {
        "meta": _meta(parsed),
        "core_rules": _core_rules_summary(parsed),
        "companion": _companion_summary(parsed),
        "scenarios": _scenarios_index(parsed),
        "parameter_families": _families_index(parsed),
        "character_sheet": _sheet_summary(parsed),
        "dice_ir": _dice_summary(parsed),
    }


def render_manifest_for_prompt(manifest: dict[str, Any]) -> str:
    """Render the manifest as a fenced JSON block for system-prompt injection.

    Mirrors chatlab's `build_v6_resident_prompt` block. Both agents see
    the same shape so they can cross-reference each other's work.
    """
    body = json.dumps(manifest, ensure_ascii=False, indent=2)
    return (
        "## Draft Manifest (auto-loaded)\n"
        "This index summarizes everything already designed in the "
        "current draft. Use the `package_id` / `family_id` / "
        "`procedure_id` values verbatim when referencing existing "
        "content. Use `character_sheet.attribute_scale_hint` to choose "
        "a compatible dice procedure.\n\n"
        f"```json\n{body}\n```"
    )


def manifest_block_for_draft(draft: Any) -> str:
    """Convenience: build manifest from a `RulesetDraft` ORM row, with
    LRU caching keyed on (id, updated_at). Returns the rendered block.

    Drafts are small (kBs) and rebuild is cheap; the cache mainly
    saves the JSON serialise + heuristics on multi-iteration agent
    turns within the same draft state.
    """
    if draft is None:
        return ""
    key = (
        str(getattr(draft, "id", "")),
        str(getattr(draft, "updated_at", "")),
    )
    parsed = draft.parsed_v6 if isinstance(draft.parsed_v6, dict) else {}
    return _cached_render(key, json.dumps(parsed, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Field builders (private)
# ---------------------------------------------------------------------------


def _meta(parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        "book_title": str(parsed.get("book_title") or ""),
        "world_mode": str(parsed.get("world_mode") or ""),
        "output_language": str(parsed.get("output_language") or ""),
    }


def _core_rules_summary(parsed: dict[str, Any]) -> dict[str, Any]:
    text = str(parsed.get("core_rules") or "")
    return {
        "designed": bool(text.strip()),
        "chars": len(text),
    }


def _companion_summary(parsed: dict[str, Any]) -> dict[str, Any]:
    comp = parsed.get("companion") if isinstance(parsed.get("companion"), dict) else {}
    text = str(comp.get("content") or "")
    return {
        "designed": bool(text.strip()),
        "chars": len(text),
        "filename": str(comp.get("filename") or ""),
    }


def _scenarios_index(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pkg in parsed.get("rule_packages") or []:
        if not isinstance(pkg, dict):
            continue
        content = str(pkg.get("content") or "")
        out.append({
            "package_id": str(pkg.get("package_id") or pkg.get("id") or ""),
            "title": str(pkg.get("title") or ""),
            "summary": _one_line(content),
            "chars": len(content),
        })
    return out


def _families_index(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fam in parsed.get("parameter_families") or []:
        if not isinstance(fam, dict):
            continue
        entries = (fam.get("json") or {}).get("entries") or []
        if not isinstance(entries, list):
            entries = []
        # Discover the field shape from the first non-empty entry so the
        # agent knows what to fill in future entries.
        shape: list[str] = []
        for e in entries:
            if isinstance(e, dict) and e:
                shape = sorted(e.keys())
                break
        # Slim entries-index: just (id, name) per entry — agent gets the
        # roster, full bodies require a read_draft(section="parameters")
        # call.
        slim_entries: list[dict[str, str]] = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            slim_entries.append({
                "id": str(e.get("id") or e.get("name") or ""),
                "name": str(e.get("name") or e.get("id") or ""),
            })
        out.append({
            "family_id": str(fam.get("family_id") or fam.get("id") or ""),
            "title": str(fam.get("title") or ""),
            "summary": _one_line(str(fam.get("content") or "")),
            "entry_count": len(entries),
            "entry_shape": shape,
            "entries_index": slim_entries,
        })
    return out


def _sheet_summary(parsed: dict[str, Any]) -> dict[str, Any]:
    sheet = parsed.get("character_sheet") if isinstance(parsed.get("character_sheet"), dict) else {}
    tj = sheet.get("template_json") if isinstance(sheet.get("template_json"), dict) else {}
    attrs = tj.get("attributes") if isinstance(tj.get("attributes"), dict) else {}
    skills = tj.get("skills") if isinstance(tj.get("skills"), list) else []
    guide = str(sheet.get("guide_content") or "")
    return {
        "designed": bool(tj),
        "template_keys": sorted(tj.keys()),
        "attribute_keys": list(attrs.keys()),
        "attribute_scale_hint": _attribute_scale_hint(attrs),
        "skills_count": len(skills),
        "guide_chars": len(guide),
    }


def _dice_summary(parsed: dict[str, Any]) -> dict[str, Any]:
    dir_ = parsed.get("dice_ir") if isinstance(parsed.get("dice_ir"), dict) else {}
    pkg = dir_.get("package") if isinstance(dir_.get("package"), dict) else {}
    compiled = pkg.get("compiled") if isinstance(pkg.get("compiled"), dict) else {}
    specs = compiled.get("check_specs") if isinstance(compiled.get("check_specs"), list) else []
    out_specs: list[dict[str, Any]] = []
    for s in specs:
        if not isinstance(s, dict):
            continue
        out_specs.append({
            "procedure_id": str(s.get("procedure_id") or ""),
            "name": str(s.get("name") or ""),
            "engine": str((s.get("check_spec") or {}).get("engine") or s.get("engine") or ""),
            "expects_skill_range": _engine_skill_range_hint(
                str((s.get("check_spec") or {}).get("engine") or s.get("engine") or ""),
            ),
            "validation_ok": bool((s.get("validation") or {}).get("ok")),
        })
    return {
        "compiled": bool(out_specs),
        "default_procedure_id": str(compiled.get("default_procedure_id") or ""),
        "specs": out_specs,
    }


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------


def _attribute_scale_hint(attrs: dict[str, Any]) -> str:
    """Classify the attribute numeric range so a dice agent can warn
    about scale mismatches before compiling.

    Returns one of:
    - "low_integer" — small ints expected (≤10), e.g. CP2020 / WoD
    - "percentile" — 0-99 expected, e.g. CoC 7e
    - "modifier" — small signed mods (-5..+5), e.g. D&D 5e
    - "unspecified" — template uses null / non-numeric placeholders
    - "empty" — no attributes declared
    """
    if not attrs:
        return "empty"
    samples: list[float] = []
    for v in attrs.values():
        n = _extract_default_number(v)
        if n is not None:
            samples.append(n)
    if not samples:
        return "unspecified"
    lo, hi = min(samples), max(samples)
    if -10 <= lo <= -1 and hi <= 10:
        return "modifier"
    if hi <= 10:
        return "low_integer"
    if hi <= 99:
        return "percentile"
    return "unspecified"


def _extract_default_number(v: Any) -> float | None:
    """Pull a representative numeric value out of an attribute slot.

    Templates write attribute slots in several shapes:
    - `50` (raw number)
    - `{value: 50}` / `{value: null}`
    - `{default: 50}`
    - `{base: 50}`
    """
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        for k in ("value", "default", "base", "score"):
            n = v.get(k)
            if isinstance(n, (int, float)):
                return float(n)
    return None


def _engine_skill_range_hint(engine: str) -> str:
    """Tell the agent what skill value range each engine expects.

    Lets the dice agent cross-check vs `attribute_scale_hint` before
    compiling a new procedure.
    """
    e = (engine or "").lower()
    if "d100" in e or "coc" in e or "brp" in e or "percentile" in e:
        return "0-99 (percentile / d100)"
    if "d20" in e:
        return "small modifier (e.g. -2..+10)"
    if "pbta" in e or "2d6" in e:
        return "small stat (-2..+3)"
    if "pool" in e:
        return "die count (1-10)"
    if "custom_llm" in e:
        return "varies (LLM-judged)"
    if "generic_resolution" in e:
        return "configurable per spec"
    return "unspecified"


def _one_line(text: str, max_len: int = 80) -> str:
    """First non-empty line, trimmed to `max_len`."""
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("# ").strip()
        if line:
            return line if len(line) <= max_len else line[: max_len - 1] + "…"
    return ""


# ---------------------------------------------------------------------------
# LRU cache helper
# ---------------------------------------------------------------------------


@lru_cache(maxsize=64)
def _cached_render(_key: tuple[str, str], parsed_json: str) -> str:
    """LRU cache wrapper. Key drives invalidation; parsed_json is
    serialised so it's hashable.
    """
    try:
        parsed = json.loads(parsed_json)
    except Exception:
        parsed = {}
    return render_manifest_for_prompt(build_draft_manifest(parsed))
