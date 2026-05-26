"""design_dice_procedure — wraps a description as a mini rulebook,
runs the deterministic dice IR compiler (or the bounded CodeAct
compiler when `CHATRPG_DICE_CODEACT=1`), then hands the compiled
package to the single-writer apply boundary in `tools_apply.py` for
persistence.

This tool deliberately does not touch `draft.parsed_v6["dice_ir"]`
directly. Persistence lives in `apply_dice_proposal` so the CodeAct
path and the main-ReAct dice bridge (`request_dice_compile`) re-use
the same writer without duplicating merge / mirror / commit logic.

`compile_and_apply_dice_procedure` is the shared entry point both
the dice agent's `design_dice_procedure` and the main agent's
`request_dice_compile` go through. Keeping it here (next to the
direct/CodeAct branch) means the compile policy lives in exactly
one place.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from agents.rule_editor.tools.base import (
    FunctionTool,
    ToolContext,
    ToolError,
    ToolResult,
    make_object_schema,
)
from agents.trpg.check_ir.compile_direct import (
    DiceRuleCompilerError,
    compile_to_ir_direct,
)
from services import ruleset_drafts as svc

from .codeact_agent import codeact_enabled, compile_via_codeact
from .tools_apply import apply_dice_proposal


logger = logging.getLogger("chatrpg.rule_editor_dice.design")


ENGINE_HINTS: tuple[str, ...] = (
    "coc_7e_d100", "brp_d100", "d20_vs_dc", "pbta_2d6",
    "pool_count_n", "custom_llm",
)
# Back-compat alias for callers that imported the old name.
_ENGINE_HINTS = ENGINE_HINTS


@dataclass
class CompileAndApplyOutcome:
    """Result of `compile_and_apply_dice_procedure`.

    `payload` is the public dict produced by `apply_dice_proposal`
    (`ok`, `compiled_specs`, `unsupported`). `source` describes which
    compiler path ran (`"direct"` or one of the codeact source labels
    from `CodeActOutcome`). Bridge callers stamp these into the
    bridge-specific tool result without re-running the compile.
    """

    payload: dict[str, Any]
    source: str
    primitive_calls: int = 0
    iters: int = 0
    fallback_reason: str | None = None


def _wrap_as_minirulebook(
    name: str, description: str, engine_hint: str, system_name: str,
) -> str:
    lines = [
        f"# {system_name or 'Custom Ruleset'}",
        "",
        f"## Procedure: {name}",
        "",
        description.strip(),
        "",
    ]
    if engine_hint:
        lines.append(
            f"_Engine hint: this procedure should compile under "
            f"`{engine_hint}` if compatible._\n"
        )
    return "\n".join(lines)


def _validate_dice_args(
    name: str, description: str, engine_hint: str,
) -> None:
    if not name:
        raise ToolError("missing_arg", "name required")
    if not description:
        raise ToolError("missing_arg", "description required")
    if engine_hint and engine_hint not in ENGINE_HINTS:
        raise ToolError(
            "bad_engine_hint",
            f"engine_hint must be one of {list(ENGINE_HINTS)} or empty",
        )


async def compile_and_apply_dice_procedure(
    ctx: ToolContext,
    *,
    name: str,
    description: str,
    engine_hint: str = "",
) -> CompileAndApplyOutcome:
    """Shared compile-and-apply entry point for both the dice agent
    (`design_dice_procedure`) and the main-agent bridge
    (`request_dice_compile`).

    Validates args, resolves the active draft + default compiler cfg,
    runs either the deterministic direct compiler or the bounded
    CodeAct loop (per `CHATRPG_DICE_CODEACT`), then persists through
    the single-writer `apply_dice_proposal` boundary. Returns the
    public apply payload plus a `source` label so callers can stamp
    bridge-specific metadata onto their tool result without
    re-running the compile.
    """
    name = name.strip()
    description = description.strip()
    engine_hint = engine_hint.strip()
    _validate_dice_args(name, description, engine_hint)

    draft = await svc.get_draft(
        ctx.db, draft_id=ctx.draft_id, owner_id=ctx.owner_id,
    )
    parsed_v6 = draft.parsed_v6 or {}
    system_name = str(parsed_v6.get("book_title") or draft.title or "Custom")
    output_language = str(parsed_v6.get("output_language") or "en").lower()
    if output_language not in {"en", "zh"}:
        output_language = "en"

    from routes.rulesets import _resolve_default_compiler_config
    cfg = await _resolve_default_compiler_config(ctx.db)
    if not cfg.get("api_key") or not cfg.get("base_url"):
        raise ToolError(
            "no_api_config",
            "no API config available for the default compiler model",
        )

    source = "direct"
    primitive_calls = 0
    iters = 0
    fallback_reason: str | None = None
    try:
        if codeact_enabled():
            outcome = await compile_via_codeact(
                procedure_id=name,
                name=name,
                description=description,
                engine_hint=engine_hint,
                system_name=system_name,
                output_language=output_language,
                cfg=cfg,
                provider="",
            )
            package = outcome.package
            source = outcome.source
            primitive_calls = outcome.primitive_calls
            iters = outcome.iters
            fallback_reason = outcome.fallback_reason
            logger.info(
                "[chatrpg] dice CodeAct compile source=%s "
                "primitive_calls=%d iters=%d fallback=%s",
                outcome.source, outcome.primitive_calls, outcome.iters,
                outcome.fallback_reason,
            )
        else:
            md = _wrap_as_minirulebook(
                name, description, engine_hint, system_name,
            )
            package = await compile_to_ir_direct(
                md,
                system_name=system_name,
                house_rules="",
                model=cfg["model"],
                base_url=cfg["base_url"],
                api_key=cfg["api_key"],
                output_language=output_language,
            )
    except DiceRuleCompilerError as e:
        raise ToolError("compile_failed", str(e)) from e
    except ToolError:
        raise
    except Exception as e:
        logger.exception("[chatrpg] dice procedure compile failed")
        raise ToolError("compile_unexpected", str(e)) from e

    payload = await apply_dice_proposal(
        ctx, package=package, model=cfg["model"],
    )
    return CompileAndApplyOutcome(
        payload=payload,
        source=source,
        primitive_calls=primitive_calls,
        iters=iters,
        fallback_reason=fallback_reason,
    )


async def _design_dice_procedure(
    ctx: ToolContext, args: dict[str, Any],
) -> ToolResult:
    outcome = await compile_and_apply_dice_procedure(
        ctx,
        name=str(args.get("name") or ""),
        description=str(args.get("description") or ""),
        engine_hint=str(args.get("engine_hint") or ""),
    )
    return ToolResult(outcome.payload)


design_dice_procedure_tool = FunctionTool(
    name="design_dice_procedure",
    description=(
        "Compile a single dice procedure from a natural-language "
        "description. The backend wraps your description as a mini "
        "rulebook and runs the deterministic dice IR compiler — which "
        "validates the result against embedded test samples. On success "
        "the procedure is persisted into draft.parsed_v6.dice_ir; if "
        "samples_failed > 0 you should iterate with a clearer "
        "description. Slow (~10-30s) — call sparingly. `engine_hint` "
        "is one of: coc_7e_d100, brp_d100, d20_vs_dc, pbta_2d6, "
        "pool_count_n, custom_llm. Leave empty to let the compiler "
        "choose."
    ),
    json_schema=make_object_schema({
        "name": {"type": "string", "description": "snake_case procedure id"},
        "description": {
            "type": "string",
            "description": (
                "Plain-English (or Chinese) description of the rule: "
                "dice expression, success condition, tier outcomes, "
                "side effects."
            ),
        },
        "engine_hint": {"type": "string"},
    }, ["name", "description"]),
    is_write=True,
    executor=_design_dice_procedure,
)
