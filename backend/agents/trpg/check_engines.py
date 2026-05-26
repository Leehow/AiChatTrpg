"""Per-engine resolver implementations for TRPG dice checks.

Each engine is a pure function ``(args: CheckArgs, spec: dict) → CheckResult``
that encodes the arithmetic of a family of tabletop systems:

  - ``coc_7e_d100`` — Call of Cthulhu 7e / Delta Green percentile
  - ``brp_d100``    — Basic Roleplaying (no hard/extreme tiers)
  - ``d20_vs_dc``   — D&D 5e / Pathfinder roll + mod vs DC
  - ``pbta_2d6``    — Powered-by-the-Apocalypse 2d6 + stat tiers
  - ``pool_count_n``— Count dice ≥ per-die-target (WOD, Triangle Agency)
  - ``custom_llm``  — Unresolved fallback when no engine matches

Registration lives in ``check_engine_registry``; dispatch lives in
``check_resolver.resolve_check``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .check_engine_registry import register_engine
from .check_resolver import (
    CheckArgs, CheckResult,
    coerce_int, coerce_float, parse_roll_list, label,
)
from .coc_runtime import coc_tier_rule_effect


# ---------------------------------------------------------------------------
# CoC 7e d100
# ---------------------------------------------------------------------------


_COC_DIFFICULTY_TIER = {
    "regular": "regular", "normal": "regular", "常规": "regular",
    "hard": "hard", "困难": "hard", "hard_success": "hard",
    "extreme": "extreme", "极难": "extreme", "extreme_success": "extreme",
}


def _coc_bonus_penalty_note(bonus: int, penalty: int) -> str:
    """We can't re-draw dice after the fact — flag mis-usage for the audit."""
    if bonus == penalty:
        return ""
    tag = f"bonus={bonus} penalty={penalty}"
    return f"bonus/penalty dice noted but not resimulated ({tag})"


def _coc_pick_tier(
    roll: int, skill: int, extreme_th: int, hard_th: int, fumble_th: int,
) -> str:
    if roll == 1:
        return "critical"
    if roll >= fumble_th:
        return "fumble"
    if roll <= extreme_th:
        return "extreme"
    if roll <= hard_th:
        return "hard"
    if roll <= skill:
        return "regular"
    return "failure"


def _coc_explain(
    tier: str, roll: int, skill: int,
    hard_th: int, extreme_th: int, fumble_th: int,
) -> str:
    if tier == "critical":
        return f"{roll} = 01 → 大成功"
    if tier == "fumble":
        return f"{roll} ≥ {fumble_th} → 大失败"
    if tier == "extreme":
        return f"{roll} ≤ {extreme_th} (技能/5) → 极难成功"
    if tier == "hard":
        return f"{roll} ≤ {hard_th} (技能/2) → 困难成功"
    if tier == "regular":
        return f"{roll} ≤ {skill} → 常规成功"
    return f"{roll} > {skill} → 失败"


def resolve_coc_7e_d100(args: CheckArgs, spec: Dict[str, Any]) -> CheckResult:
    rolls = parse_roll_list(args.roll)
    if not rolls:
        return CheckResult(
            tier="failure", tier_label=label(spec, "coc_7e_d100", "failure"),
            engine="coc_7e_d100",
            warnings=["CHECK marker missing roll value"],
        )
    roll = rolls[0]
    if roll < 1 or roll > 100:
        return CheckResult(
            tier="failure", tier_label=label(spec, "coc_7e_d100", "failure"),
            engine="coc_7e_d100", roll_display=str(roll),
            warnings=[f"d100 roll out of range: {roll}"],
        )
    value = coerce_float(args.value)
    if value is None or value <= 0:
        return CheckResult(
            tier="failure", tier_label=label(spec, "coc_7e_d100", "failure"),
            engine="coc_7e_d100", roll_display=str(roll),
            warnings=["CHECK marker missing skill value"],
        )
    skill = int(value)

    hard_th = skill // 2
    extreme_th = skill // 5
    fumble_th = 96 if skill < 50 else 100
    required = _COC_DIFFICULTY_TIER.get(
        (args.difficulty or "regular").lower(), "regular",
    )

    tier = _coc_pick_tier(roll, skill, extreme_th, hard_th, fumble_th)
    tier_rank = {"fumble": -2, "failure": -1, "regular": 1, "hard": 2,
                 "extreme": 3, "critical": 4}
    req_rank = {"regular": 1, "hard": 2, "extreme": 3}[required]
    passed = tier_rank.get(tier, -1) >= req_rank

    parts = [_coc_explain(
        tier, roll, skill, hard_th, extreme_th, fumble_th,
    )]
    if required != "regular":
        parts.append(
            f"要求 {label(spec, 'coc_7e_d100', required)} "
            f"→ {'通过' if passed else '未通过'}"
        )

    warnings: List[str] = []
    bp_note = ""
    if not (args.extras or {}).get("coc_bonus_penalty_resolved"):
        bp_note = _coc_bonus_penalty_note(args.bonus, args.penalty)
    if bp_note:
        warnings.append(bp_note)
    side_effects: Dict[str, Any] = {}
    tier_effect = coc_tier_rule_effect(tier)
    if tier_effect:
        side_effects["额外效果"] = tier_effect

    return CheckResult(
        tier=tier,
        tier_label=label(spec, "coc_7e_d100", tier),
        passed=passed,
        explanation=" | ".join(parts),
        thresholds={
            "regular": skill, "hard": hard_th, "extreme": extreme_th,
            "fumble": fumble_th, "critical": 1,
        },
        warnings=warnings,
        engine="coc_7e_d100",
        roll_display=str(roll),
        side_effects=side_effects,
    )


