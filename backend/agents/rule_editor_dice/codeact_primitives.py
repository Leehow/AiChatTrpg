"""Deterministic primitives for the bounded dice CodeAct loop.

These are the only operations the CodeAct agent may invoke. They are
pure Python functions over in-memory IR dicts:

  - `run_sample(ir, args)`         — single dispatch into the IR runtime.
  - `simulate_probability(ir, n, seed, args_template, roll_groups)` —
    seeded Monte Carlo over the IR with synthetic dice values.
  - `generate_sample_cases(family, params)` — canned sample suites per
    canonical engine family (defined in `codeact_fixtures.py`).
  - `propose_ir_skeleton(family, procedure_id, name)` — pick a starter
    IR from the `check_ir/examples.py` fixtures.
  - `mutate_ir(ir, ops)` — apply a minimal JSON Patch subset (add,
    replace, remove) to a deep-copy of the IR.
  - `validate_proposal(ir, samples)` — re-runs the same validator the
    direct compiler uses.
  - `compile_one(description, ...)` — call the existing direct
    compiler as the canonical fallback / cold-start primitive.

What CodeAct may NOT do here:

  - No DB writes (those go through `apply_dice_proposal`).
  - No filesystem reads / writes outside this process's in-memory IR
    JSON.
  - No `exec`, no `eval`, no `subprocess`, no dynamic `__import__`.
  - No raw network — the only outbound call is the OpenAI-compat LLM
    used by `compile_one`, which routes through the same client the
    rest of the agent already uses.

Keep this module engine-/app-boundary clean: no FastAPI, no ORM
imports. The compile primitive talks to the deterministic compiler
through `compile_to_ir_direct` (which is itself an engine module).
"""

from __future__ import annotations

import copy
import logging
import random
import re
from typing import Any, Dict, List, Mapping, Optional

from agents.trpg.check_ir.compile_direct import (
    DiceRuleCompilerError,
    _validate_ir_with_samples,
    compile_to_ir_direct,
)
from agents.trpg.check_ir.core import (
    DiceIRExecutionError,
    DiceIRManualResolutionRequired,
    DiceIRValidationError,
    run_resolution_ir,
)

from .codeact_fixtures import (  # re-export the fixture primitives
    CodeActFixtureError,
    KNOWN_SAMPLE_FAMILIES,
    KNOWN_SKELETON_FAMILIES,
    generate_sample_cases,
    propose_ir_skeleton,
)


logger = logging.getLogger("chatrpg.rule_editor_dice.codeact.primitives")

_DICE_EXPR_RE = re.compile(r"^(?P<count>\d+|N)?d(?P<sides>\d+)$", re.I)


class CodeActPrimitiveError(Exception):
    """Raised when a primitive call is invalid (bad args, etc.)."""


# ---------------------------------------------------------------------------
# Run / simulate
# ---------------------------------------------------------------------------


