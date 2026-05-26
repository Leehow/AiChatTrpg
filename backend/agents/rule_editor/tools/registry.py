"""Aggregate every tool into a single registry + OpenAI tools[] schema.

P0.6 introduced design-state-first gating that hides every legacy
parsed_v6 writer (`P0_6_HIDDEN_NAMES`). M1 of the ReAct/CodeAct
redesign layered phase-aware gating on top: the registry narrows the
toolset per `draft.design_phase` instead of advertising a single flat
surface. M2 moves the phase -> tools table into `phase_skills.py`
(single source of truth for both toolsets and prompt fragments); this
module re-exports it as `PHASE_TOOLSETS` for back-compat with the M1
phase-gating smoke.

The legacy flat helpers (`TOOL_LIST`, `build_tools_schema`,
`get_tool`) stay as-is so the dice agent and smoke tests that import
them keep working. The main agent loop calls
`build_tools_schema_for_draft` / `get_allowed_tool_for_draft`, so the
LLM only ever sees the phase-narrowed surface, and hidden tools fail
closed at the gated lookup.

Hidden everywhere (parsed_v6 writers): bootstrap_framework,
design_core_rules, patch_core_rules, set_companion, design_scenario,
remove_scenario, design_parameter_family, add_parameter_entry,
remove_parameter_entry, design_character_sheet,
patch_character_sheet_field, compile_character_ui.
"""

from __future__ import annotations

from typing import Any

from ..phase_skills import PHASE_SKILLS, _resolve_phase
from .base import FunctionTool, Tool
from .blueprints import BLUEPRINT_TOOLS
from .compile_design import COMPILE_DESIGN_TOOLS
from .design_collection import COLLECTION_DESIGN_TOOLS
from .design_meta import META_DESIGN_TOOLS
from .design_sheet import SHEET_DESIGN_TOOLS
from .design_state import DESIGN_STATE_TOOLS
from .dice_bridge import DICE_BRIDGE_TOOLS
from .inspect import INSPECT_TOOLS
from .search_rulesets import SEARCH_RULESET_TOOLS
from .search_world import SEARCH_WORLD_TOOLS


# Flat all-tools list -- kept for back-compat with code that imports it
# directly. The agent loop no longer relies on this; it asks for the
# phase-aware list via `build_tools_schema_for_draft`.
TOOL_LIST: list[FunctionTool] = [
    *INSPECT_TOOLS,
    *SEARCH_RULESET_TOOLS,
    *SEARCH_WORLD_TOOLS,
    *META_DESIGN_TOOLS,
    *COLLECTION_DESIGN_TOOLS,
    *SHEET_DESIGN_TOOLS,
    *DESIGN_STATE_TOOLS,
    *BLUEPRINT_TOOLS,
    *COMPILE_DESIGN_TOOLS,
    *DICE_BRIDGE_TOOLS,
]


_TOOL_INDEX: dict[str, FunctionTool] = {t.name: t for t in TOOL_LIST}


# Phase -> advertised tool name tuple. Derived from PHASE_SKILLS so
# phase policy lives in exactly one place. The dict shape (rather than
# `MappingProxyType`) matches the M1 smoke's assumption that callers
# can iterate keys and values without unwrapping.
PHASE_TOOLSETS: dict[str, tuple[str, ...]] = {
    phase: skill.tools for phase, skill in PHASE_SKILLS.items()
}


# Back-compat: the union of every name that could ever be advertised
# under the phase-aware policy. Kept so external smoke tests / docs
# that assert "design-state-first surface is covered" still see a
# stable set. The agent loop does NOT use this -- it always asks
# `allowed_tool_names_for_draft(draft)` for the per-phase narrowed
# list.
P0_6_ADVERTISED_NAMES: tuple[str, ...] = tuple(
    dict.fromkeys(
        name
        for phase_tools in PHASE_TOOLSETS.values()
        for name in phase_tools
    )
)


# Tools that the LLM must NEVER see in P0.6. Listed explicitly so the
# guard fails closed: a new tool added without an explicit entry in
# either advertised or hidden is treated as hidden.
P0_6_HIDDEN_NAMES: tuple[str, ...] = (
    "bootstrap_framework",
    "design_core_rules",
    "patch_core_rules",
    "set_companion",
    "design_scenario",
    "remove_scenario",
    "design_parameter_family",
    "add_parameter_entry",
    "remove_parameter_entry",
    "design_character_sheet",
    "patch_character_sheet_field",
    "compile_character_ui",
)


def get_tool(name: str) -> Tool | None:
    """Look up any registered tool by name (does not enforce gating)."""
    return _TOOL_INDEX.get(name)


def build_tools_schema() -> list[dict[str, Any]]:
    """Return the FULL tools schema. Kept for back-compat; agent loop
    should prefer `build_tools_schema_for_draft`."""
    return [_tool_to_schema(t) for t in TOOL_LIST]


def _tool_to_schema(t: FunctionTool) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description,
            "parameters": t.json_schema,
        },
    }


def allowed_tool_names_for_draft(draft: Any) -> list[str]:
    """Return the list of tool names the LLM is allowed to see for the
    given draft. Phase-aware: reads `draft.design_phase` and looks up
    `PHASE_TOOLSETS` (derived from `PHASE_SKILLS`). The hidden-name
    guard (`get_allowed_tool_for_draft`) remains the final fail-closed
    barrier, but narrowing the schema is what keeps the LLM from even
    proposing irrelevant tools in the first place.
    """
    phase = _resolve_phase(draft)
    phase_tools = PHASE_TOOLSETS.get(phase, PHASE_TOOLSETS["intake"])
    names: list[str] = []
    for name in phase_tools:
        if name in _TOOL_INDEX:
            names.append(name)
    return names


def build_tools_schema_for_draft(draft: Any) -> list[dict[str, Any]]:
    """Return the OpenAI Chat Completions `tools` array filtered to the
    phase-aware advertised tool list. The agent loop calls this on
    every turn so adjusting `allowed_tool_names_for_draft` flows
    through automatically."""
    names = set(allowed_tool_names_for_draft(draft))
    return [_tool_to_schema(t) for t in TOOL_LIST if t.name in names]


def get_allowed_tool_for_draft(draft: Any, name: str) -> Tool | None:
    """Look up a tool only if it's in the advertised set for `draft`.

    The agent loop uses this to refuse legacy parsed_v6 writers even if
    a misbehaving model attempts to call them. Callers receive `None`
    for hidden / unknown names; the agent loop translates that into a
    structured `tool_not_advertised` tool result.
    """
    if name not in allowed_tool_names_for_draft(draft):
        return None
    return _TOOL_INDEX.get(name)


__all__ = [
    "TOOL_LIST",
    "PHASE_TOOLSETS",
    "P0_6_ADVERTISED_NAMES",
    "P0_6_HIDDEN_NAMES",
    "get_tool",
    "build_tools_schema",
    "build_tools_schema_for_draft",
    "allowed_tool_names_for_draft",
    "get_allowed_tool_for_draft",
]
