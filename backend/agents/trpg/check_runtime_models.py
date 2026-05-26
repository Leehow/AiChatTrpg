"""Dataclasses shared by the unified CHECK runtime facade.

These types are re-exported by ``agents.trpg.check_runtime`` so external
callers keep the existing import surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .check_resolver import CheckArgs, CheckResult


@dataclass
class RuntimeCheckContext:
    """Selected runtime spec plus routing metadata for one CHECK."""

    spec: dict[str, Any]
    requested_procedure_id: str = ""
    procedure_id: str = ""
    engine: str = "custom_llm"


@dataclass
class RollTrace:
    """Structured execution trace for dice history and diagnostics."""

    source: str = "check_runtime"
    procedure_id: str = ""
    requested_procedure_id: str = ""
    engine: str = "custom_llm"
    skill: str = ""
    value: Any = None
    difficulty: str = "regular"
    target: Any = None
    pool: str = ""
    reason: str = ""
    roll_expression: str = ""
    roll_expressions: dict[str, str] = field(default_factory=dict)
    roll_sources: dict[str, Any] = field(default_factory=dict)
    roll_trace: dict[str, Any] = field(default_factory=dict)
    roll_seed: str = ""
    roll: Any = None
    roll_total: int | None = None
    roll_display: str = ""
    auto_rolled: bool = False
    tier: str = ""
    tier_label: str = ""
    passed: bool = False
    explanation: str = ""
    thresholds: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    side_effects: dict[str, Any] = field(default_factory=dict)
    result_axes: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        """Return a JSON-friendly trace dict."""

        return {
            "source": self.source,
            "procedure_id": self.procedure_id,
            "requested_procedure_id": self.requested_procedure_id,
            "engine": self.engine,
            "skill": self.skill,
            "value": self.value,
            "difficulty": self.difficulty,
            "target": self.target,
            "pool": self.pool,
            "reason": self.reason,
            "roll_expression": self.roll_expression,
            "roll_expressions": self.roll_expressions,
            "roll_sources": self.roll_sources,
            "roll_trace": self.roll_trace,
            "roll_seed": self.roll_seed,
            "roll": self.roll,
            "roll_total": self.roll_total,
            "roll_display": self.roll_display,
            "auto_rolled": self.auto_rolled,
            "tier": self.tier,
            "tier_label": self.tier_label,
            "passed": self.passed,
            "explanation": self.explanation,
            "thresholds": self.thresholds,
            "warnings": self.warnings,
            "side_effects": self.side_effects,
            "result_axes": self.result_axes,
        }


@dataclass
class CheckExecution:
    """Complete output from resolving one CHECK."""

    args: CheckArgs
    spec: dict[str, Any]
    result: CheckResult
    rendered: str
    trace: RollTrace


@dataclass
class RollSample:
    """Boundary roll plus the expression that produced it."""

    value: Any
    expression: str = ""
    source_arg: str = "roll"
    roll_sources: dict[str, Any] = field(default_factory=dict)
    roll_expressions: dict[str, str] = field(default_factory=dict)
    roll_traces: dict[str, Any] = field(default_factory=dict)
    seed: str = ""
    extra_args: dict[str, Any] = field(default_factory=dict)
