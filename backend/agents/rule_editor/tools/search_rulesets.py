"""Tools to search / read / grep across the user's rulesets."""

from __future__ import annotations

import json as _json
import re
from typing import Any

from sqlalchemy import select

from orm.models import Ruleset

from .base import (
    FunctionTool,
    ToolContext,
    ToolError,
    ToolResult,
    make_object_schema,
)


async def _search_my_rulesets(
    ctx: ToolContext, args: dict[str, Any],
) -> ToolResult:
    query = str(args.get("query") or "").strip().lower()
    limit = max(1, min(int(args.get("limit") or 30), 50))
    res = await ctx.db.execute(
        select(Ruleset)
        .where(
            (Ruleset.owner_id == ctx.owner_id) | (Ruleset.is_shared == True)  # noqa: E712
        )
        .order_by(Ruleset.updated_at.desc())
    )
    items: list[dict[str, Any]] = []
    for r in res.scalars().all():
        haystack = f"{r.book_title} {r.world_mode} {r.book_id}".lower()
        if query and query not in haystack:
            continue
        items.append({
            "id": r.id,
            "book_title": r.book_title,
            "world_mode": r.world_mode,
            "owner_id": r.owner_id,
            "is_shared": bool(r.is_shared),
            "scenarios": [
                p.get("package_id", "")
                for p in ((r.parsed_v6 or {}).get("rule_packages") or [])
                if isinstance(p, dict)
            ],
            "families": [
                f.get("family_id", "")
                for f in ((r.parsed_v6 or {}).get("parameter_families") or [])
                if isinstance(f, dict)
            ],
            "updated_at": r.updated_at.isoformat(),
        })
        if len(items) >= limit:
            break
    return ToolResult({"items": items, "total": len(items)})


search_rulesets_tool = FunctionTool(
    name="search_my_rulesets",
    description=(
        "List rulesets visible to the user (mine + shared). Optional "
        "`query` does case-insensitive substring match on book_title / "
        "world_mode / book_id. Use BEFORE designing a 'system like X' "
        "to check if X already exists in the user's library."
    ),
    json_schema=make_object_schema({
        "query": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    }),
    is_write=False,
    executor=_search_my_rulesets,
)


async def _read_ruleset(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    rs_id = str(args.get("ruleset_id") or "").strip()
    if not rs_id:
        raise ToolError("missing_ruleset_id", "ruleset_id is required")
    rs = await ctx.db.get(Ruleset, rs_id)
    if rs is None or (rs.owner_id != ctx.owner_id and not rs.is_shared):
        raise ToolError("not_found", "ruleset not visible to this user")
    sections = args.get("sections") or [
        "meta", "core", "scenarios_summary", "families_summary",
    ]
    sections = [str(s) for s in sections if isinstance(s, str)]
    parsed = rs.parsed_v6 or {}
    out: dict[str, Any] = {"id": rs.id, "book_title": rs.book_title}
    if "meta" in sections:
        out["meta"] = {
            "book_id": parsed.get("book_id", ""),
            "world_mode": parsed.get("world_mode", ""),
            "output_language": parsed.get("output_language", ""),
        }
    if "core" in sections:
        core = str(parsed.get("core_rules") or "")
        out["core_rules"] = core[:6000]
        out["core_rules_truncated"] = len(core) > 6000
    if "scenarios_summary" in sections:
        out["scenarios"] = [
            {
                "package_id": p.get("package_id", ""),
                "filename": p.get("filename", ""),
                "content_chars": len(str(p.get("content") or "")),
                "preview": str(p.get("content") or "")[:300],
            }
            for p in (parsed.get("rule_packages") or [])
            if isinstance(p, dict)
        ]
    if "scenarios_full" in sections:
        out["scenarios"] = parsed.get("rule_packages") or []
    if "families_summary" in sections:
        out["parameter_families"] = [
            {
                "family_id": f.get("family_id", ""),
                "entries_count": len((f.get("json") or {}).get("entries") or []),
                "should_remain_markdown": bool(f.get("should_remain_markdown")),
            }
            for f in (parsed.get("parameter_families") or [])
            if isinstance(f, dict)
        ]
    if "families_full" in sections:
        out["parameter_families"] = parsed.get("parameter_families") or []
    if "character_sheet" in sections:
        out["character_sheet"] = parsed.get("character_sheet")
    return ToolResult(out)


read_ruleset_tool = FunctionTool(
    name="read_ruleset",
    description=(
        "Fetch one or more sections of a ruleset. `sections` defaults "
        "to a summary set; pass 'scenarios_full' / 'families_full' / "
        "'character_sheet' for full content. Use after search_my_rulesets "
        "to absorb the user's style before designing a similar ruleset."
    ),
    json_schema=make_object_schema({
        "ruleset_id": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "meta", "core", "scenarios_summary", "scenarios_full",
                    "families_summary", "families_full", "character_sheet",
                ],
            },
        },
    }, ["ruleset_id"]),
    is_write=False,
    executor=_read_ruleset,
)


