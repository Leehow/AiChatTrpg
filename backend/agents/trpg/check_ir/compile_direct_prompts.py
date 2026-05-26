"""Prompt strings for the direct LLM → IR compiler.

Kept in a separate module so ``compile_direct.py`` stays focused on
orchestration, validation, and retry logic. The few-shot examples are
real working IRs from ``examples.py`` — when one of them needs an update
fix the source there.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .examples import (
    COC_SKILL_CHECK_IR,
    D20_VS_DC_IR,
    FITD_ACTION_ROLL_IR,
    PBTA_BASIC_MOVE_IR,
    TWOD20_TASK_IR,
)

MAX_PROCEDURES_PER_RULEBOOK = 20


PROCEDURE_ENUM_SYSTEM = """You are a TRPG rules analyst.

Given a rulebook excerpt, identify every distinct DICE-RESOLVED procedure that players will perform during play. Output a single JSON object — no prose, no markdown fence.

Include:
- Skill checks / saving throws / attribute tests
- Attack resolution (one entry per family if mechanics differ — e.g. melee vs firearms)
- Sanity / fear / horror / stress checks
- Damage rolls only when formula-driven (e.g. 3d6 + STR mod), not narrative
- Stat-improvement / advancement rolls
- Reputation / morale / panic / pursuit rolls

Skip:
- Pure narrative outcomes (no dice)
- Character-creation point-buy and direct assignment (no roll)
- World-building lore tables that aren't rolled at the table

