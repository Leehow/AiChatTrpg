"""Static fixture data for the dice CodeAct primitives.

Two responsibilities:

  - `propose_ir_skeleton(family, procedure_id, name)` — deep-copies a
    canonical IR template from `check_ir/examples.py` and stamps it
    with the caller's id/name. The CodeAct loop uses this as a cold-
    start so the LLM does not have to author boilerplate IR from
    scratch for every familiar family.
  - `generate_sample_cases(family, params)` — emits a deterministic
    sample suite (args + expected primary_tier/passed) per canonical
    engine. Used to drive `run_sample` / `validate_proposal` without
    asking the LLM to invent samples for every retry.

Adding a new family means: add the IR fixture to
`check_ir/examples.py`, register it in `_SKELETONS` here, and (if you
want sample-based validation) add a `_*_samples` builder + entry in
`_SAMPLE_BUILDERS`.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Mapping, Optional

from agents.trpg.check_ir.examples import (
    COC_SKILL_CHECK_IR,
    D20_VS_DC_IR,
    FITD_ACTION_ROLL_IR,
    PBTA_BASIC_MOVE_IR,
    TWOD20_TASK_IR,
)


class CodeActFixtureError(Exception):
    """Raised when a fixture request is invalid (unknown family etc.)."""


_SKELETONS: Dict[str, Dict[str, Any]] = {
    "coc_7e_d100": COC_SKILL_CHECK_IR,
    "d20_vs_dc": D20_VS_DC_IR,
    "pbta_2d6": PBTA_BASIC_MOVE_IR,
    "fitd_pool": FITD_ACTION_ROLL_IR,
    "2d20_task": TWOD20_TASK_IR,
}


def propose_ir_skeleton(
    family: str,
    *,
    procedure_id: str = "",
    name: str = "",
) -> Dict[str, Any]:
    template = _SKELETONS.get(family)
    if template is None:
        raise CodeActFixtureError(
            f"no skeleton for family {family!r}; known: "
            f"{sorted(_SKELETONS.keys())}",
        )
    ir = copy.deepcopy(template)
    if procedure_id:
        ir["id"] = procedure_id
    if name:
        ir["name"] = name
    return ir


# ---------------------------------------------------------------------------
# Sample suites
# ---------------------------------------------------------------------------


def _coc_samples(skill: int = 50) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = [
        {"name": "critical", "args": {"roll": [1], "skill": skill},
         "expected": {"primary_tier": "critical", "passed": True}},
        {"name": "extreme", "args": {"roll": [max(1, skill // 5)], "skill": skill},
         "expected": {"primary_tier": "extreme", "passed": True}},
        {"name": "hard", "args": {"roll": [max(2, skill // 2)], "skill": skill},
         "expected": {"primary_tier": "hard", "passed": True}},
        {"name": "regular", "args": {"roll": [skill], "skill": skill},
         "expected": {"primary_tier": "regular", "passed": True}},
    ]
    # Failure tier needs roll > skill while staying out of the fumble band
    # (roll == 100 always; roll >= 96 when skill < 50). For skill >= 99 the
    # only remaining roll (100) is fumble, so no failure sample is emitted.
    if skill < 99:
        cases.append(
            {"name": "failure", "args": {"roll": [skill + 1], "skill": skill},
             "expected": {"primary_tier": "failure", "passed": False}},
        )
    cases.append(
        {"name": "fumble", "args": {"roll": [100], "skill": skill},
         "expected": {"primary_tier": "fumble", "passed": False}},
    )
    return cases


def _d20_samples(target: int = 15) -> List[Dict[str, Any]]:
    return [
        {"name": "nat20", "args": {"roll": [20], "target": target, "value": 0},
         "expected": {"primary_tier": "critical", "passed": True}},
        {"name": "nat1", "args": {"roll": [1], "target": target, "value": 0},
         "expected": {"primary_tier": "fumble", "passed": False}},
        {"name": "meets_dc", "args": {"roll": [target], "target": target, "value": 0},
         "expected": {"primary_tier": "success", "passed": True}},
        {"name": "below_dc", "args": {"roll": [2], "target": target, "value": 0},
         "expected": {"primary_tier": "failure", "passed": False}},
    ]


def _pbta_samples() -> List[Dict[str, Any]]:
    return [
        {"name": "miss", "args": {"roll": [1, 1], "value": 0},
         "expected": {"primary_tier": "miss", "passed": False}},
        {"name": "partial", "args": {"roll": [3, 4], "value": 0},
         "expected": {"primary_tier": "partial", "passed": True}},
        {"name": "hit", "args": {"roll": [5, 5], "value": 0},
         "expected": {"primary_tier": "hit", "passed": True}},
    ]


def _pool_samples() -> List[Dict[str, Any]]:
    return [
        {"name": "double_six", "args": {"roll": [6, 6, 2], "value": 3},
         "expected": {"primary_tier": "critical", "passed": True}},
        {"name": "single_six", "args": {"roll": [6, 3, 2], "value": 3},
         "expected": {"primary_tier": "success", "passed": True}},
        {"name": "partial", "args": {"roll": [4, 3, 2], "value": 3},
         "expected": {"primary_tier": "partial", "passed": True}},
        {"name": "failure", "args": {"roll": [1, 2, 3], "value": 3},
         "expected": {"primary_tier": "failure", "passed": False}},
    ]


_SAMPLE_BUILDERS = {
    "coc_7e_d100": lambda p: _coc_samples(int((p or {}).get("skill", 50))),
    "d20_vs_dc": lambda p: _d20_samples(int((p or {}).get("target", 15))),
    "pbta_2d6": lambda _p: _pbta_samples(),
    "fitd_pool": lambda _p: _pool_samples(),
}


def generate_sample_cases(
    family: str, params: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    builder = _SAMPLE_BUILDERS.get(family)
    if builder is None:
        raise CodeActFixtureError(
            f"no sample suite for family {family!r}; known: "
            f"{sorted(_SAMPLE_BUILDERS.keys())}",
        )
    return builder(params)


KNOWN_SKELETON_FAMILIES = tuple(sorted(_SKELETONS.keys()))
KNOWN_SAMPLE_FAMILIES = tuple(sorted(_SAMPLE_BUILDERS.keys()))