def _grep_text(text: str, pattern: re.Pattern, max_hits: int) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if pattern.search(line):
            ctx_start = max(0, i - 2)
            ctx_end = min(len(lines), i + 3)
            hits.append({
                "line": i + 1,
                "match": line[:300],
                "context": "\n".join(lines[ctx_start:ctx_end])[:800],
            })
            if len(hits) >= max_hits:
                break
    return hits


async def _grep_in_ruleset(
    ctx: ToolContext, args: dict[str, Any],
) -> ToolResult:
    rs_id = str(args.get("ruleset_id") or "").strip()
    pattern_str = str(args.get("pattern") or "").strip()
    if not rs_id or not pattern_str:
        raise ToolError("missing_args", "ruleset_id and pattern required")
    max_hits = max(1, min(int(args.get("max_hits") or 20), 50))
    rs = await ctx.db.get(Ruleset, rs_id)
    if rs is None or (rs.owner_id != ctx.owner_id and not rs.is_shared):
        raise ToolError("not_found", "ruleset not visible to this user")
    try:
        pattern = re.compile(pattern_str, re.IGNORECASE | re.MULTILINE)
    except re.error as e:
        raise ToolError("bad_pattern", f"regex error: {e}") from e
    parsed = rs.parsed_v6 or {}
    hits_by_section: dict[str, Any] = {}

    core = str(parsed.get("core_rules") or "")
    if core:
        h = _grep_text(core, pattern, max_hits)
        if h:
            hits_by_section["core_rules"] = h

    pkg_hits: dict[str, Any] = {}
    for pkg in (parsed.get("rule_packages") or []):
        if not isinstance(pkg, dict):
            continue
        h = _grep_text(str(pkg.get("content") or ""), pattern, max_hits)
        if h:
            pkg_hits[pkg.get("package_id", "")] = h
    if pkg_hits:
        hits_by_section["rule_packages"] = pkg_hits

    fam_hits: dict[str, Any] = {}
    for fam in (parsed.get("parameter_families") or []):
        if not isinstance(fam, dict):
            continue
        body = str(fam.get("content") or "")
        if fam.get("json"):
            body += "\n" + _json.dumps(fam["json"], ensure_ascii=False)
        h = _grep_text(body, pattern, max_hits)
        if h:
            fam_hits[fam.get("family_id", "")] = h
    if fam_hits:
        hits_by_section["parameter_families"] = fam_hits

    cs = parsed.get("character_sheet") or {}
    if isinstance(cs, dict):
        body = (
            str(cs.get("template_content") or "")
            + "\n"
            + str(cs.get("guide_content") or "")
        )
        h = _grep_text(body, pattern, max_hits)
        if h:
            hits_by_section["character_sheet"] = h

    return ToolResult({
        "ruleset_id": rs.id,
        "book_title": rs.book_title,
        "pattern": pattern_str,
        "hits_by_section": hits_by_section,
    })


grep_in_ruleset_tool = FunctionTool(
    name="grep_in_ruleset",
    description=(
        "Search for a regex pattern across a ruleset's core_rules, "
        "rule_packages, parameter_families, and character_sheet text. "
        "Returns matching lines with ±2 line context. Case-insensitive."
    ),
    json_schema=make_object_schema({
        "ruleset_id": {"type": "string"},
        "pattern": {"type": "string", "description": "Python regex"},
        "max_hits": {"type": "integer", "minimum": 1, "maximum": 50},
    }, ["ruleset_id", "pattern"]),
    is_write=False,
    executor=_grep_in_ruleset,
)


SEARCH_RULESET_TOOLS: list[FunctionTool] = [
    search_rulesets_tool,
    read_ruleset_tool,
    grep_in_ruleset_tool,
]
