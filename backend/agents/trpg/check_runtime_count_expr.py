"""Count / value / dice expression helpers for the CHECK runtime facade.

These helpers parse the ``count_from`` and ``source`` references that appear
on generic-resolution IR steps. They are pure functions over ``CheckArgs`` and
a ``vars_seen`` mapping; no I/O, no dice rolling.
"""

from __future__ import annotations

import ast
import operator
import re
from typing import Any, Mapping

from .check_resolver import CheckArgs


_DICE_LIKE_VALUE_RE = re.compile(
    r"^\s*(?:\d*)d\d+(?:\s*[+-]\s*\d+)?\s*$",
    re.IGNORECASE,
)


def needs_auto_roll(raw: Any) -> bool:
    if raw is None:
        return True
    text = str(raw).strip().lower()
    return text in {"", "auto", "random", "roll"}


_COUNT_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
}


def _arg_value(args: CheckArgs, key: str) -> Any:
    if key == "value":
        return args.value
    if key == "target":
        return args.target
    if key == "bonus":
        return args.bonus
    if key == "penalty":
        return args.penalty
    if key == "roll":
        return args.roll
    return (args.extras or {}).get(key)


def _resolve_count_ref(
    raw: Any,
    args: CheckArgs,
    vars_seen: Mapping[str, Any],
) -> Any:
    if isinstance(raw, (int, float)):
        return raw
    text = str(raw or "").strip()
    if not text:
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    if text.startswith("args."):
        return _arg_value(args, text[5:])
    if text.startswith("vars."):
        return vars_seen.get(text[5:])
    if text in vars_seen:
        return vars_seen[text]
    value = _arg_value(args, text)
    if value is not None:
        return value
    return _eval_count_expr(text, args, vars_seen)


def _resolve_auxiliary_source(
    raw: Any,
    args: CheckArgs,
    vars_seen: Mapping[str, Any],
) -> Any:
    if isinstance(raw, (int, float, bool)) or raw is None:
        return raw
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.startswith("args."):
        return _arg_value(args, text[5:])
    if text.startswith("vars."):
        return vars_seen.get(text[5:])
    if text in vars_seen:
        return vars_seen[text]
    value = _arg_value(args, text)
    if value is not None:
        return value
    return raw


def _eval_count_expr(
    expr: str,
    args: CheckArgs,
    vars_seen: Mapping[str, Any],
) -> Any:
    tree = ast.parse(expr, mode="eval")
    return _eval_count_ast(tree.body, args, vars_seen)


def _eval_count_ast(
    node: ast.AST,
    args: CheckArgs,
    vars_seen: Mapping[str, Any],
) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Name):
        value = _resolve_count_ref(node.id, args, vars_seen)
        if value is None:
            raise ValueError(f"unknown count ref: {node.id}")
        return value
    if isinstance(node, ast.Attribute):
        value = _resolve_count_ref(_attr_path(node), args, vars_seen)
        if value is None:
            raise ValueError("unknown count attr")
        return value
    if isinstance(node, ast.BinOp) and type(node.op) in _COUNT_BINOPS:
        return _COUNT_BINOPS[type(node.op)](
            _eval_count_ast(node.left, args, vars_seen),
            _eval_count_ast(node.right, args, vars_seen),
        )
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_count_ast(node.operand, args, vars_seen)
    raise ValueError(f"unsupported count expression: {type(node).__name__}")


def _attr_path(node: ast.Attribute) -> str:
    parts = [node.attr]
    cur = node.value
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    raise ValueError("invalid attr path")


def _display_expr(expr: str, count_override: int | None) -> str:
    text = str(expr or "").strip()
    if count_override is None:
        return text
    return re.sub(r"^\s*N(?=d)", str(count_override), text, flags=re.I)


def _count_override_for_step(
    step: Mapping[str, Any],
    args: CheckArgs,
    vars_seen: Mapping[str, Any],
) -> int | None:
    raw = step.get("count_from")
    if raw in (None, ""):
        return None
    try:
        value = _resolve_count_ref(raw, args, vars_seen)
    except Exception:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dice_expression_from_value(raw: Any) -> str:
    if raw is None or isinstance(raw, (int, float, bool)):
        return ""
    text = str(raw or "").strip()
    if not _DICE_LIKE_VALUE_RE.match(text):
        return ""
    return re.sub(r"\s+", "", text)
