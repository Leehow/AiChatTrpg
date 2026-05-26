"""AST-bounded scalar expression evaluator for the dice-rule IR.

Used by ``formula`` steps and ``expr`` axis values. Intentionally small:
arithmetic, unary minus/plus, ``floor`` / ``ceil`` / ``min`` / ``max`` /
``abs``, and name/attribute lookups that delegate to ``_resolve_value`` in
``core_runtime``. Collection work belongs in explicit steps.
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any, Dict

from .core_runtime import _resolve_value
from .core_types import DiceIRValidationError


_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_ALLOWED_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_ALLOWED_FUNCS = {
    "floor": math.floor,
    "ceil": math.ceil,
    "min": min,
    "max": max,
    "abs": abs,
}


def _eval_scalar_expr(expr: str, ctx: Dict[str, Any]) -> Any:
    """Evaluate a deliberately small scalar expression language.

    Collection work is intentionally not supported here. Use explicit steps for
    tallying, selection, symbol cancellation, and branch logic.
    """

    tree = ast.parse(expr, mode="eval")
    return _eval_ast(tree.body, ctx)


def _eval_ast(node: ast.AST, ctx: Dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise DiceIRValidationError("formula constants must be numeric")
    if isinstance(node, ast.Name):
        return _resolve_value(node.id, ctx)
    if isinstance(node, ast.Attribute):
        return _resolve_value(_attr_path(node), ctx)
    if isinstance(node, ast.BinOp):
        fn = _ALLOWED_BINOPS.get(type(node.op))
        if not fn:
            raise DiceIRValidationError("formula uses unsupported operator")
        return fn(_eval_ast(node.left, ctx), _eval_ast(node.right, ctx))
    if isinstance(node, ast.UnaryOp):
        fn = _ALLOWED_UNARY.get(type(node.op))
        if not fn:
            raise DiceIRValidationError("formula uses unsupported unary operator")
        return fn(_eval_ast(node.operand, ctx))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            raise DiceIRValidationError("formula uses unsupported function")
        args = [_eval_ast(arg, ctx) for arg in node.args]
        return _ALLOWED_FUNCS[node.func.id](*args)
    raise DiceIRValidationError(f"formula uses unsupported expression: {type(node).__name__}")


def _attr_path(node: ast.Attribute) -> str:
    parts = [node.attr]
    cur = node.value
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    raise DiceIRValidationError("invalid formula reference")
