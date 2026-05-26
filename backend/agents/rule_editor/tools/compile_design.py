"""Agent tool wrapper for the design-state -> parsed_v6 compile path.

The tool is intentionally thin: it forwards to the shared service in
`services.ruleset_draft_compile`, then translates the dataclass result
into the structured payload the agent loop ships back as a
`role=tool` message. P0.6 will wire this tool into the phase-aware
prompt; for now the tool is registered but the runtime prompt does
not yet require it.
"""

from __future__ import annotations

from typing import Any

from services.ruleset_draft_compile import (
    CompileBlockedResult,
    CompileSuccessResult,
    compile_design_for_draft,
)

from .base import (
    FunctionTool,
    ToolContext,
    ToolResult,
    make_object_schema,
)


async def _compile_design(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    result = await compile_design_for_draft(
        ctx.db,
        draft_id=ctx.draft_id,
        owner_id=ctx.owner_id,
        message_id=ctx.assistant_message_id,
    )
    if isinstance(result, CompileBlockedResult):
        return ToolResult(
            payload={
                "ok": False,
                "status": "blocked",
                "ready_blockers": list(result.ready_blockers),
                "validation_report": result.validation_report,
                "design_phase": result.design_phase,
                "error": result.error,
            },
        )
    assert isinstance(result, CompileSuccessResult)
    return ToolResult(
        payload={
            "ok": True,
            "status": "success",
            "edit_id": result.edit_id,
            "sections_emitted": list(result.sections_emitted),
            "validation_report": result.validation_report,
            "needs_dice_compile": result.needs_dice_compile,
            "needs_character_ui_compile": result.needs_character_ui_compile,
            "design_phase": result.design_phase,
        },
        edit_id=result.edit_id,
    )


compile_design_tool = FunctionTool(
    name="compile_design",
    description=(
        "Run the deterministic compiler from the current design_state to "
        "the runtime parsed_v6 artifact. Validator gates compile -- when "
        "any blocking issue exists the tool returns a structured "
        "`status=blocked` payload and parsed_v6 is not changed. On "
        "`status=success` parsed_v6 is replaced and an edit row is "
        "written. No arguments; the tool always operates on the active "
        "draft from the tool context."
    ),
    json_schema=make_object_schema({}, []),
    is_write=True,
    executor=_compile_design,
)


COMPILE_DESIGN_TOOLS: list[FunctionTool] = [compile_design_tool]


__all__ = ["COMPILE_DESIGN_TOOLS", "compile_design_tool"]
