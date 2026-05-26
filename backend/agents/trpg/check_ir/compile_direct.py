"""Direct LLM → resolution_ir_v1_1 compiler (v2 strategy).

Bypasses the old intermediate facts DSL. The LLM is given the rulebook
markdown, an optional house_rules layer, the IR schema, and a handful of
diverse few-shot examples — and emits ``resolution_ir_v1_1`` directly,
together with a small sample suite. Validation runs each sample through
``run_resolution_ir``; any failure is fed back to the LLM for one retry.

Why this exists: the removed template compiler path required the LLM
to emit a strict declarative DSL that was then transpiled by ~1000 lines
of hand-written templates. Minor LLM variations (e.g. declaring a
``perfect_th`` threshold without an ``expr``) caused whole procedures to
be rejected, so even simple d100 systems like Deep Files compiled to 0
check_specs. The direct path is permissive: any IR that runs cleanly
against its own samples is accepted, regardless of how the LLM chose to
shape it.

The output package is the canonical dice compiler artifact consumed by
chatrpg upload, chatlab dice-ir endpoints, and runtime check selection.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from agents.trpg.llm_json import (
    DEFAULT_STRUCTURED_LLM_MODEL,
    StructuredLLMError,
    call_llm_json_task,
    extract_json_object,
    resolve_llm_api_config,
)

from .compile_direct_prompts import (
    IR_COMPILE_SYSTEM,
    MAX_PROCEDURES_PER_RULEBOOK,
    PROCEDURE_ENUM_SYSTEM,
    build_compile_user_prompt,
    build_enum_user_prompt,
)
from .core import (
    DiceIRExecutionError,
    DiceIRManualResolutionRequired,
    DiceIRValidationError,
    run_resolution_ir,
)

logger = logging.getLogger("chatrpg.compile_direct")

COMPILER_STRATEGY = "direct_ir_v1"
COMPILED_PACKAGE_VERSION = "compiled_check_specs_v1"
DEFAULT_DICE_COMPILER_MODEL = DEFAULT_STRUCTURED_LLM_MODEL
DEFAULT_MAX_RETRIES = 2
DEFAULT_PARALLEL_WORKERS = 4
DiceRuleCompilerError = StructuredLLMError
OnProgress = Optional[Callable[[str, str], Awaitable[None]]]
OnChunk = Optional[Callable[[str, str], Awaitable[None]]]
_OPTIONAL_RESOURCE_MAX_RE = re.compile(
    r"(^max_.*_(?:loss|cost)$|_(?:loss|cost)_max$)",
    re.I,
)


async def _progress(on_progress: OnProgress, label: str, status: str) -> None:
    if on_progress:
        await on_progress(label, status)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# Validation
# =============================================================================


def _samples_match(actual: Dict[str, Any], expected: Dict[str, Any]) -> List[str]:
    """Return human-readable mismatch strings, empty if everything matches."""
    out: List[str] = []
    if "primary_tier" in expected:
        if str(actual.get("primary_tier")) != str(expected["primary_tier"]):
            out.append(
                f"primary_tier: expected {expected['primary_tier']!r}, "
                f"got {actual.get('primary_tier')!r}"
            )
    if "passed" in expected:
        if bool(actual.get("passed")) != bool(expected["passed"]):
            out.append(f"passed: expected {expected['passed']}, got {actual.get('passed')}")
    if isinstance(expected.get("side_effects"), dict):
        actual_se = actual.get("side_effects") or {}
        actual_axes = actual.get("axes") if isinstance(actual.get("axes"), dict) else {}
        for k, v in expected["side_effects"].items():
            actual_value = actual_se.get(k)
            if actual_value is None and isinstance(actual_axes.get(k), dict):
                actual_value = actual_axes[k].get("value")
            if actual_value != v:
                out.append(f"side_effects.{k}: expected {v!r}, got {actual_value!r}")
    return out


def _validate_ir_with_samples(
    ir: Dict[str, Any], samples: List[Dict[str, Any]],
) -> Tuple[bool, List[str], List[Dict[str, Any]]]:
    """Run each sample through run_resolution_ir.

    Returns (all_passed, error_strings, sample_results).
    """
    if not isinstance(samples, list) or not samples:
        return False, ["no samples provided to validate IR"], []
    errors: List[str] = []
    results: List[Dict[str, Any]] = []
    for sample in samples:
        if not isinstance(sample, dict):
            errors.append("sample is not an object")
            continue
        name = str(sample.get("name") or "unnamed")
        args = sample.get("args") if isinstance(sample.get("args"), dict) else {}
        expected = sample.get("expected") if isinstance(sample.get("expected"), dict) else {}
        try:
            actual = run_resolution_ir(ir, args)
        except (
            DiceIRValidationError, DiceIRExecutionError, DiceIRManualResolutionRequired,
        ) as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            results.append({"name": name, "ok": False, "error": str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: unexpected {type(exc).__name__}: {exc}")
            results.append({"name": name, "ok": False, "error": str(exc)})
            continue
        mismatches = _samples_match(actual, expected)
        if mismatches:
            errors.append(f"{name}: " + "; ".join(mismatches))
            results.append({
                "name": name, "ok": False,
                "expected": expected, "actual_tier": actual.get("primary_tier"),
                "mismatches": mismatches,
            })
        else:
            results.append({"name": name, "ok": True})
    return (not errors), errors, results


def _normalize_ir_for_runtime(ir: Dict[str, Any]) -> None:
    """Clean up common LLM-emitted IR contract rough edges before validation."""

    contract = ir.get("input_contract")
    if not isinstance(contract, dict):
        return
    required = contract.get("required")
    if not isinstance(required, list):
        return
    optional = contract.get("optional")
    if not isinstance(optional, dict):
        optional = {}
        contract["optional"] = optional

    next_required: List[Any] = []
    for key in required:
        text = str(key or "").strip()
        if text and _OPTIONAL_RESOURCE_MAX_RE.search(text):
            spec = optional.get(text)
            if not isinstance(spec, dict):
                spec = {"type": "number", "default": 0}
            elif spec.get("default") is None:
                spec = {**spec, "default": 0}
            optional[text] = spec
            continue
        next_required.append(key)
    contract["required"] = next_required


# =============================================================================
# LLM phases
# =============================================================================


async def _enumerate_procedures(
    markdown: str,
    *,
    system_name: str,
    output_language: str,
    house_rules: str,
    cfg: Dict[str, str],
    stream: bool,
    on_chunk: OnChunk,
) -> List[Dict[str, Any]]:
    raw = await call_llm_json_task(
        stage="enumerate",
        model=cfg["model"], base_url=cfg["base_url"], api_key=cfg["api_key"],
        system_prefix=PROCEDURE_ENUM_SYSTEM,
        user_message=build_enum_user_prompt(
            markdown,
            system_name=system_name,
            output_language=output_language,
            house_rules=house_rules,
        ),
        stream=stream, on_chunk=on_chunk,
    )
    obj = extract_json_object(raw)
    if not isinstance(obj, dict):
        raise DiceRuleCompilerError("enumerate response was not a JSON object")
    procs = obj.get("procedures")
    if not isinstance(procs, list):
        raise DiceRuleCompilerError("enumerate response missing procedures[]")
    cleaned: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for p in procs[:MAX_PROCEDURES_PER_RULEBOOK]:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "").strip()
        if not pid or pid in seen_ids:
            continue
        seen_ids.add(pid)
        cleaned.append(p)
    return cleaned


async def _compile_one_procedure(
    procedure: Dict[str, Any],
    *,
    markdown: str,
    house_rules: str,
    output_language: str,
    cfg: Dict[str, str],
    max_retries: int,
    stream: bool,
    on_chunk: OnChunk,
) -> Dict[str, Any]:
    """Compile + validate one procedure with retry on validation failure."""
    proc_id = str(procedure.get("id") or "")
    history: List[Dict[str, Any]] = []
    last_ir: Optional[Dict[str, Any]] = None
    last_samples: List[Dict[str, Any]] = []

    for attempt in range(max_retries + 1):
        try:
            raw = await call_llm_json_task(
                stage=f"compile:{proc_id}",
                model=cfg["model"], base_url=cfg["base_url"], api_key=cfg["api_key"],
                system_prefix=IR_COMPILE_SYSTEM,
                user_message=build_compile_user_prompt(
                    markdown=markdown, procedure=procedure,
                    house_rules=house_rules, output_language=output_language,
                    error_history=history,
                ),
                stream=stream, on_chunk=on_chunk,
            )
        except Exception as exc:  # noqa: BLE001
            history.append({"ir": last_ir or {}, "errors": [f"LLM call failed: {exc}"]})
            continue

        try:
            obj = extract_json_object(raw)
        except Exception as exc:  # noqa: BLE001
            history.append({"ir": {}, "errors": [f"could not parse JSON: {exc}"]})
            continue

        if not isinstance(obj, dict):
            history.append({"ir": {}, "errors": ["LLM output was not a JSON object"]})
            continue
        ir = obj.get("ir")
        samples = obj.get("samples") or []
        if not isinstance(ir, dict):
            history.append({"ir": {}, "errors": ["LLM output missing `ir` object"]})
            continue
        _normalize_ir_for_runtime(ir)
        last_ir = ir
        last_samples = samples if isinstance(samples, list) else []

        ok, errors, sample_results = _validate_ir_with_samples(ir, last_samples)
        if ok:
            check_spec = {"engine": "generic_resolution_v1", "ir": ir}
            return {
                "ok": True,
                "check_spec_entry": {
                    "procedure_id": proc_id,
                    "name": procedure.get("name") or proc_id,
                    "primary_family": str(procedure.get("primary_family") or ""),
                    "check_spec": check_spec,
                    "validation": {
                        "ok": True,
                        "sample_count": len(sample_results),
                        "samples": sample_results,
                    },
                    "samples": last_samples,
                },
            }
        history.append({"ir": ir, "errors": errors})
        logger.info(
            "[compile_direct] %s attempt %d/%d failed: %s",
            proc_id, attempt + 1, max_retries + 1,
            errors[0] if errors else "unknown",
        )

    return {
        "ok": False,
        "unsupported_entry": {
            "procedure_id": proc_id,
            "name": procedure.get("name") or proc_id,
            "primary_family": procedure.get("primary_family"),
            "reason": "validation failed after retries",
            "last_ir": last_ir,
            "last_samples": last_samples,
            "history": history,
        },
    }


def _pick_default(check_specs: List[Dict[str, Any]]) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Pick a sensible default procedure id from the compiled list.

    Prefer ids containing 'standard', 'skill', 'check', 'task' — these
    tend to be the bread-and-butter resolution. Fall back to first.
    """
    if not check_specs:
        return "", None
    for kw in ("standard", "skill", "task", "check"):
        for entry in check_specs:
            pid = str(entry.get("procedure_id") or "").lower()
            if kw in pid:
                return entry["procedure_id"], entry["check_spec"]
    first = check_specs[0]
    return first["procedure_id"], first["check_spec"]