# ---------------------------------------------------------------------------
# BRP d100 (simpler — no hard/extreme tiers, optional "special")
# ---------------------------------------------------------------------------


def resolve_brp_d100(args: CheckArgs, spec: Dict[str, Any]) -> CheckResult:
    rolls = parse_roll_list(args.roll)
    value = coerce_float(args.value)
    if not rolls or value is None:
        return CheckResult(
            tier="failure", tier_label=label(spec, "brp_d100", "failure"),
            engine="brp_d100",
            warnings=["CHECK marker missing roll or value"],
        )
    roll = rolls[0]
    skill = int(value)
    special = skill // 5
    fumble_th = 96 if skill < 50 else 100

    if roll == 1:
        tier = "special"
    elif roll >= fumble_th:
        tier = "fumble"
    elif roll <= special:
        tier = "special"
    elif roll <= skill:
        tier = "regular"
    else:
        tier = "failure"

    passed = tier in ("special", "regular")
    if tier == "fumble":
        explanation = f"{roll} ≥ {fumble_th} → 大失败"
    elif tier == "special":
        explanation = f"{roll} ≤ {special} (技能/5) → 特殊成功"
    elif tier == "regular":
        explanation = f"{roll} ≤ {skill} → 成功"
    else:
        explanation = f"{roll} > {skill} → 失败"

    return CheckResult(
        tier=tier, tier_label=label(spec, "brp_d100", tier),
        passed=passed, explanation=explanation,
        thresholds={"regular": skill, "special": special, "fumble": fumble_th},
        engine="brp_d100", roll_display=str(roll),
    )


# ---------------------------------------------------------------------------
# d20 vs DC (D&D 5e / Pathfinder)
# ---------------------------------------------------------------------------


def resolve_d20_vs_dc(args: CheckArgs, spec: Dict[str, Any]) -> CheckResult:
    rolls = parse_roll_list(args.roll)
    if not rolls:
        return CheckResult(
            tier="failure", tier_label=label(spec, "d20_vs_dc", "failure"),
            engine="d20_vs_dc",
            warnings=["CHECK marker missing roll value"],
        )
    roll = rolls[0]
    # `value` is the modifier added to the roll; `target` is the DC.
    modifier = int(coerce_float(args.value) or 0)
    dc = coerce_int(args.target) or coerce_int(
        (spec or {}).get("default_dc"), 10,
    )
    total = roll + modifier

    if roll == 20:
        tier, passed = "critical", True
        explanation = f"自然 20 → 暴击 (总值 {total} vs DC {dc})"
    elif roll == 1:
        tier, passed = "fumble", False
        explanation = f"自然 1 → 大失败 (总值 {total} vs DC {dc})"
    elif total >= dc:
        tier, passed = "success", True
        explanation = f"{roll}+{modifier} = {total} ≥ DC {dc} → 成功"
    else:
        tier, passed = "failure", False
        explanation = f"{roll}+{modifier} = {total} < DC {dc} → 失败"

    return CheckResult(
        tier=tier, tier_label=label(spec, "d20_vs_dc", tier),
        passed=passed, explanation=explanation,
        thresholds={"dc": dc}, engine="d20_vs_dc",
        roll_display=f"{roll}+{modifier}={total}",
    )


# ---------------------------------------------------------------------------
# PbtA 2d6 + stat
# ---------------------------------------------------------------------------


