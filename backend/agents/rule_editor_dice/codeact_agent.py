"""Bounded CodeAct compiler loop for the dice agent.

`compile_via_codeact(...)` runs a tool-calling LLM loop over the
deterministic primitives in `codeact_primitives.py`, builds a
canonical `package` dict on `propose_final`, and falls back to
`compile_to_ir_direct` (via the `compile_one` primitive) on budget
exhaustion or invalid proposals. The returned `package` matches
`compile_to_ir_direct`'s shape and goes straight to
`apply_dice_proposal`, preserving the single-writer invariant.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional

from agents.grep_retrieval.runtime_openai import (
    apply_openai_request_defaults,
    build_openai_client,
    resolve_openai_compat_base_url,
)

from . import codeact_primitives as P
from .codeact_prompts import (
    TOOL_NAME_COMPILE_ONE, TOOL_NAME_GENERATE_SAMPLES, TOOL_NAME_MUTATE,
    TOOL_NAME_PROPOSE_FINAL, TOOL_NAME_RUN_SAMPLE, TOOL_NAME_SIMULATE,
    TOOL_NAME_SKELETON, TOOL_NAME_VALIDATE,
    build_codeact_system_prompt, build_codeact_tools_schema, build_user_brief,
)

logger = logging.getLogger("chatrpg.rule_editor_dice.codeact.agent")
CODEACT_ENV_FLAG = "CHATRPG_DICE_CODEACT"


def codeact_enabled() -> bool:
    """Return True iff CodeAct should handle new dice compiles. Off by default."""
    raw = (os.environ.get(CODEACT_ENV_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass
class CodeActBudget:
    max_primitive_calls: int = 20
    max_inner_iters: int = 8
    wallclock_seconds: float = 90.0


@dataclass
class CodeActOutcome:
    package: Dict[str, Any]
    source: str  # "codeact" | "fallback_compile_one" | "fallback_codeact_failed"
    primitive_calls: int
    iters: int
    fallback_reason: Optional[str] = None
    proposal_errors: List[str] = field(default_factory=list)


LLMCaller = Callable[[List[Dict[str, Any]], List[Dict[str, Any]]], Awaitable[Any]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_package_from_proposal(
    *, ir: Mapping[str, Any], samples: List[Mapping[str, Any]],
    sample_results: List[Mapping[str, Any]], procedure_id: str,
    name: str, primary_family: str, system_name: str, model: str,
) -> Dict[str, Any]:
    """Wrap a validated proposal into the canonical compiler package
    shape (the same dict `compile_to_ir_direct` returns)."""
    entry = {
        "procedure_id": procedure_id, "name": name or procedure_id,
        "primary_family": str(primary_family or ""),
        "check_spec": {"engine": "generic_resolution_v1", "ir": dict(ir)},
        "validation": {"ok": True, "sample_count": len(sample_results),
                       "samples": [dict(r) for r in sample_results]},
        "samples": [dict(s) for s in samples],
    }
    return {
        "schema_version": "rulebook_dice_compilation_v1",
        "compiled_at": _now_iso(), "model": model,
        "compiler_strategy": "codeact_v1", "house_rules": None,
        "compiled": {
            "schema_version": "compiled_check_specs_v1",
            "compiled_at": _now_iso(), "system_name": system_name,
            "default_procedure_id": procedure_id,
            "default_check_spec": entry["check_spec"],
            "check_specs": [entry], "unsupported_procedures": [],
            "overall_ok": True,
        },
    }


async def _dispatch_primitive(
    name: str,
    args: Mapping[str, Any],
    *,
    cfg: Mapping[str, str],
    system_name: str,
    output_language: str,
) -> Dict[str, Any]:
    """Run one primitive by name. Returns a JSON-safe dict. Unknown
    or malformed calls return `{ok:false, error_kind, error}` so the
    LLM sees structured feedback in the tool message."""
    try:
        if name == TOOL_NAME_SKELETON:
            return {"ok": True, "ir": P.propose_ir_skeleton(
                str(args.get("family") or ""),
                procedure_id=str(args.get("procedure_id") or ""),
                name=str(args.get("name") or ""),
            )}
        if name == TOOL_NAME_GENERATE_SAMPLES:
            params = args.get("params") if isinstance(args.get("params"), Mapping) else None
            return {"ok": True, "samples": P.generate_sample_cases(
                str(args.get("family") or ""), params,
            )}
        if name == TOOL_NAME_RUN_SAMPLE:
            return P.run_sample(args.get("ir") or {}, args.get("args") or {})
        if name == TOOL_NAME_SIMULATE:
            tpl = args.get("args_template")
            return P.simulate_probability(
                args.get("ir") or {},
                n=int(args.get("n") or 1000),
                seed=int(args.get("seed") or 42),
                args_template=tpl if isinstance(tpl, Mapping) else None,
            )
        if name == TOOL_NAME_MUTATE:
            return {"ok": True, "ir": P.mutate_ir(
                args.get("ir") or {}, list(args.get("ops") or []),
            )}
        if name == TOOL_NAME_VALIDATE:
            return P.validate_proposal(
                args.get("ir") or {}, list(args.get("samples") or []),
            )
        if name == TOOL_NAME_COMPILE_ONE:
            pkg = await P.compile_one(
                str(args.get("description") or ""),
                name=str(args.get("name") or ""),
                engine_hint=str(args.get("engine_hint") or ""),
                system_name=system_name,
                output_language=output_language,
                cfg=cfg,
            )
            return {"ok": True, "package": pkg}
    except (P.CodeActPrimitiveError, P.CodeActFixtureError) as exc:
        return {"ok": False, "error_kind": "primitive", "error": str(exc)}
    return {"ok": False, "error_kind": "unknown_tool",
            "error": f"no such primitive `{name}`"}


def _make_default_llm_caller(
    *, provider: str, base_url: str, api_key: str, model: str,
) -> LLMCaller:
    resolved = resolve_openai_compat_base_url(provider, base_url)
    if not resolved:
        raise RuntimeError(f"no OpenAI-compat base_url for provider `{provider}`")
    client = build_openai_client(base_url=resolved, api_key=api_key)

    async def _call(
        messages: List[Dict[str, Any]], tools: List[Dict[str, Any]],
    ) -> Any:
        kwargs = apply_openai_request_defaults({
            "model": model, "messages": messages,
            "tools": tools, "tool_choice": "auto", "stream": False,
        })
        return await client.chat.completions.create(**kwargs)

    return _call


async def _run_codeact_loop(
    *, llm_call: LLMCaller, sys_prompt: str, user_brief: str,
    tools_schema: List[Dict[str, Any]], budget: CodeActBudget,
    cfg: Mapping[str, str], system_name: str, output_language: str,
) -> Dict[str, Any]:
    """The bounded inner loop. Returns one of:
      {"status": "proposal", "proposal": {...}, "primitive_calls", "iters"}
      {"status": "compile_one_fallback", "package": {...}, ...}
      {"status": "budget_exceeded", "reason": ..., ...}
      {"status": "llm_error", "error": ..., ...}
    """
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_brief},
    ]
    primitive_calls = 0
    iters = 0
    started = time.monotonic()
    last_compile_one_package: Optional[Dict[str, Any]] = None

    while iters < budget.max_inner_iters:
        iters += 1
        if time.monotonic() - started > budget.wallclock_seconds:
            return {"status": "budget_exceeded", "reason": "wallclock",
                    "primitive_calls": primitive_calls, "iters": iters}
        try:
            resp = await llm_call(messages, tools_schema)
        except Exception as exc:  # noqa: BLE001
            return {"status": "llm_error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "primitive_calls": primitive_calls, "iters": iters}

        choices = getattr(resp, "choices", None) or []
        if not choices:
            return {"status": "llm_error", "error": "no choices in response",
                    "primitive_calls": primitive_calls, "iters": iters}
        msg = getattr(choices[0], "message", None)
        text = (getattr(msg, "content", "") or "") if msg is not None else ""
        tool_calls = list(getattr(msg, "tool_calls", None) or [])

        messages.append({
            "role": "assistant", "content": text or None,
            "tool_calls": [
                {"id": tc.id, "type": "function", "function": {
                    "name": getattr(tc.function, "name", "") or "",
                    "arguments": getattr(tc.function, "arguments", "") or "",
                }}
                for tc in tool_calls
            ] or None,
        })

        if not tool_calls:
            return {"status": "budget_exceeded", "reason": "no_tool_call",
                    "primitive_calls": primitive_calls, "iters": iters}

        for tc in tool_calls:
            if primitive_calls >= budget.max_primitive_calls:
                return {"status": "budget_exceeded",
                        "reason": "max_primitive_calls",
                        "primitive_calls": primitive_calls, "iters": iters}
            primitive_calls += 1
            tool_name = getattr(tc.function, "name", "") or ""
            try:
                args = json.loads(
                    getattr(tc.function, "arguments", "") or "{}",
                )
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}

            if tool_name == TOOL_NAME_PROPOSE_FINAL:
                return {"status": "proposal", "proposal": args,
                        "primitive_calls": primitive_calls, "iters": iters}

            result = await _dispatch_primitive(
                tool_name, args, cfg=cfg,
                system_name=system_name, output_language=output_language,
            )
            if tool_name == TOOL_NAME_COMPILE_ONE and result.get("ok"):
                pkg = result.get("package")
                if isinstance(pkg, dict):
                    last_compile_one_package = pkg
            messages.append({
                "role": "tool", "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False)[:8000],
            })

    if last_compile_one_package is not None:
        return {"status": "compile_one_fallback",
                "package": last_compile_one_package,
                "primitive_calls": primitive_calls, "iters": iters}
    return {"status": "budget_exceeded", "reason": "max_inner_iters",
            "primitive_calls": primitive_calls, "iters": iters}


async def _fallback(
    *,
    description: str, name: str, engine_hint: str,
    system_name: str, output_language: str, cfg: Mapping[str, str],
    primitive_calls: int, iters: int, reason: str,
    errors: Optional[List[str]] = None,
) -> CodeActOutcome:
    """Direct-compile safety net. `DiceRuleCompilerError` propagates."""
    logger.info(
        "[chatrpg] dice CodeAct falling back to compile_to_ir_direct: %s",
        reason,
    )
    pkg = await P.compile_one(
        description, name=name, engine_hint=engine_hint,
        system_name=system_name, output_language=output_language, cfg=cfg,
    )
    return CodeActOutcome(
        package=pkg, source="fallback_codeact_failed",
        primitive_calls=primitive_calls, iters=iters,
        fallback_reason=reason, proposal_errors=list(errors or []),
    )


async def compile_via_codeact(
    *, procedure_id: str, name: str, description: str, engine_hint: str,
    system_name: str, output_language: str, cfg: Mapping[str, str],
    provider: str, budget: Optional[CodeActBudget] = None,
    llm_call: Optional[LLMCaller] = None,
) -> CodeActOutcome:
    """Run the bounded dice CodeAct compiler and return a canonical
    package. On any internal failure (LLM error, budget exceeded,
    invalid proposal) it falls back to `compile_to_ir_direct` so the
    caller always receives a usable package or a `DiceRuleCompilerError`.
    """
    budget = budget or CodeActBudget()
    sys_prompt = build_codeact_system_prompt(
        max_primitive_calls=budget.max_primitive_calls,
        max_inner_iters=budget.max_inner_iters,
    )
    user_brief = build_user_brief(
        procedure_id=procedure_id, name=name, description=description,
        engine_hint=engine_hint, system_name=system_name,
    )
    tools_schema = build_codeact_tools_schema()

    if llm_call is None:
        llm_call = _make_default_llm_caller(
            provider=provider, base_url=cfg["base_url"],
            api_key=cfg["api_key"], model=cfg["model"],
        )

    loop_result = await _run_codeact_loop(
        llm_call=llm_call, sys_prompt=sys_prompt, user_brief=user_brief,
        tools_schema=tools_schema, budget=budget, cfg=cfg,
        system_name=system_name, output_language=output_language,
    )

    status = loop_result.get("status")
    primitive_calls = int(loop_result.get("primitive_calls") or 0)
    iters = int(loop_result.get("iters") or 0)

    if status == "proposal":
        proposal = loop_result.get("proposal") or {}
        ir = proposal.get("ir")
        samples = proposal.get("samples") or []
        if not isinstance(ir, dict) or not isinstance(samples, list):
            return await _fallback(
                description=description, name=name, engine_hint=engine_hint,
                system_name=system_name, output_language=output_language,
                cfg=cfg, primitive_calls=primitive_calls, iters=iters,
                reason="proposal_shape_invalid",
            )
        validation = P.validate_proposal(ir, samples)
        if not validation.get("ok"):
            return await _fallback(
                description=description, name=name, engine_hint=engine_hint,
                system_name=system_name, output_language=output_language,
                cfg=cfg, primitive_calls=primitive_calls, iters=iters,
                reason="proposal_validation_failed",
                errors=list(validation.get("errors") or []),
            )
        pkg = _build_package_from_proposal(
            ir=ir, samples=samples,
            sample_results=list(validation.get("sample_results") or []),
            procedure_id=str(proposal.get("procedure_id") or procedure_id),
            name=str(proposal.get("name") or name),
            primary_family=str(proposal.get("primary_family") or ""),
            system_name=system_name, model=cfg["model"],
        )
        return CodeActOutcome(
            package=pkg, source="codeact",
            primitive_calls=primitive_calls, iters=iters,
        )

    if status == "compile_one_fallback":
        pkg = loop_result.get("package") or {}
        return CodeActOutcome(
            package=pkg, source="fallback_compile_one",
            primitive_calls=primitive_calls, iters=iters,
            fallback_reason="loop_ended_with_compile_one_pkg",
        )

    reason = str(loop_result.get("reason") or loop_result.get("error") or status)
    return await _fallback(
        description=description, name=name, engine_hint=engine_hint,
        system_name=system_name, output_language=output_language,
        cfg=cfg, primitive_calls=primitive_calls, iters=iters,
        reason=reason,
    )
