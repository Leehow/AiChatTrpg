"""Built-in CoC 7e runtime check specs.

These are precompiled ``resolution_ir_v1_1`` artifacts. They are used only as
runtime fallbacks when an uploaded ruleset lacks its own compiled SAN procedure.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_COC7_SANITY_ROLL_IR: dict[str, Any] = {
    "schema_version": "resolution_ir_v1_1",
    "id": "coc7.sanity_roll",
    "name": "Sanity Roll",
    "primary_family": "percentile_roll_under",
    "routing": {
        "aliases": [
            "SAN",
            "Sanity",
            "Sanity Check",
            "sancheck",
            "sanity check",
            "理智",
            "理智检定",
            "理智损失",
        ],
        "semantic_tags": ["sanity", "fear", "horror", "mental_resource_loss"],
    },
    "input_contract": {
        "required": ["roll", "value"],
        "optional": {
            "difficulty": {"type": "string", "default": "regular"},
            "success_san_loss": {"type": "number|string", "default": 0},
            "failure_san_loss": {"type": "number|string", "default": 0},
            "max_failure_san_loss": {"type": "number|string|null", "default": 0},
            "success_san_loss_roll": {"type": "number[]|null", "default": None},
            "failure_san_loss_roll": {"type": "number[]|null", "default": None},
        },
    },
    "steps": [
        {"id": "roll_main", "op": "read_rolls", "group": "main", "expr": "1d100"},
        {"id": "natural_roll", "op": "sum_values", "from": "main", "write": "natural_roll"},
        {"id": "skill", "op": "formula", "expr": "args.value", "write": "skill"},
        {"id": "hard_th", "op": "formula", "expr": "floor(skill / 2)", "write": "hard_th"},
        {"id": "extreme_th", "op": "formula", "expr": "floor(skill / 5)", "write": "extreme_th"},
        {
            "id": "fumble_th",
            "op": "conditional_value",
            "cases": [{"when": {"var": "skill", "lt": 50}, "value": 96}],
            "default": 100,
            "write": "fumble_th",
        },
        {
            "id": "success_san_loss_value",
            "op": "resolve_dice_value",
            "source": "args.success_san_loss",
            "roll_source_arg": "success_san_loss_roll",
            "write": "success_san_loss_value",
        },
        {
            "id": "failure_san_loss_value",
            "op": "resolve_dice_value",
            "source": "args.failure_san_loss",
            "roll_source_arg": "failure_san_loss_roll",
            "write": "failure_san_loss_value",
        },
        {
            "id": "effective_failure_max",
            "op": "formula",
            "expr": "max(failure_san_loss_value, args.max_failure_san_loss)",
            "write": "effective_failure_max",
        },
        {
            "id": "san_loss",
            "op": "conditional_value",
            "cases": [
                {"when": {"var": "natural_roll", "gte": "fumble_th"}, "value": "effective_failure_max"},
                {"when": {"var": "natural_roll", "lte": "skill"}, "value": "success_san_loss_value"},
            ],
            "default": "failure_san_loss_value",
            "write": "san_loss",
        },
    ],
    "result_axes": [
        {
            "id": "san_result",
            "kind": "tier",
            "outcomes": [
                {"tier": "critical", "when": {"var": "natural_roll", "eq": 1}, "passed": True},
                {"tier": "fumble", "when": {"var": "natural_roll", "gte": "fumble_th"}, "passed": False},
                {"tier": "extreme", "when": {"var": "natural_roll", "lte": "extreme_th"}, "passed": True},
                {"tier": "hard", "when": {"var": "natural_roll", "lte": "hard_th"}, "passed": True},
                {"tier": "regular", "when": {"var": "natural_roll", "lte": "skill"}, "passed": True},
                {"tier": "failure", "default": True, "passed": False},
            ],
        },
        {"id": "san_loss", "kind": "resource_delta", "from": "san_loss"},
        {
            "id": "sanity_flags",
            "kind": "flags",
            "flags": [
                {
                    "id": "temporary_insanity_check_trigger",
                    "label": "单次 SAN 损失 >= 5，需处理临时疯狂触发",
                    "when": {"var": "san_loss", "gte": 5},
                }
            ],
        },
    ],
    "primary_axis": "san_result",
    "labels": {
        "critical": "大成功",
        "extreme": "极难成功",
        "hard": "困难成功",
        "regular": "成功",
        "failure": "失败",
        "fumble": "大失败",
    },
}


def coc7_sanity_roll_ir() -> dict[str, Any]:
    return deepcopy(_COC7_SANITY_ROLL_IR)


def coc7_sanity_roll_check_spec() -> dict[str, Any]:
    return {
        "engine": "generic_resolution_v1",
        "ir": coc7_sanity_roll_ir(),
        "aliases": deepcopy(_COC7_SANITY_ROLL_IR["routing"]["aliases"]),
        "semantic_tags": deepcopy(_COC7_SANITY_ROLL_IR["routing"]["semantic_tags"]),
        "_runtime_procedure_id": "coc7.sanity_roll",
    }