def resolve_pbta_2d6(args: CheckArgs, spec: Dict[str, Any]) -> CheckResult:
    rolls = parse_roll_list(args.roll)
    if len(rolls) < 2:
        return CheckResult(
            tier="miss", tier_label=label(spec, "pbta_2d6", "miss"),
            engine="pbta_2d6",
            warnings=["PbtA check needs 2 dice values"],
        )
    stat = int(coerce_float(args.value) or 0)
    total = sum(rolls[:2]) + stat
    hit_th = coerce_int((spec or {}).get("hit_threshold"), 10)
    partial_th = coerce_int((spec or {}).get("partial_threshold"), 7)

    if total >= hit_th:
        tier, passed = "hit", True
    elif total >= partial_th:
        tier, passed = "partial", True
    else:
        tier, passed = "miss", False

    explanation = (
        f"{rolls[0]}+{rolls[1]}+{stat} = {total} → "
        f"{label(spec, 'pbta_2d6', tier)} "
        f"(完全≥{hit_th}, 部分≥{partial_th})"
    )

    return CheckResult(
        tier=tier, tier_label=label(spec, "pbta_2d6", tier),
        passed=passed, explanation=explanation,
        thresholds={"hit": hit_th, "partial": partial_th},
        engine="pbta_2d6",
        roll_display=f"{rolls[0]},{rolls[1]}+{stat}={total}",
    )


# ---------------------------------------------------------------------------
# pool_count_n (count dice ≥ per-die target)
# ---------------------------------------------------------------------------


def resolve_pool_count_n(args: CheckArgs, spec: Dict[str, Any]) -> CheckResult:
    rolls = parse_roll_list(args.roll)
    if not rolls:
        return CheckResult(
            tier="failure", tier_label=label(spec, "pool_count_n", "failure"),
            engine="pool_count_n",
            warnings=["pool engine needs at least one die"],
        )
    per_die = coerce_int(
        args.target
        if args.target is not None
        else (spec or {}).get("per_die_target", 3),
        3,
    )
    required = int(coerce_float(args.value) or 1)
    successes = sum(1 for r in rolls if r >= per_die)
    # Crit tier only triggers when the spec explicitly configures it,
    # otherwise systems like Triangle Agency (where ≥1 three is already
    # regular success) would flip to crit on any second success.
    raw_crit = (spec or {}).get("crit_successes")
    crit_th = coerce_int(raw_crit, 0) if raw_crit is not None else 0

    if crit_th > 0 and successes >= crit_th:
        tier, passed = "crit", True
    elif successes >= required:
        tier, passed = "success", True
    else:
        tier, passed = "failure", False

    explanation = (
        f"骰值 [{', '.join(str(r) for r in rolls)}] | "
        f"{successes} 个 ≥ {per_die} (需要 ≥ {required}) → "
        f"{label(spec, 'pool_count_n', tier)}"
    )

    return CheckResult(
        tier=tier, tier_label=label(spec, "pool_count_n", tier),
        passed=passed, explanation=explanation,
        thresholds={"per_die": per_die, "required": required,
                    "successes": successes, "crit": crit_th},
        engine="pool_count_n",
        roll_display=", ".join(str(r) for r in rolls),
    )


# ---------------------------------------------------------------------------
# custom_llm fallback
# ---------------------------------------------------------------------------


def resolve_custom_llm(args: CheckArgs, spec: Dict[str, Any]) -> CheckResult:
    """Graceful fallback when no engine matches.

    Emits a result so the renderer doesn't crash, but flags it so the
    inline wrapper can leave the marker as a plain ``[dice]`` block and
    defer to the LLM's own narration.
    """
    rolls = parse_roll_list(args.roll)
    display = ", ".join(str(r) for r in rolls) if rolls else str(args.roll or "?")
    return CheckResult(
        tier="unresolved",
        tier_label=args.skill or "检定",
        explanation=f"骰值: {display} (规则未提供确定性判定引擎，保留原叙述)",
        warnings=["engine=custom_llm — resolution deferred to narration"],
        engine="custom_llm",
        roll_display=display,
    )


register_engine(
    "coc_7e_d100",
    resolve_coc_7e_d100,
    default_labels={
        "critical": "大成功",
        "extreme": "极难成功",
        "hard": "困难成功",
        "regular": "常规成功",
        "failure": "失败",
        "fumble": "大失败",
    },
)
register_engine(
    "brp_d100",
    resolve_brp_d100,
    default_labels={
        "special": "特殊成功",
        "regular": "成功",
        "failure": "失败",
        "fumble": "大失败",
    },
)
register_engine(
    "d20_vs_dc",
    resolve_d20_vs_dc,
    default_labels={
        "critical": "暴击",
        "success": "成功",
        "failure": "失败",
        "fumble": "大失败",
    },
)
register_engine(
    "pbta_2d6",
    resolve_pbta_2d6,
    default_labels={"hit": "完全成功", "partial": "部分成功", "miss": "失败"},
)
register_engine(
    "pool_count_n",
    resolve_pool_count_n,
    default_labels={"crit": "大成功", "success": "成功", "failure": "失败"},
)
register_engine(
    "custom_llm",
    resolve_custom_llm,
    default_labels={"success": "成功", "failure": "失败"},
)
