"""Rule editor agent tools.

Each tool is a small async-callable that receives a ToolContext (db, user
id, draft id) and structured args, and returns a JSON-serializable result
that the agent loop sends back to the LLM as a `role: "tool"` message.

The tool registry yields the OpenAI Chat-Completions tools[] schema for
the agent's per-turn LLM call.
"""

from __future__ import annotations

from .base import Tool, ToolContext, ToolError, ToolResult
from .registry import (
    TOOL_LIST,
    P0_6_ADVERTISED_NAMES,
    P0_6_HIDDEN_NAMES,
    allowed_tool_names_for_draft,
    build_tools_schema,
    build_tools_schema_for_draft,
    get_allowed_tool_for_draft,
    get_tool,
)

__all__ = [
    "TOOL_LIST",
    "P0_6_ADVERTISED_NAMES",
    "P0_6_HIDDEN_NAMES",
    "Tool",
    "ToolContext",
    "ToolError",
    "ToolResult",
    "allowed_tool_names_for_draft",
    "build_tools_schema",
    "build_tools_schema_for_draft",
    "get_allowed_tool_for_draft",
    "get_tool",
]