def run_sample(
    ir: Mapping[str, Any], args: Mapping[str, Any],
) -> Dict[str, Any]:
    """Execute one IR run. Returns the runtime dict on success or a
    `{"ok": False, "error_kind": ..., "error": ...}` on failure.

    Catches all known IR exceptions so the CodeAct loop sees structured
    feedback instead of unhandled Python tracebacks.
    """

    try:
        result = run_resolution_ir(ir, args)
    except DiceIRValidationError as exc:
        return {"ok": False, "error_kind": "validation", "error": str(exc)}
    except DiceIRExecutionError as exc:
        return {"ok": False, "error_kind": "execution", "error": str(exc)}
    except DiceIRManualResolutionRequired as exc:
        return {"ok": False, "error_kind": "manual", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error_kind": "unexpected",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {"ok": True, "result": result}


def _extract_roll_groups(ir: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Pull (source_arg, count, sides) tuples out of every `read_rolls`
    step. The count is `None` for `Nd<sides>` groups whose count is
    data-driven; the caller must override via `roll_groups`.
    """

    out: List[Dict[str, Any]] = []
    steps = ir.get("steps") if isinstance(ir, Mapping) else None
    if not isinstance(steps, list):
        return out
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        if str(step.get("op") or "") != "read_rolls":
            continue
        expr = str(step.get("expr") or "")
        m = _DICE_EXPR_RE.match(expr.strip())
        if not m:
            continue
        sides = int(m.group("sides"))
        raw_count = m.group("count")
        count: Optional[int]
        if raw_count and raw_count != "N":
            count = int(raw_count)
        else:
            count = None
        out.append({
            "source_arg": str(step.get("source_arg") or "roll"),
            "sides": sides,
            "count": count,
            "count_from": step.get("count_from"),
        })
    return out


def simulate_probability(
    ir: Mapping[str, Any],
    *,
    n: int = 1000,
    seed: int = 42,
    args_template: Optional[Mapping[str, Any]] = None,
    roll_groups: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Run `n` seeded simulations of the IR. Returns:

        {
            "n": int,
            "seed": int,
            "tiers": {tier: int, ...},
            "pass_rate": float | None,
            "errors": int,
            "error_samples": [str, ...],
        }

    For each `read_rolls` step we auto-fill `args[source_arg]` with a
    random array of count/sides. Callers may pass `roll_groups` to
    override counts for Nd<sides> groups.
    """

    if n <= 0:
        raise CodeActPrimitiveError("simulate_probability requires n > 0")
    if n > 10000:
        raise CodeActPrimitiveError("simulate_probability hard cap n<=10000")

    rng = random.Random(seed)
    base_args = dict(args_template or {})
    groups = list(roll_groups or _extract_roll_groups(ir))

    tier_counts: Dict[str, int] = {}
    passed = 0
    errors = 0
    error_samples: List[str] = []

    for _ in range(n):
        sim_args: Dict[str, Any] = dict(base_args)
        for g in groups:
            count = g.get("count")
            if not isinstance(count, int) or count <= 0:
                cf = g.get("count_from")
                resolved: Optional[int] = None
                if isinstance(cf, str) and cf.startswith("args."):
                    key = cf[len("args."):]
                    val = sim_args.get(key)
                    if isinstance(val, int) and val > 0:
                        resolved = val
                if resolved is None:
                    raise CodeActPrimitiveError(
                        f"cannot resolve count for read_rolls group "
                        f"{g.get('source_arg')!r}; pass roll_groups override",
                    )
                count = resolved
            sides = int(g.get("sides") or 0)
            if sides <= 0:
                raise CodeActPrimitiveError(
                    f"invalid sides {sides} for group {g.get('source_arg')!r}",
                )
            sim_args[g["source_arg"]] = [
                rng.randint(1, sides) for _ in range(count)
            ]
        outcome = run_sample(ir, sim_args)
        if not outcome.get("ok"):
            errors += 1
            if len(error_samples) < 3:
                error_samples.append(str(outcome.get("error") or ""))
            continue
        res = outcome.get("result") or {}
        tier = str(res.get("primary_tier") or "")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        if res.get("passed"):
            passed += 1

    successful = max(n - errors, 0)
    pass_rate: Optional[float] = (
        passed / successful if successful > 0 else None
    )
    return {
        "n": n,
        "seed": seed,
        "tiers": tier_counts,
        "pass_rate": pass_rate,
        "errors": errors,
        "error_samples": error_samples,
    }


# ---------------------------------------------------------------------------
# Mutation (minimal JSON Patch)
# ---------------------------------------------------------------------------


def _resolve_pointer(doc: Any, pointer: str) -> Any:
    if pointer in ("", "/"):
        return doc
    if not pointer.startswith("/"):
        raise CodeActPrimitiveError(f"bad pointer {pointer!r}: must start with /")
    parts = [p.replace("~1", "/").replace("~0", "~") for p in pointer.split("/")[1:]]
    node = doc
    for part in parts:
        if isinstance(node, list):
            try:
                idx = int(part)
            except ValueError as exc:
                raise CodeActPrimitiveError(
                    f"pointer {pointer!r}: non-integer index {part!r}",
                ) from exc
            node = node[idx]
        elif isinstance(node, Mapping):
            if part not in node:
                raise CodeActPrimitiveError(
                    f"pointer {pointer!r}: missing key {part!r}",
                )
            node = node[part]
        else:
            raise CodeActPrimitiveError(
                f"pointer {pointer!r}: cannot descend into {type(node).__name__}",
            )
    return node


def _apply_one_patch_op(doc: Any, op: Mapping[str, Any]) -> None:
    kind = str(op.get("op") or "")
    path = str(op.get("path") or "")
    if kind not in {"add", "replace", "remove"}:
        raise CodeActPrimitiveError(f"unsupported patch op {kind!r}")
    if not path.startswith("/"):
        raise CodeActPrimitiveError(f"bad patch path {path!r}")
    parts = [p.replace("~1", "/").replace("~0", "~") for p in path.split("/")[1:]]
    if not parts:
        raise CodeActPrimitiveError("patch path must address a child of the root")
    parent = (
        _resolve_pointer(doc, "/" + "/".join(parts[:-1]))
        if len(parts) > 1 else doc
    )
    last = parts[-1]
    if isinstance(parent, list):
        if last == "-":
            if kind == "remove":
                raise CodeActPrimitiveError("remove on '-' not allowed")
            parent.append(op.get("value"))
            return
        try:
            idx = int(last)
        except ValueError as exc:
            raise CodeActPrimitiveError(
                f"patch path {path!r}: non-integer index {last!r}",
            ) from exc
        if kind == "remove":
            del parent[idx]
        elif kind == "add":
            parent.insert(idx, op.get("value"))
        else:
            parent[idx] = op.get("value")
        return
    if not isinstance(parent, dict):
        raise CodeActPrimitiveError(
            f"patch path {path!r}: parent is {type(parent).__name__}",
        )
    if kind == "remove":
        if last not in parent:
            raise CodeActPrimitiveError(f"remove on missing key {last!r}")
        del parent[last]
    else:
        parent[last] = op.get("value")


def mutate_ir(
    ir: Mapping[str, Any], ops: List[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Return a deep-copied IR with the given patch ops applied. Input
    is never mutated; on any bad op the partial state is discarded.
    """

    if not isinstance(ops, list):
        raise CodeActPrimitiveError("mutate_ir ops must be a list")
    out = copy.deepcopy(dict(ir))
    for op in ops:
        if not isinstance(op, Mapping):
            raise CodeActPrimitiveError("mutate_ir op must be an object")
        _apply_one_patch_op(out, op)
    return out


# ---------------------------------------------------------------------------
# Validation + compile fallback
# ---------------------------------------------------------------------------


def validate_proposal(
    ir: Mapping[str, Any], samples: List[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Run the same gate the direct compiler uses
    (`_validate_ir_with_samples`). Returns `{ok, errors, sample_results}`.
    """

    ok, errors, results = _validate_ir_with_samples(
        dict(ir), [dict(s) for s in samples],
    )
    return {"ok": ok, "errors": errors, "sample_results": results}


async def compile_one(
    description: str,
    *,
    name: str,
    engine_hint: str,
    system_name: str,
    output_language: str,
    cfg: Mapping[str, str],
) -> Dict[str, Any]:
    """Wrap the deterministic compiler as a single-procedure primitive.
    Returns the canonical `package` dict that `apply_dice_proposal`
    consumes.
    """

    if not description.strip():
        raise CodeActPrimitiveError("compile_one description required")
    title = system_name or "Custom Ruleset"
    lines = [f"# {title}", "", f"## Procedure: {name or 'procedure'}", "",
             description.strip(), ""]
    if engine_hint:
        lines.append(
            f"_Engine hint: this procedure should compile under "
            f"`{engine_hint}` if compatible._\n"
        )
    md = "\n".join(lines)
    try:
        return await compile_to_ir_direct(
            md,
            system_name=system_name,
            house_rules="",
            model=cfg["model"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            output_language=output_language,
        )
    except DiceRuleCompilerError as exc:
        raise CodeActPrimitiveError(f"compile_one failed: {exc}") from exc


__all__ = [
    "CodeActFixtureError",
    "CodeActPrimitiveError",
    "KNOWN_SAMPLE_FAMILIES",
    "KNOWN_SKELETON_FAMILIES",
    "compile_one",
    "generate_sample_cases",
    "mutate_ir",
    "propose_ir_skeleton",
    "run_sample",
    "simulate_probability",
    "validate_proposal",
]
