"""Runtime context helpers for the dice-rule IR interpreter.

Provides the predicate and value-resolution layer that step ops and axis
computation build on: reading ``ctx`` (``args`` / ``vars`` / ``groups``),
coercing roll inputs, matching dice and conditions, and writing trace entries.
"""

from __future__ import annotations

import operator
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .core_types import (
    DiceIRExecutionError,
    DiceIRValidationError,
    Die,
)


_DICE_VALUE_RE = re.compile(
    r"^\s*(?P<count>\d*)d(?P<sides>\d+)(?P<mod>\s*[+-]\s*\d+)?\s*$",
    re.I,
)


def _coerce_roll_values(raw: Any) -> List[int]:
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        for key in ("main", "roll", "dice", "values", "results"):
            if key in raw:
                return _coerce_roll_values(raw.get(key))
        if len(raw) == 1:
            return _coerce_roll_values(next(iter(raw.values())))
        return []
    if isinstance(raw, list):
        return [int(x) for x in raw]
    if isinstance(raw, (int, float)):
        return [int(raw)]
    text = str(raw).strip().strip("[]")
    if not text:
        return []
    out: List[int] = []
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if part:
            out.append(int(float(part)))
    return out


def _coerce_int_list(raw: Any) -> List[int]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [int(x) for x in raw]
    if isinstance(raw, (int, float)):
        return [int(raw)]
    text = str(raw).strip().strip("[]")
    if not text:
        return []
    return [int(float(p.strip())) for p in text.replace(";", ",").split(",") if p.strip()]


def _resolve_dice_like_value(raw: Any, roll_values: Any = None, *, mode: str = "value") -> Any:
    if raw is None or isinstance(raw, (int, float, bool)):
        return raw
    text = str(raw).strip()
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    match = _DICE_VALUE_RE.match(text)
    if not match:
        return raw
    count_text = match.group("count")
    count = int(count_text) if count_text else 1
    sides = int(match.group("sides"))
    mod_text = (match.group("mod") or "").replace(" ", "")
    modifier = int(mod_text) if mod_text else 0
    if mode == "max":
        return count * sides + modifier
    rolls = _coerce_int_list(roll_values)
    if len(rolls) < count:
        return text
    return sum(rolls[:count]) + modifier


def _optional_indices(ref: Any, ctx: Dict[str, Any]) -> List[int]:
    if not ref:
        return []
    try:
        raw = _resolve_value(ref, ctx)
    except DiceIRExecutionError:
        return []
    return _coerce_int_list(raw)


def _write_var(ctx: Dict[str, Any], step: Mapping[str, Any], value: Any) -> None:
    key = step.get("write")
    if not key:
        raise DiceIRValidationError(f"{step.get('op')} step requires write")
    ctx["vars"][str(key)] = value


def _group(ctx: Dict[str, Any], group_id: str) -> List[Die]:
    if not group_id or group_id not in ctx["groups"]:
        raise DiceIRExecutionError(f"unknown die group: {group_id}")
    return ctx["groups"][group_id]


def _resolve_value(value: Any, ctx: Dict[str, Any]) -> Any:
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    if text.startswith("args."):
        return _deep_get(ctx["args"], text[5:])
    if text.startswith("vars."):
        return _deep_get(ctx["vars"], text[5:])
    if text.startswith("roll."):
        parts = text.split(".")
        if len(parts) == 3:
            die = _group(ctx, parts[1])[int(parts[2])]
            return die.value
        raise DiceIRExecutionError(f"invalid roll reference: {text}")
    if text in ctx["vars"]:
        return ctx["vars"][text]
    if text in ctx["args"]:
        return ctx["args"][text]
    return text


def _deep_get(obj: Mapping[str, Any], dotted: str) -> Any:
    cur: Any = obj
    for part in dotted.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            raise DiceIRExecutionError(f"unknown reference: {dotted}")
    return cur


def _condition_matches(cond: Any, ctx: Dict[str, Any]) -> bool:
    if not isinstance(cond, Mapping):
        return False
    if "all" in cond:
        return all(_condition_matches(c, ctx) for c in cond.get("all") or [])
    if "any" in cond:
        return any(_condition_matches(c, ctx) for c in cond.get("any") or [])
    if "not" in cond:
        return not _condition_matches(cond.get("not") or {}, ctx)

    try:
        left = _resolve_value(cond.get("var"), ctx) if "var" in cond else None
    except (DiceIRExecutionError, DiceIRValidationError):
        return False
    comparisons = {
        "eq": operator.eq,
        "neq": operator.ne,
        "gt": operator.gt,
        "gte": operator.ge,
        "lt": operator.lt,
        "lte": operator.le,
    }
    for key, fn in comparisons.items():
        if key in cond:
            try:
                return bool(fn(left, _resolve_value(cond[key], ctx)))
            except (DiceIRExecutionError, DiceIRValidationError, TypeError, ValueError):
                return False
    if "in" in cond:
        values = cond.get("in") or []
        return left in values
    return False


def _die_matches(die: Die, cond: Mapping[str, Any], ctx: Optional[Dict[str, Any]] = None) -> bool:
    if not cond:
        return True
    if "all" in cond:
        return all(_die_matches(die, c, ctx) for c in cond.get("all") or [])
    if "any" in cond:
        return any(_die_matches(die, c, ctx) for c in cond.get("any") or [])
    if "not" in cond:
        return not _die_matches(die, cond.get("not") or {}, ctx)
    value_comparisons = {
        "eq": operator.eq,
        "neq": operator.ne,
        "gt": operator.gt,
        "gte": operator.ge,
        "lt": operator.lt,
        "lte": operator.le,
    }
    for key, fn in value_comparisons.items():
        if key in cond:
            right = _resolve_value(cond[key], ctx) if ctx is not None else cond[key]
            if not fn(die.value, right):
                return False
    if "tag" in cond and str(cond["tag"]) not in die.tags:
        return False
    if "tag_not" in cond and str(cond["tag_not"]) in die.tags:
        return False
    if "source_group" in cond and die.source_group != str(cond["source_group"]):
        return False
    if "kept" in cond and die.kept is not bool(cond["kept"]):
        return False
    return True


def _values(dice: Iterable[Die], kept_marker: bool = False) -> str:
    vals = []
    for die in dice:
        val = str(die.value)
        if kept_marker and not die.kept:
            val = f"({val})"
        vals.append(val)
    return "[" + ", ".join(vals) + "]"


def _trace(ctx: Dict[str, Any], step: Mapping[str, Any], message: str) -> None:
    ctx["trace"].append({
        "step": step.get("id") or step.get("op"),
        "op": step.get("op"),
        "message": message,
    })
