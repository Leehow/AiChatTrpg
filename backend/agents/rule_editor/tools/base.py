"""Tool protocol + shared types for the rule editor agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class ToolContext:
    """Threaded into every tool execution."""
    db: AsyncSession
    owner_id: str
    draft_id: str
    # Set by the agent loop for write tools: the assistant message id that
    # produced this tool call. Stored on RulesetDraftEdit for audit.
    assistant_message_id: str | None = None


class ToolError(Exception):
    """Raised by a tool to signal a structured failure to the LLM."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {"error": True, "code": self.code, "message": self.message}


@dataclass
class ToolResult:
    """What a tool's execute returns. The agent will JSON-stringify this
    and send it back as role=tool content.

    `edit_id` is set by write tools whose effect goes through the patch
    layer; the agent loop forwards it in the `tool_result` SSE event so the
    frontend can correlate the edit history.
    """
    payload: dict[str, Any]
    edit_id: str | None = None


class Tool(Protocol):
    name: str
    description: str
    json_schema: dict[str, Any]
    is_write: bool

    async def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        ...


# Convenience type for ad-hoc tools defined as plain functions.
ToolExecutor = Callable[[ToolContext, dict[str, Any]], Awaitable[ToolResult]]


@dataclass
class FunctionTool:
    """Adapter: wrap a plain async function as a Tool."""
    name: str
    description: str
    json_schema: dict[str, Any]
    is_write: bool
    executor: ToolExecutor

    async def execute(
        self, ctx: ToolContext, args: dict[str, Any],
    ) -> ToolResult:
        return await self.executor(ctx, args)


def make_object_schema(
    properties: dict[str, dict[str, Any]],
    required: list[str] | None = None,
) -> dict[str, Any]:
    """Helper to build the JSONSchema `parameters` block for a tool."""
    return {
        "type": "object",
        "properties": properties,
        "required": list(required or []),
        "additionalProperties": False,
    }
