"""Example IR fixtures for docs, debug scripts, and regression tests."""

COC_SKILL_CHECK_IR = {
    "schema_version": "resolution_ir_v1_1",
    "id": "coc.skill_check",
    "name": "Call of Cthulhu 7e skill check",
    "primary_family": "sum_vs_target",
    "mechanic_tags": ["roll_under", "tier_bands", "critical", "fumble", "d100"],
    "input_contract": {
        "required": ["roll", "skill"],
        "optional": {"skill_name": {"type": "string"}},
    },
    "steps": [
        {"id": "roll", "op": "read_rolls", "group": "main", "expr": "1d100"},
        {"id": "die", "op": "sum_values", "from": "main", "write": "die_value"},
        {"id": "hard", "op": "formula", "expr": "args.skill // 2", "write": "hard_threshold"},
        {"id": "extreme", "op": "formula", "expr": "args.skill // 5", "write": "extreme_threshold"},
    ],
    "result_axes": [
        {
            "id": "skill_result",
            "kind": "tier",
            "outcomes": [
                {
                    "tier": "fumble",
                    "when": {
                        "any": [
                            {"var": "die_value", "eq": 100},
                            {"all": [
                                {"var": "die_value", "gte": 96},
                                {"var": "args.skill", "lt": 50},
                            ]},
                        ]
                    },
                    "passed": False,
                },
                {"tier": "critical", "when": {"var": "die_value", "eq": 1}, "passed": True},
                {"tier": "extreme", "when": {"var": "die_value", "lte": "extreme_threshold"}, "passed": True},
                {"tier": "hard", "when": {"var": "die_value", "lte": "hard_threshold"}, "passed": True},
                {"tier": "regular", "when": {"var": "die_value", "lte": "args.skill"}, "passed": True},
                {"tier": "failure", "default": True, "passed": False},
            ],
        }
    ],
    "primary_axis": "skill_result",
    "labels": {
        "critical": "Critical Success",
        "extreme": "Extreme Success",
        "hard": "Hard Success",
        "regular": "Regular Success",
        "failure": "Failure",
        "fumble": "Fumble",
    },
}


D20_VS_DC_IR = {
    "schema_version": "resolution_ir_v1_1",
    "id": "d20.dc_check",
    "name": "d20 vs DC",
    "primary_family": "sum_vs_target",
    "mechanic_tags": ["linear_sum", "target_number", "natural_critical"],
    "input_contract": {
        "required": ["roll", "target"],
        "optional": {"value": {"type": "number", "default": 0}},
    },
    "steps": [
        {"id": "roll", "op": "read_rolls", "group": "main", "expr": "1d20"},
        {"id": "die", "op": "sum_values", "from": "main", "write": "die_value"},
        {"id": "total", "op": "formula", "expr": "die_value + args.value", "write": "total"},
    ],
    "result_axes": [
        {
            "id": "task",
            "kind": "tier",
            "outcomes": [
                {"tier": "critical", "when": {"var": "roll.main.0", "eq": 20}, "passed": True},
                {"tier": "fumble", "when": {"var": "roll.main.0", "eq": 1}, "passed": False},
                {"tier": "success", "when": {"var": "total", "gte": "args.target"}, "passed": True},
                {"tier": "failure", "default": True, "passed": False},
            ],
        }
    ],
    "primary_axis": "task",
    "labels": {"critical": "暴击", "success": "成功", "failure": "失败", "fumble": "大失败"},
}


PBTA_BASIC_MOVE_IR = {
    "schema_version": "resolution_ir_v1_1",
    "id": "pbta.basic_move",
    "name": "PbtA Basic Move",
    "primary_family": "sum_bands",
    "mechanic_tags": ["2d6_curve", "tier_bands"],
    "input_contract": {
        "required": ["roll"],
        "optional": {"value": {"type": "number", "default": 0}},
    },
    "steps": [
        {"id": "roll", "op": "read_rolls", "group": "main", "expr": "2d6"},
        {"id": "sum", "op": "sum_values", "from": "main", "write": "dice_sum"},
        {"id": "total", "op": "formula", "expr": "dice_sum + args.value", "write": "total"},
    ],
    "result_axes": [
        {
            "id": "move_result",
            "kind": "tier",
            "outcomes": [
                {"tier": "hit", "when": {"var": "total", "gte": 10}, "passed": True},
                {"tier": "partial", "when": {"var": "total", "gte": 7}, "passed": True},
                {"tier": "miss", "default": True, "passed": False},
            ],
        }
    ],
    "primary_axis": "move_result",
    "labels": {"hit": "完全成功", "partial": "部分成功", "miss": "失败"},
}


FITD_ACTION_ROLL_IR = {
    "schema_version": "resolution_ir_v1_1",
    "id": "fitd.action_roll",
    "name": "Forged in the Dark Action Roll",
    "primary_family": "highest_die_pool",
    "mechanic_tags": ["dice_pool", "highest_die", "critical_count"],
    "input_contract": {
        "required": ["roll"],
        "optional": {"value": {"type": "integer", "default": 1}},
    },
    "steps": [
        {
            "id": "roll",
            "op": "read_rolls",
            "group": "pool",
            "expr": "Nd6",
            "count_from": "args.value",
        },
        {"id": "highest", "op": "max_value", "from": "pool", "write": "highest"},
        {"id": "sixes", "op": "tally", "from": "pool", "where": {"eq": 6}, "write": "sixes"},
    ],
    "result_axes": [
        {
            "id": "action_result",
            "kind": "tier",
            "outcomes": [
                {"tier": "critical", "when": {"var": "sixes", "gte": 2}, "passed": True},
                {"tier": "success", "when": {"var": "highest", "eq": 6}, "passed": True},
                {"tier": "partial", "when": {"var": "highest", "gte": 4}, "passed": True},
                {"tier": "failure", "default": True, "passed": False},
            ],
        }
    ],
    "primary_axis": "action_result",
    "labels": {
        "critical": "暴击",
        "success": "成功",
        "partial": "成功但有后果",
        "failure": "失败",
    },
}


TWOD20_TASK_IR = {
    "schema_version": "resolution_ir_v1_1",
    "id": "2d20.task",
    "name": "2d20 Task",
    "primary_family": "roll_under_pool",
    "mechanic_tags": [
        "weighted_success_count",
        "complication_axis",
        "resource_generation",
        "buy_extra_dice",
    ],
    "input_contract": {
        "required": ["roll", "target"],
        "optional": {
            "difficulty": {"type": "integer", "default": 1},
            "focus": {"type": "integer", "default": 1},
        },
    },
    "steps": [
        {"id": "roll", "op": "read_rolls", "group": "pool", "expr": "2d20"},
        {
            "id": "successes",
            "op": "weighted_success_count",
            "from": "pool",
            "success_where": {"lte": "args.target"},
            "crit_where": {"lte": "args.focus"},
            "success_weight": 1,
            "crit_weight": 2,
            "complication_where": {"eq": 20},
            "write": "successes",
            "write_complications": "complications",
        },
        {
            "id": "momentum",
            "op": "formula",
            "expr": "max(successes - args.difficulty, 0)",
            "write": "momentum",
        },
    ],
    "result_axes": [
        {
            "id": "task_success",
            "kind": "pass_fail",
            "pass_when": {"var": "successes", "gte": "args.difficulty"},
            "success_tier": "success",
            "failure_tier": "failure",
        },
        {"id": "momentum", "kind": "resource_delta", "from": "momentum"},
        {"id": "complications", "kind": "complication", "from": "complications"},
    ],
    "primary_axis": "task_success",
    "labels": {"success": "成功", "failure": "失败"},
}
