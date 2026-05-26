"""Main-agent bridge to the dice IR compile + apply pipeline.

The dice tab keeps its own conversational agent (`agents.rule_editor_dice`)
for advanced dice authoring. This bridge lets the main rule-design
ReAct agent request a single dice procedure compile mid-turn without
spawning that secondary agent or duplicating compile / persist logic.

The tool is intentionally thin: it forwards to the shared
`compile_and_apply_dice_procedure` helper in
`agents.rule_editor_dice.tools_design`, which routes through either
the deterministic direct compiler or the bounded CodeAct loop (per
`CHATRPG_DICE_CODEACT`) and then persists through the single-writer
`apply_dice_proposal` boundary in `tools_apply.py`. No new dice_ir
writer is introduced; the merge helper keeps exactly one owner.

The agent loop layers SSE on top via the
`_request_dice_compile_changed` marker stamped onto the tool payload:
the marker is stripped before the LLM ever sees the result, but the
loop reads it and emits an additive `dice_state_changed` event so
the frontend reloads the dice preview the same way the dice tab does
after a successful `design_dice_procedure`.
"""

from __future__ import annotations

from typing import Any

from .base import (
    FunctionTool,
    ToolContext,
    ToolResult,
    make_object_schema,
)


# Internal marker keys the agent loop reads to mirror dice state into
# SSE events. Stripped from the public payload before the LLM sees it
# (`strip_internal_markers` in `agent_context.py`).
DICE_STATE_CHANGED_MARKER = "_request_dice_compile_changed"
DICE_COMPILE_PROGRESS_MARKER = "_request_dice_compile_progress"


# Engine hints are duplicated here (rather than imported from
# `tools_design`) so this module stays import-clean. Importing
# `tools_design` at module load creates a cycle: tools_apply ->
# tools.base -> tools.__init__ -> registry -> dice_bridge ->
# tools_design -> tools_apply. The list is short and changes
# alongside the compiler families, so duplication is cheaper than
# the lazy-import dance.
_ENGINE_HINT_NAMES: tuple[str, ...] = (
    "coc_7e_d100", "brp_d100", "d20_vs_dc", "pbta_2d6",
    "pool_count_n", "custom_llm",
)


async def _request_dice_compile(
    ctx: ToolContext, args: dict[str, Any],
) -> ToolResult:
    # Lazy import to avoid the import cycle described above.
    from agents.rule_editor_dice.tools_design import (
        compile_and_apply_dice_procedure,
    )

    outcome = await compile_and_apply_dice_procedure(
        ctx,
        name=str(args.get("name") or ""),
        description=str(args.get("description") or ""),
        engine_hint=str(args.get("engine_hint") or ""),
    )
    payload: dict[str, Any] = dict(outcome.payload)
    # Stamp internal markers so the agent loop can emit additive SSE
    # events. Both markers are stripped from the LLM-visible payload.
    payload[DICE_STATE_CHANGED_MARKER] = True
    payload[DICE_COMPILE_PROGRESS_MARKER] = {
        "source": outcome.source,
        "primitive_calls": outcome.primitive_calls,
        "iters": outcome.iters,
        "fallback_reason": outcome.fallback_reason,
    }
    return ToolResult(payload)


request_dice_compile_tool = FunctionTool(
    name="request_dice_compile",
    description=(
        "Request a single dice procedure compile from the main rule "
        "design agent. The backend wraps your description as a mini "
        "rulebook, runs the deterministic dice IR compiler (or the "
        "bounded CodeAct compiler when `CHATRPG_DICE_CODEACT=1`), and "
        "persists the result into draft.parsed_v6.dice_ir through the "
        "same single-writer boundary as the dedicated dice tab. Slow "
        "(~10-30s) -- call sparingly, and prefer the dice tab for "
        "iterative dice authoring. `engine_hint` is one of: "
        "coc_7e_d100, brp_d100, d20_vs_dc, pbta_2d6, pool_count_n, "
        "custom_llm. Leave empty to let the compiler choose."
    ),
    json_schema=make_object_schema({
        "name": {
            "type": "string",
            "description": "snake_case procedure id (e.g. `skill_check`).",
        },
        "description": {
            "type": "string",
            "description": (
                "Plain-English (or Chinese) description of the rule: "
                "dice expression, success condition, tier outcomes, "
                "side effects."
            ),
        },
        "engine_hint": {
            "type": "string",
            "description": (
                "Optional engine family hint. One of: "
                + ", ".join(_ENGINE_HINT_NAMES)
                + ". Leave empty to let the compiler pick."
            ),
        },
    }, ["name", "description"]),
    is_write=True,
    executor=_request_dice_compile,
)


DICE_BRIDGE_TOOLS: list[FunctionTool] = [request_dice_compile_tool]


__all__ = [
    "DICE_BRIDGE_TOOLS",
    "DICE_STATE_CHANGED_MARKER",
    "DICE_COMPILE_PROGRESS_MARKER",
    "request_dice_compile_tool",
]
