"""Small pure helpers for the ruleset parse workflow."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HINT_PAD = 50
CUE_CONTEXT = 30
MAX_EXCERPT_CHARS = 400_000


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def title_from_filename(filename: str) -> str:
    stem = Path(filename).stem.strip()
    return stem or "Untitled Ruleset"


def slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return text[:48].strip("-")


def language(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw in {"zh", "zh-cn", "zh_hans", "chinese", "中文"}:
        return "Chinese"
    return "English"


def make_lined_view(markdown: str) -> tuple[str, list[str]]:
    raw_lines = (markdown or "").splitlines()
    lined = "\n".join(f"[L{idx:06d}] {line}" for idx, line in enumerate(raw_lines, 1))
    return lined, raw_lines


def limit_descriptors(items: list[Any], key: str, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        ident = str(item.get(key) or "").strip()
        if not ident or ident in seen:
            continue
        seen.add(ident)
        out.append(dict(item))
        if len(out) >= limit:
            break
    return out


def build_excerpt(
    lined_view: str,
    raw_lines: list[str],
    descriptor: dict[str, Any],
) -> tuple[str, bool, dict[str, Any]]:
    ranges = _line_ranges(descriptor.get("line_hints"), len(raw_lines))
    cue_ranges = _cue_ranges(raw_lines, descriptor.get("source_cues") or [])
    merged = _merge_ranges(ranges + cue_ranges, len(raw_lines))
    if not merged:
        excerpt = lined_view
        narrowed = False
    else:
        lines = lined_view.splitlines()
        chunks = ["\n".join(lines[start - 1:end]) for start, end in merged]
        excerpt = "\n\n[...omitted...]\n\n".join(chunks)
        narrowed = True
    if len(excerpt) > MAX_EXCERPT_CHARS:
        excerpt = excerpt[:MAX_EXCERPT_CHARS] + "\n\n[...truncated...]"
    return excerpt, narrowed, {
        "hint_ranges": [list(r) for r in ranges],
        "cue_ranges": [list(r) for r in cue_ranges],
        "merged_ranges": [list(r) for r in merged],
        "char_count": len(excerpt),
    }


def normalize_manifest(raw: Any, *, book_id: str, title: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    manifest = dict(raw)
    manifest["book_id"] = str(manifest.get("book_id") or book_id)
    manifest["book_title"] = str(manifest.get("book_title") or title)
    manifest["world_mode"] = "fiction"
    manifest["resident"] = {
        "core_file": "core_rules.md",
        "companion_file": "world_guide.md",
    }
    for key in ("detailed_rule_packages", "parameter_families", "aliases"):
        if not isinstance(manifest.get(key), list):
            manifest[key] = []
    cs = manifest.get("character_sheet_package")
    if not isinstance(cs, dict):
        cs = {"present": True}
    cs.setdefault("present", True)
    cs.setdefault("template_file", "character_sheet/character_sheet_template.json")
    cs.setdefault("guide_file", "character_sheet/character_creation_guide.md")
    manifest["character_sheet_package"] = cs
    return manifest


def assemble_final_manifest(
    discovery: dict[str, Any],
    packages: list[dict[str, Any]],
    families: list[dict[str, Any]],
    character_sheet: dict[str, Any],
) -> dict[str, Any]:
    pkg_ids = {p.get("package_id") for p in packages if p.get("content") and not p.get("error")}
    fam_ids = {
        f.get("family_id") for f in families
        if not f.get("error") and not f.get("should_remain_markdown")
    }
    slim_packages = [
        _keep(p, ("package_id", "title", "resident_presence", "summary", "load_when", "contains", "file"))
        for p in discovery.get("detailed_rule_packages", [])
        if isinstance(p, dict) and p.get("package_id") in pkg_ids
    ]
    slim_families = [
        _keep(f, ("family_id", "title", "summary", "entry_definition", "family_specific_fields", "file"))
        for f in discovery.get("parameter_families", [])
        if isinstance(f, dict) and f.get("family_id") in fam_ids
    ]
    aliases = [a for a in discovery.get("aliases", []) if isinstance(a, dict)]
    return {
        "book_id": discovery.get("book_id"),
        "book_title": discovery.get("book_title"),
        "world_mode": "fiction",
        "resident": discovery.get("resident") or {},
        "detailed_rule_packages": slim_packages,
        "parameter_families": slim_families,
        "character_sheet_package": {
            "present": bool(character_sheet.get("template_json")),
            "template_file": "character_sheet/character_sheet_template.json",
            "guide_file": "character_sheet/character_creation_guide.md",
        },
        "aliases": aliases,
    }


def _line_ranges(raw: Any, total: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        try:
            start, end = int(item[0]), int(item[1])
        except (TypeError, ValueError):
            continue
        if start <= 0 or end <= 0:
            continue
        if start > end:
            start, end = end, start
        out.append((max(1, start - HINT_PAD), min(total, end + HINT_PAD)))
    return out


def _cue_ranges(raw_lines: list[str], cues: list[Any]) -> list[tuple[int, int]]:
    terms = [str(c).strip() for c in cues if len(str(c).strip()) >= 3]
    if not terms:
        return []
    patterns = [re.compile(re.escape(term), re.I) for term in terms[:20]]
    total = len(raw_lines)
    out: list[tuple[int, int]] = []
    for idx, line in enumerate(raw_lines, 1):
        if any(p.search(line) for p in patterns):
            out.append((max(1, idx - CUE_CONTEXT), min(total, idx + CUE_CONTEXT)))
    return out


def _merge_ranges(ranges: list[tuple[int, int]], total: int) -> list[tuple[int, int]]:
    valid = sorted((max(1, s), min(total, e)) for s, e in ranges if s <= e and total > 0)
    merged: list[tuple[int, int]] = []
    for start, end in valid:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _keep(src: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: src[key] for key in keys if key in src}
