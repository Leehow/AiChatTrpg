"""Design tools for collections: rule_packages + parameter_families."""

from __future__ import annotations

import copy
from typing import Any

from agents.rule_editor.paradigms import lookup_family, lookup_scenario
from services import ruleset_drafts as svc

from ._apply import apply_ops
from .base import (
    FunctionTool,
    ToolContext,
    ToolError,
    ToolResult,
    make_object_schema,
)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


async def _design_scenario(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    pkg_id = str(args.get("id") or "").strip()
    paradigm = str(args.get("paradigm") or "").strip()
    content = str(args.get("content") or "")
    if not pkg_id:
        raise ToolError("missing_arg", "id required")
    if not paradigm:
        raise ToolError("missing_arg", "paradigm required")
    p = lookup_scenario(paradigm)
    val = p.validate(content)
    if not val.ok:
        raise ToolError("validation_failed", "; ".join(val.errors))
    return await apply_ops(ctx, [{
        "op": "upsert_rule_package",
        "id": pkg_id,
        "package": {"content": content, "paradigm": p.id},
    }], extra_payload={"warnings": val.warnings})


design_scenario_tool = FunctionTool(
    name="design_scenario",
    description=(
        "Create or rewrite a rule package. `id` is the package_id (e.g. "
        "`combat`). `paradigm` is one of the canonical scenario "
        "paradigms (combat / sanity / chase_vehicles / creation / "
        "progression / recovery / exploration / social / abilities / "
        "downtime_economy / hacking / mission) or `custom`. `content` "
        "is the full markdown — write it directly. Aim for 300-1500 "
        "words. Validates non-empty / >=50 chars."
    ),
    json_schema=make_object_schema({
        "id": {"type": "string"},
        "paradigm": {"type": "string"},
        "brief": {"type": "string", "description": "one-line goal (logged, optional)"},
        "content": {"type": "string"},
    }, ["id", "paradigm", "content"]),
    is_write=True,
    executor=_design_scenario,
)


async def _remove_scenario(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    pkg_id = str(args.get("id") or "").strip()
    if not pkg_id:
        raise ToolError("missing_arg", "id required")
    return await apply_ops(ctx, [{"op": "remove_rule_package", "id": pkg_id}])


remove_scenario_tool = FunctionTool(
    name="remove_scenario",
    description="Delete a rule package by id.",
    json_schema=make_object_schema({"id": {"type": "string"}}, ["id"]),
    is_write=True,
    executor=_remove_scenario,
)


# ---------------------------------------------------------------------------
# Parameter families
# ---------------------------------------------------------------------------


def _normalize_entry(book_id: str, fam_id: str, idx: int, entry: dict) -> dict:
    """Apply common-shell defaults: id / family / required keys."""
    e = dict(entry)
    if not e.get("id"):
        e["id"] = f"{(book_id or 'CUSTOM').upper()}.{fam_id.upper()}.{idx + 1:03d}"
    e.setdefault("family", fam_id)
    e.setdefault("aliases", [])
    e.setdefault("tags", [])
    e.setdefault("rule_context", "")
    return e


async def _design_parameter_family(
    ctx: ToolContext, args: dict[str, Any],
) -> ToolResult:
    fam_id = str(args.get("id") or "").strip()
    paradigm = str(args.get("paradigm") or "").strip()
    entries = args.get("entries") or []
    if not fam_id:
        raise ToolError("missing_arg", "id required")
    if not paradigm:
        raise ToolError("missing_arg", "paradigm required")
    if not isinstance(entries, list) or not entries:
        raise ToolError("missing_arg", "entries (non-empty list) required")
    p = lookup_family(paradigm)
    val = p.validate(entries)
    if not val.ok:
        raise ToolError("validation_failed", "; ".join(val.errors))

    draft = await svc.get_draft(
        ctx.db, draft_id=ctx.draft_id, owner_id=ctx.owner_id,
    )
    book_id = str((draft.parsed_v6 or {}).get("book_id") or "")
    normalized = [
        _normalize_entry(book_id, fam_id, i, e)
        for i, e in enumerate(entries)
        if isinstance(e, dict)
    ]

    return await apply_ops(ctx, [{
        "op": "upsert_parameter_family",
        "id": fam_id,
        "family": {
            "content": "",
            "json": {
                "family_id": fam_id,
                "schema_used": {
                    "common_shell_fields": [
                        "id", "name", "aliases", "family", "summary",
                        "tags", "rule_context",
                    ],
                    "family_specific_fields": list(p.family_specific_fields),
                },
                "entries": normalized,
            },
            "paradigm": p.id,
        },
    }], extra_payload={
        "entries_count": len(normalized),
        "warnings": val.warnings,
    })


design_family_tool = FunctionTool(
    name="design_parameter_family",
    description=(
        "Create or rewrite a parameter family with a list of entries. "
        "`id` is the family_id (e.g. `weapon`, `occupation`). `paradigm` "
        "is one of the canonical family paradigms or `custom`. `entries` "
        "is a list of objects; each MUST have at least `name` and "
        "`summary`; the backend fills in `id`, `family`, `aliases`, "
        "`tags`, `rule_context` defaults. Family-specific fields are "
        "passed through verbatim — see paradigm catalog for suggestions."
    ),
    json_schema=make_object_schema({
        "id": {"type": "string"},
        "paradigm": {"type": "string"},
        "brief": {"type": "string"},
        "entries": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": True},
        },
    }, ["id", "paradigm", "entries"]),
    is_write=True,
    executor=_design_parameter_family,
)


async def _add_parameter_entry(
    ctx: ToolContext, args: dict[str, Any],
) -> ToolResult:
    fam_id = str(args.get("family_id") or "").strip()
    entry = args.get("entry") or {}
    if not fam_id or not isinstance(entry, dict):
        raise ToolError("missing_arg", "family_id and entry required")

    draft = await svc.get_draft(
        ctx.db, draft_id=ctx.draft_id, owner_id=ctx.owner_id,
    )
    book_id = str((draft.parsed_v6 or {}).get("book_id") or "")
    fam_match = next(
        (
            f for f in (draft.parsed_v6 or {}).get("parameter_families") or []
            if isinstance(f, dict) and f.get("family_id") == fam_id
        ),
        None,
    )
    if fam_match is None:
        raise ToolError(
            "family_not_found",
            f"family `{fam_id}` does not exist; create it with "
            "design_parameter_family first",
        )
    existing_entries = list((fam_match.get("json") or {}).get("entries") or [])
    new_entry = _normalize_entry(
        book_id, fam_id, len(existing_entries), entry,
    )
    new_entries = existing_entries + [new_entry]
    new_family = copy.deepcopy(fam_match)
    new_family.setdefault("json", {})
    new_family["json"]["entries"] = new_entries
    new_family["json"]["family_id"] = fam_id

    return await apply_ops(ctx, [{
        "op": "upsert_parameter_family",
        "id": fam_id,
        "family": {
            "content": new_family.get("content", ""),
            "json": new_family["json"],
            "paradigm": new_family.get("paradigm"),
        },
    }], extra_payload={"new_entry_id": new_entry["id"]})


add_entry_tool = FunctionTool(
    name="add_parameter_entry",
    description=(
        "Append a single entry to an existing parameter family. The "
        "family must already exist (call design_parameter_family first "
        "if not). Provide `entry` with at least `name` and `summary`."
    ),
    json_schema=make_object_schema({
        "family_id": {"type": "string"},
        "entry": {"type": "object", "additionalProperties": True},
    }, ["family_id", "entry"]),
    is_write=True,
    executor=_add_parameter_entry,
)


async def _remove_parameter_entry(
    ctx: ToolContext, args: dict[str, Any],
) -> ToolResult:
    fam_id = str(args.get("family_id") or "").strip()
    entry_id = str(args.get("entry_id") or "").strip()
    if not fam_id or not entry_id:
        raise ToolError("missing_arg", "family_id and entry_id required")
    draft = await svc.get_draft(
        ctx.db, draft_id=ctx.draft_id, owner_id=ctx.owner_id,
    )
    fam_match = next(
        (
            f for f in (draft.parsed_v6 or {}).get("parameter_families") or []
            if isinstance(f, dict) and f.get("family_id") == fam_id
        ),
        None,
    )
    if fam_match is None:
        raise ToolError("family_not_found", f"family `{fam_id}` not found")
    existing_entries = list((fam_match.get("json") or {}).get("entries") or [])
    new_entries = [e for e in existing_entries if e.get("id") != entry_id]
    if len(new_entries) == len(existing_entries):
        raise ToolError("entry_not_found", f"entry `{entry_id}` not in family")
    new_family = copy.deepcopy(fam_match)
    new_family.setdefault("json", {})
    new_family["json"]["entries"] = new_entries
    return await apply_ops(ctx, [{
        "op": "upsert_parameter_family",
        "id": fam_id,
        "family": {
            "content": new_family.get("content", ""),
            "json": new_family["json"],
            "paradigm": new_family.get("paradigm"),
        },
    }])


remove_entry_tool = FunctionTool(
    name="remove_parameter_entry",
    description="Drop one entry from a parameter family by entry id.",
    json_schema=make_object_schema({
        "family_id": {"type": "string"},
        "entry_id": {"type": "string"},
    }, ["family_id", "entry_id"]),
    is_write=True,
    executor=_remove_parameter_entry,
)


COLLECTION_DESIGN_TOOLS: list[FunctionTool] = [
    design_scenario_tool,
    remove_scenario_tool,
    design_family_tool,
    add_entry_tool,
    remove_entry_tool,
]