For each procedure, choose ONE primary_family from this list (these match the IR runtime's mechanics):
- sum_vs_target — total a roll (with mods) and compare to a target value (d20+mod vs DC, d100 roll-under skill, 1d10+stat+skill vs DV)
- sum_bands — sum dice and look up tier by threshold bands (PbtA 2d6: <7 / 7-9 / 10+)
- highest_die_pool — roll N dice, take the highest, compare bands (FitD: 1-3 fail, 4-5 partial, 6 success, double 6 critical)
- match_count_pool — roll N dice and count specific faces (Triangle Agency: 6d4, count 3s)
- weighted_success_pool — count successes (and crits, complications) across a pool (2d20 systems)
- beat_count_challenges — roll one score, count how many challenge dice it beats
- static_outcome — no dice; deterministic application of an effect

Output exactly:
{
  "system_name": "<from the rulebook header, or empty>",
  "procedures": [
    {
      "id": "snake_case_id",
      "name": "Human readable name",
      "summary": "1-2 sentences describing the mechanic",
      "primary_family": "...",
      "key_inputs": ["roll", "skill", "target", ...],
      "tier_outcomes": ["success", "failure", ...]
    }
  ]
}

Cap procedures at """ + str(MAX_PROCEDURES_PER_RULEBOOK) + """; pick the most central / frequently-used ones first.
"""


def _ir_examples_block() -> str:
    """Render five diverse working IRs as the few-shot block."""
    examples = [
        ("d100 roll-under (Call of Cthulhu 7e skill check)", COC_SKILL_CHECK_IR),
        ("d20 + modifier vs DC (D&D / Pathfinder family)", D20_VS_DC_IR),
        ("2d6 sum bands (Powered by the Apocalypse)", PBTA_BASIC_MOVE_IR),
        ("dice pool, take highest (Forged in the Dark)", FITD_ACTION_ROLL_IR),
        ("multi-axis success counting (2d20 / Modiphius)", TWOD20_TASK_IR),
    ]
    out: List[str] = []
    for label, ir in examples:
        out.append(f"EXAMPLE — {label}:")
        out.append(json.dumps(ir, ensure_ascii=False, indent=2))
        out.append("")
    return "\n".join(out).rstrip()


IR_COMPILE_SYSTEM = """You are a TRPG dice IR compiler.

Compile ONE procedure into a directly-executable resolution_ir_v1_1 spec PLUS a small suite of sample test cases. Output a single JSON object — no prose, no markdown fence.

The IR runtime supports these step ops (use only these):

- read_rolls   — load player-provided dice into a group. expr is "1d100" / "Nd6" etc; for variable counts use "Nd<sides>" + count_from
- tally        — count kept dice matching a condition
- sum_values   — sum kept dice values
- max_value    — highest kept die
- formula      — arithmetic. operators: + - * / // % ; functions: floor, ceil, min, max, abs ; references: args.X, vars.X, plain var name
- conditional_value — switch-case write
- weighted_success_count — pool counting with crit weight + complication tracking
- change_die_to_value, remove_matches, select_keep — dice manipulation
- beat_count, degree_count — beat-based counting

Conditions support: eq, neq, gt, gte, lt, lte, in, all, any, not.
Reference forms inside conditions:
- {"var": "args.skill", "lte": 50}
- {"var": "vars.total", "gte": "args.target"}
- {"var": "roll.main.0", "eq": 20}  ← group main, die index 0

Result axes (pick one as primary_axis):
- pass_fail — single boolean with success_tier / failure_tier
- tier      — outcomes[] evaluated FIRST-MATCH; put more-specific outcomes (criticals, fumbles) before generic ones; last entry should have "default": True
- flags     — multiple flags, each with an independent when condition
- resource_delta / complication / narrative_positive / value — numeric side effects

CRITICAL RULES:
1. Tier outcomes are matched in array order. ALWAYS put fumble/critical (special bands) before regular success/failure.
2. Never reference a variable in conditions or formulas without first defining it in steps. If you need args.skill / 5, write it into a var first via formula.
3. Optional args MUST be in input_contract.optional with a default.
4. Each sample's "expected" must specify primary_tier (a string from your tier outcomes) and passed (bool). You may optionally specify side_effects keyed by axis id.
5. Runtime sample args should pass primary dice as "roll": 42 or "roll": [4, 2], not nested objects like {"main": [42]}.
6. Prefer CHECK-compatible argument names for portable runtime use: "roll" for primary dice, "value" for the target/skill/current rating, and descriptive optional resource inputs such as "success_san_loss" / "failure_san_loss" or "success_stress_loss" / "failure_stress_loss".
7. Provide AT LEAST 4 samples covering distinct outcome tiers including the failure case.

Reference examples from real systems:

""" + _ir_examples_block() + """

OUTPUT SHAPE — exactly this JSON object, no fence, no prose:
{
  "ir": <full resolution_ir_v1_1 spec — see schema_version field>,
  "samples": [
    {"name": "...", "args": {"roll": ..., "skill": ...}, "expected": {"primary_tier": "...", "passed": true/false}},
    ...
  ]
}
"""


def build_enum_user_prompt(
    markdown: str,
    *,
    system_name: str,
    output_language: str,
    house_rules: str,
) -> str:
    parts = [f"OUTPUT_LANGUAGE: {output_language or 'en'}"]
    if system_name:
        parts.append(f"SYSTEM_NAME: {system_name}")
    if house_rules.strip():
        parts.append("HOUSE_RULES:\n" + house_rules.strip())
    parts.append("RULEBOOK_MARKDOWN:")
    parts.append(markdown)
    return "\n\n".join(parts)


def build_compile_user_prompt(
    *,
    markdown: str,
    procedure: Dict[str, Any],
    house_rules: str,
    output_language: str,
    error_history: List[Dict[str, Any]],
) -> str:
    parts = [f"OUTPUT_LANGUAGE: {output_language or 'en'}"]
    parts.append("PROCEDURE_TO_COMPILE:\n" + json.dumps(procedure, ensure_ascii=False, indent=2))
    if house_rules.strip():
        parts.append("HOUSE_RULES (apply on top of rulebook):\n" + house_rules.strip())
    if error_history:
        history_lines = ["PRIOR_ATTEMPTS_AND_ERRORS — FIX THESE:"]
        for i, entry in enumerate(error_history, 1):
            history_lines.append(f"\nAttempt {i}:")
            ir_text = json.dumps(entry["ir"], ensure_ascii=False, indent=2)
            # Cap each prior IR so a runaway retry doesn't blow up the prompt.
            history_lines.append("Your IR was:\n" + ir_text[:4000])
            history_lines.append("Errors:\n" + "\n".join(f"  - {e}" for e in entry["errors"]))
        parts.append("\n".join(history_lines))
    parts.append("RULEBOOK_MARKDOWN_CONTEXT:")
    parts.append(markdown)
    return "\n\n".join(parts)