# =============================================================================
# Public entry point
# =============================================================================


async def compile_to_ir_direct(
    markdown: str,
    *,
    system_name: str = "",
    house_rules: str = "",
    model: str = DEFAULT_DICE_COMPILER_MODEL,
    base_url: str = "",
    api_key: str = "",
    output_language: str = "en",
    stream: bool = False,
    max_retries: int = DEFAULT_MAX_RETRIES,
    parallel_workers: int = DEFAULT_PARALLEL_WORKERS,
    on_progress: OnProgress = None,
    on_chunk: OnChunk = None,
) -> Dict[str, Any]:
    """Compile a rulebook to runtime check_specs via direct LLM → IR.

    Returns the canonical dice IR package. Distinguishing field:
    ``compiler_strategy = "direct_ir_v1"``.
    """
    if not (markdown or "").strip():
        raise DiceRuleCompilerError("empty rulebook markdown")

    cfg = resolve_llm_api_config(model=model, base_url=base_url, api_key=api_key)
    await _progress(on_progress, "enumerate", f"identifying procedures with {cfg['model']}")

    procedures = await _enumerate_procedures(
        markdown,
        system_name=system_name, output_language=output_language,
        house_rules=house_rules, cfg=cfg,
        stream=stream, on_chunk=on_chunk,
    )
    if not procedures:
        raise DiceRuleCompilerError("LLM did not enumerate any procedures")

    await _progress(
        on_progress, "compile",
        f"compiling {len(procedures)} procedures "
        f"(parallel={parallel_workers}, retries={max_retries})",
    )

    sem = asyncio.Semaphore(max(1, parallel_workers))

    async def _gated(proc: Dict[str, Any]) -> Dict[str, Any]:
        async with sem:
            return await _compile_one_procedure(
                proc,
                markdown=markdown, house_rules=house_rules,
                output_language=output_language, cfg=cfg,
                max_retries=max_retries, stream=stream, on_chunk=on_chunk,
            )

    results = await asyncio.gather(*[_gated(p) for p in procedures], return_exceptions=False)

    check_specs: List[Dict[str, Any]] = []
    unsupported: List[Dict[str, Any]] = []
    for r in results:
        if r.get("ok"):
            check_specs.append(r["check_spec_entry"])
        else:
            unsupported.append(r["unsupported_entry"])

    default_proc_id, default_spec = _pick_default(check_specs)

    compiled_block = {
        "schema_version": COMPILED_PACKAGE_VERSION,
        "compiled_at": _now_iso(),
        "system_name": system_name,
        "default_procedure_id": default_proc_id,
        "default_check_spec": default_spec,
        "check_specs": check_specs,
        "unsupported_procedures": unsupported,
        "overall_ok": bool(check_specs) and not unsupported,
    }

    logger.info(
        "[compile_direct] done procedures=%d ok=%d unsupported=%d default=%s",
        len(procedures), len(check_specs), len(unsupported), default_proc_id,
    )

    return {
        "schema_version": "rulebook_dice_compilation_v1",
        "compiled_at": _now_iso(),
        "model": cfg["model"],
        "compiler_strategy": COMPILER_STRATEGY,
        "house_rules": house_rules or None,
        "compiled": compiled_block,
    }
