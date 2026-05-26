"""Dice agent tools — re-exports the 3 tools defined in the
sub-modules. Sub-modules:
    tools_inspect.py     — read_dice_state (read-only)
    tools_design.py      — design_dice_procedure (compile + apply;
                           branches on `CHATRPG_DICE_CODEACT` between
                           the legacy direct compiler and the bounded
                           CodeAct loop)
    tools_test.py        — test_dice_procedure (synthetic execute)
    tools_apply.py       — apply_dice_proposal (the single dice_ir
                           writer; called by tools_design and any
                           future CodeAct / main-ReAct bridge —
                           never advertised to the LLM in M1/M2)
    codeact_agent.py     — bounded CodeAct compiler loop (M2; off by
                           default; falls back to compile_to_ir_direct)
    codeact_primitives.py — deterministic primitives the CodeAct LLM
                           may call (run_sample, simulate, mutate,
                           validate, propose_ir_skeleton, etc.)
    codeact_fixtures.py  — static IR skeletons + canned sample suites
    codeact_prompts.py   — system prompt + tool schemas for the
                           CodeAct loop

We deliberately do NOT include a `respond` tool. The dice agent uses
plain assistant text for conversation; tools are reserved for actions
that read or write the dice IR. Earlier versions exposed `respond` as
a no-op stub but the model gravitated toward it for every reply,
which made every chat answer render as a tool-call card instead of a
chat bubble. Without the tool, normal replies fall through to plain
assistant text — exactly what the user expects.
"""

from __future__ import annotations

from .tools_design import design_dice_procedure_tool
from .tools_inspect import read_dice_state_tool
from .tools_test import test_dice_procedure_tool


DICE_TOOLS = [
    read_dice_state_tool,
    design_dice_procedure_tool,
    test_dice_procedure_tool,
]
