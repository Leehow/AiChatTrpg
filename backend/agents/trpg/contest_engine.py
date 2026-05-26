"""Deterministic opposed/contest resolution for TRPG runtime checks.

This module sits one layer above ``check_resolver``:

- ``check_resolver`` answers: "how did one side's roll resolve?"
- ``contest_engine`` answers: "given two resolved checks, who wins the contest?"

The goal is to stop opposed outcomes (Dodge / Fight Back / save contests /
resisted moves) from falling back to free-form LLM narration. Rulesets differ
mainly in three places:

1. How each side's single check resolves
2. How success tiers compare in an opposed context
3. What mechanical branch fires on attacker win / defender win / stalemate

This engine keeps (1) delegated to existing ``resolve_check`` and makes
``(2)+(3)`` explicit and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Sequence, Set

from .check_resolver import CheckArgs, CheckResult, resolve_check

ContestOutcome = Literal["attacker_wins", "defender_wins", "stalemate"]

_DEFAULT_TIER_RANKS: Dict[str, int] = {
    "critical": 60,
    "triscendence": 55,
    "extreme": 50,
    "hard": 40,
    "special": 35,
    "regular": 30,
    "success": 30,
    "hit": 30,
    "partial": 20,
    "failure": 10,
    "miss": 10,
    "fumble": 0,
    "manual_resolution_required": -10,
    "unresolved": -20,
}

_DEFAULT_FAILURE_TIERS: Set[str] = {
    "failure",
    "miss",
    "fumble",
    "manual_resolution_required",
    "unresolved",
}


@dataclass
class ContestSide:
    """One participant in an opposed resolution."""

    role: Literal["attacker", "defender"]
    label: str
    args: CheckArgs
    spec: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ContestPolicy:
    """Ruleset-specific comparison policy."""

    id: str
    tie_outcome: ContestOutcome = "stalemate"
    both_fail_outcome: ContestOutcome = "stalemate"
    tier_ranks: Dict[str, int] = field(default_factory=dict)
    failure_tiers: Set[str] = field(default_factory=lambda: set(_DEFAULT_FAILURE_TIERS))
    outcome_effects: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    def rank_for(self, result: CheckResult) -> int:
        tier = str(result.tier or "").strip().lower()
        if tier in self.tier_ranks:
            return int(self.tier_ranks[tier])
        if tier in _DEFAULT_TIER_RANKS:
            return _DEFAULT_TIER_RANKS[tier]
        return 1 if result.passed else 0

    def counts_as_pass(self, result: CheckResult) -> bool:
        tier = str(result.tier or "").strip().lower()
        if tier in self.failure_tiers:
            return False
        if result.passed:
            return True
        return self.rank_for(result) > 0


@dataclass
class ContestResolution:
    """Fully-resolved contest result."""

    attacker: ContestSide
    defender: ContestSide
    attacker_result: CheckResult
    defender_result: CheckResult
    outcome: ContestOutcome
    comparator_reason: str
    explanation: str
    planned_effects: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _resolve_side(side: ContestSide) -> CheckResult:
    return resolve_check(side.args, side.spec or {})


def resolve_contest(
    attacker: ContestSide,
    defender: ContestSide,
    policy: ContestPolicy,
) -> ContestResolution:
    """Resolve a two-side contest deterministically."""

    attacker_result = _resolve_side(attacker)
    defender_result = _resolve_side(defender)

    attacker_passed = policy.counts_as_pass(attacker_result)
    defender_passed = policy.counts_as_pass(defender_result)

    warnings: List[str] = []
    if not attacker_passed and attacker_result.passed and attacker_result.tier in policy.failure_tiers:
        warnings.append("attacker result marked passed but tier is configured as failure")
    if not defender_passed and defender_result.passed and defender_result.tier in policy.failure_tiers:
        warnings.append("defender result marked passed but tier is configured as failure")

    if attacker_passed and not defender_passed:
        outcome: ContestOutcome = "attacker_wins"
        reason = "only_attacker_passed"
        explanation = (
            f"{attacker.label}单边成功，{defender.label}未通过对抗检定。"
        )
    elif defender_passed and not attacker_passed:
        outcome = "defender_wins"
        reason = "only_defender_passed"
        explanation = (
            f"{defender.label}单边成功，{attacker.label}未通过对抗检定。"
        )
    elif not attacker_passed and not defender_passed:
        outcome = policy.both_fail_outcome
        reason = "both_failed"
        explanation = (
            f"{attacker.label}与{defender.label}都未通过检定，按策略判定为{outcome}。"
        )
    else:
        attacker_rank = policy.rank_for(attacker_result)
        defender_rank = policy.rank_for(defender_result)
        if attacker_rank > defender_rank:
            outcome = "attacker_wins"
            reason = "higher_success_tier"
            explanation = (
                f"{attacker.label}成功等级更高（{attacker_result.tier} > {defender_result.tier}）。"
            )
        elif defender_rank > attacker_rank:
            outcome = "defender_wins"
            reason = "higher_success_tier"
            explanation = (
                f"{defender.label}成功等级更高（{defender_result.tier} > {attacker_result.tier}）。"
            )
        else:
            outcome = policy.tie_outcome
            reason = "equal_success_tier"
            explanation = (
                f"双方成功等级相同（{attacker_result.tier}），按策略判定为{outcome}。"
            )

    planned_effects = [dict(item) for item in policy.outcome_effects.get(outcome, [])]
    return ContestResolution(
        attacker=attacker,
        defender=defender,
        attacker_result=attacker_result,
        defender_result=defender_result,
        outcome=outcome,
        comparator_reason=reason,
        explanation=explanation,
        planned_effects=planned_effects,
        warnings=warnings + list(attacker_result.warnings or []) + list(defender_result.warnings or []),
    )


def coc_melee_contest_policy(reaction: str) -> ContestPolicy:
    """CoC 7e melee contest policy for Dodge / Fight Back."""

    key = str(reaction or "").strip().lower().replace("_", " ")
    if key == "dodge":
        return ContestPolicy(
            id="coc_7e.melee_vs_dodge",
            tie_outcome="defender_wins",
            both_fail_outcome="stalemate",
            outcome_effects={
                "attacker_wins": [
                    {
                        "op": "apply_attack_damage",
                        "source": "attacker",
                        "target": "defender",
                    },
                ],
            },
        )
    if key in {"fight back", "fightback", "counter"}:
        return ContestPolicy(
            id="coc_7e.melee_vs_fight_back",
            tie_outcome="attacker_wins",
            both_fail_outcome="stalemate",
            outcome_effects={
                "attacker_wins": [
                    {
                        "op": "apply_attack_damage",
                        "source": "attacker",
                        "target": "defender",
                    },
                ],
                "defender_wins": [
                    {
                        "op": "apply_attack_damage",
                        "source": "defender",
                        "target": "attacker",
                    },
                ],
            },
        )
    raise ValueError(f"Unsupported CoC melee reaction: {reaction!r}")


def summarize_contest_lines(resolution: ContestResolution) -> List[str]:
    """Return compact player-facing summary lines for logging or future UI."""

    attacker = resolution.attacker
    defender = resolution.defender
    a = resolution.attacker_result
    d = resolution.defender_result
    return [
        f"{attacker.label}: {a.roll_display or attacker.args.roll} / {attacker.args.value} -> {a.tier}",
        f"{defender.label}: {d.roll_display or defender.args.roll} / {defender.args.value} -> {d.tier}",
        f"outcome: {resolution.outcome} ({resolution.comparator_reason})",
    ]


def build_contest_effect_payload(
    resolution: ContestResolution,
    extra_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a transport-friendly payload for later state-application layers."""

    return {
        "outcome": resolution.outcome,
        "comparator_reason": resolution.comparator_reason,
        "explanation": resolution.explanation,
        "attacker": {
            "label": resolution.attacker.label,
            "result_tier": resolution.attacker_result.tier,
            "passed": resolution.attacker_result.passed,
        },
        "defender": {
            "label": resolution.defender.label,
            "result_tier": resolution.defender_result.tier,
            "passed": resolution.defender_result.passed,
        },
        "planned_effects": [dict(item) for item in resolution.planned_effects],
        "context": dict(extra_context or {}),
    }
