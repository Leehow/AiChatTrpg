"""Single-writer apply boundary for dice IR persistence.

Every agent-side path that wants to land a compiled dice procedure
into `draft.parsed_v6.dice_ir` goes through `apply_dice_proposal` in
this module. The legacy `design_dice_procedure` tool calls it after
running `compile_to_ir_direct`; future CodeAct / main-ReAct bridges
must use the same entry point.

Keeping the merge helper and the DB write in one module makes the
invariant statically checkable: a grep for `_merge_into_dice_ir`
or `draft.parsed_v6["dice_ir"] =` should turn up exactly one owner.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from agents.rule_editor.tools.base import ToolContext, ToolError
from services import ruleset_drafts as svc


logger = logging.getLogger("chatrpg.rule_editor_dice.apply")


def _merge_into_dice_ir(
    parsed_v6: dict[str, Any],
    new_specs: list[dict[str, Any]],
    *,
    model: str,
) -> dict[str, Any]:
    """Replace existing procedures by id, append new ones. Mutates
    parsed_v6 in place; returns the updated dice_ir artifact.

    Private to this module — see the file docstring for the
    single-writer invariant.
    """
    existing_ir = parsed_v6.get("dice_ir") or {}
    existing_pkg = (existing_ir.get("package") or {})
    existing_compiled = (existing_pkg.get("compiled") or {})
    existing_specs: list[dict[str, Any]] = list(
        existing_compiled.get("check_specs") or []
    )
    by_id: dict[str, int] = {}
    for i, s in enumerate(existing_specs):
        pid = str((s or {}).get("procedure_id") or "")
        if pid:
            by_id[pid] = i

    for new_s in new_specs:
        pid = str((new_s or {}).get("procedure_id") or "")
        if pid and pid in by_id:
            existing_specs[by_id[pid]] = new_s
        else:
            existing_specs.append(new_s)
            if pid:
                by_id[pid] = len(existing_specs) - 1

    new_compiled = {
        **existing_compiled,
        "schema_version": (
            existing_compiled.get("schema_version")
            or "ruleset_dice_ir_compiled_package_v1"
        ),
        "check_specs": existing_specs,
        "default_procedure_id": (
            existing_compiled.get("default_procedure_id")
            or (existing_specs[0]["procedure_id"] if existing_specs else "")
        ),
        "overall_ok": all(
            (s.get("validation") or {}).get("ok") for s in existing_specs
        ),
    }
    new_pkg = {
        **existing_pkg,
        "schema_version": (
            existing_pkg.get("schema_version")
            or "ruleset_dice_ir_compiler_artifact_v1"
        ),
        "compiled": new_compiled,
    }
    new_ir = {
        **existing_ir,
        "schema_version": "ruleset_dice_ir_compiler_artifact_v1",
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "package": new_pkg,
    }
    parsed_v6["dice_ir"] = new_ir
    return new_ir


def _summarize_specs(new_specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in new_specs:
        spec = s.get("check_spec") or {}
        validation = s.get("validation") or {}
        samples = validation.get("samples") or []
        out.append({
            "procedure_id": s.get("procedure_id", ""),
            "name": s.get("name", ""),
            "engine": spec.get("engine", ""),
            "validation_ok": validation.get("ok"),
            "samples_passed": sum(1 for x in samples if x.get("ok")),
            "samples_failed": sum(1 for x in samples if not x.get("ok")),
            "sample_summary": [
                {
                    "name": x.get("name"),
                    "ok": x.get("ok"),
                    "expected": x.get("expected"),
                    "actual": x.get("actual"),
                }
                for x in samples[:6]
            ],
        })
    return out


async def apply_dice_proposal(
    ctx: ToolContext,
    *,
    package: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    """Persist a compiled dice IR package into
    `draft.parsed_v6.dice_ir`, mirror it onto the linked target ruleset
    when one exists, clear `needs_dice_compile`, and commit.

    `package` is the dict returned by `compile_to_ir_direct`. It must
    have a `compiled.check_specs` array with at least one entry;
    otherwise `ToolError("no_compiled_procedures")` is raised and no
    write happens.

    Returns the public payload that the dice agent surfaces as the
    tool result (`ok`, `compiled_specs`, `unsupported`). Callers wrap
    it in `ToolResult(...)` as needed.

    This is the only function in the agent codebase that should call
    `_merge_into_dice_ir` or write `draft.parsed_v6["dice_ir"]`. The
    single-writer invariant is enforced by
    `backend/debug/trpg/test_dice_single_writer.py`.
    """
    compiled = (package.get("compiled") or {})
    new_specs = compiled.get("check_specs") or []
    unsupported = compiled.get("unsupported_procedures") or []
    if not new_specs:
        raise ToolError(
            "no_compiled_procedures",
            f"compiler emitted no procedures (unsupported: {unsupported})",
        )

    draft = await svc.get_draft(
        ctx.db, draft_id=ctx.draft_id, owner_id=ctx.owner_id,
    )
    parsed_v6 = copy.deepcopy(draft.parsed_v6 or {})
    _merge_into_dice_ir(parsed_v6, new_specs, model=model)
    draft.parsed_v6 = parsed_v6
    flag_modified(draft, "parsed_v6")
    draft.needs_dice_compile = False
    if draft.target_ruleset_id:
        from orm.models import Ruleset
        target = await ctx.db.get(Ruleset, draft.target_ruleset_id)
        if target is not None and target.owner_id == ctx.owner_id:
            target.dice_ir = parsed_v6["dice_ir"]
            flag_modified(target, "dice_ir")
            target.updated_at = datetime.now(timezone.utc)
    await ctx.db.commit()
    await ctx.db.refresh(draft)

    return {
        "ok": True,
        "compiled_specs": _summarize_specs(new_specs),
        "unsupported": unsupported,
    }
