"""Tools to search modules + sessions and a web_search stub."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from orm.models import GameSession, Message, ParsedModule

from .base import (
    FunctionTool,
    ToolContext,
    ToolError,
    ToolResult,
    make_object_schema,
)


async def _search_my_modules(
    ctx: ToolContext, args: dict[str, Any],
) -> ToolResult:
    query = str(args.get("query") or "").strip().lower()
    limit = max(1, min(int(args.get("limit") or 30), 50))
    res = await ctx.db.execute(
        select(ParsedModule)
        .where(
            (ParsedModule.owner_id == ctx.owner_id) | (ParsedModule.is_shared == True)  # noqa: E712
        )
        .order_by(ParsedModule.updated_at.desc())
    )
    items: list[dict[str, Any]] = []
    for m in res.scalars().all():
        haystack = f"{m.extracted_title or m.filename} {m.briefing_md[:200]}".lower()
        if query and query not in haystack:
            continue
        items.append({
            "id": m.id,
            "title": m.extracted_title or m.filename,
            "is_shared": bool(m.is_shared),
            "page_count": m.page_count,
            "briefing_preview": m.briefing_md[:300],
            "updated_at": m.updated_at.isoformat(),
        })
        if len(items) >= limit:
            break
    return ToolResult({"items": items, "total": len(items)})


search_modules_tool = FunctionTool(
    name="search_my_modules",
    description=(
        "List adventure/scenario modules visible to the user. Use to "
        "ground rule decisions in modules the user actually plays."
    ),
    json_schema=make_object_schema({
        "query": {"type": "string"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    }),
    is_write=False,
    executor=_search_my_modules,
)


async def _read_module(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    mod_id = str(args.get("module_id") or "").strip()
    if not mod_id:
        raise ToolError("missing_module_id", "module_id required")
    m = await ctx.db.get(ParsedModule, mod_id)
    if m is None or (m.owner_id != ctx.owner_id and not m.is_shared):
        raise ToolError("not_found", "module not visible")
    return ToolResult({
        "id": m.id,
        "title": m.extracted_title or m.filename,
        "briefing_md": m.briefing_md,
        "markdown_chars": len(m.markdown or ""),
        "markdown_preview": (m.markdown or "")[:6000],
    })


read_module_tool = FunctionTool(
    name="read_module",
    description="Fetch a module's briefing + first ~6000 chars of its markdown.",
    json_schema=make_object_schema(
        {"module_id": {"type": "string"}}, ["module_id"],
    ),
    is_write=False,
    executor=_read_module,
)


async def _list_my_sessions(
    ctx: ToolContext, args: dict[str, Any],
) -> ToolResult:
    limit = max(1, min(int(args.get("limit") or 20), 50))
    res = await ctx.db.execute(
        select(GameSession)
        .where(GameSession.user_id == ctx.owner_id)
        .order_by(GameSession.last_active_at.desc())
        .limit(limit)
    )
    items = [{
        "id": s.id,
        "title": s.title,
        "ruleset_id": s.ruleset_id,
        "last_active_at": s.last_active_at.isoformat(),
    } for s in res.scalars().all()]
    return ToolResult({"items": items})


list_sessions_tool = FunctionTool(
    name="list_my_sessions",
    description=(
        "List the user's game sessions, most recently active first. "
        "Useful for picking up the user's preferred narrative style."
    ),
    json_schema=make_object_schema({
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    }),
    is_write=False,
    executor=_list_my_sessions,
)


async def _read_session(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    sess_id = str(args.get("session_id") or "").strip()
    if not sess_id:
        raise ToolError("missing_session_id", "session_id required")
    s = await ctx.db.get(GameSession, sess_id)
    if s is None or s.user_id != ctx.owner_id:
        raise ToolError("not_found", "session not owned by user")
    msg_limit = max(1, min(int(args.get("message_limit") or 10), 30))
    msgs_res = await ctx.db.execute(
        select(Message)
        .where(Message.session_id == sess_id)
        .order_by(Message.created_at.desc())
        .limit(msg_limit)
    )
    msgs = list(reversed(msgs_res.scalars().all()))
    return ToolResult({
        "id": s.id,
        "title": s.title,
        "ruleset_id": s.ruleset_id,
        "recent_messages": [
            {
                "role": m.role,
                "content": (m.content or "")[:1500],
                "created_at": m.created_at.isoformat(),
            }
            for m in msgs
        ],
    })


read_session_tool = FunctionTool(
    name="read_session",
    description=(
        "Fetch a session's recent messages (default 10). Useful to see "
        "the user's narrative voice when designing flavor for rules."
    ),
    json_schema=make_object_schema({
        "session_id": {"type": "string"},
        "message_limit": {"type": "integer", "minimum": 1, "maximum": 30},
    }, ["session_id"]),
    is_write=False,
    executor=_read_session,
)


async def _web_search(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return ToolResult({
        "available": False,
        "reason": "provider_unsupported",
        "hint": (
            "Web search is not wired in V1. Ask the user to paste "
            "reference material instead."
        ),
    })


web_search_tool = FunctionTool(
    name="web_search",
    description=(
        "Web search for a query. May be unavailable on the active "
        "provider — check the `available` field in the result and fall "
        "back to asking the user for source material if false."
    ),
    json_schema=make_object_schema({
        "query": {"type": "string"},
        "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
    }, ["query"]),
    is_write=False,
    executor=_web_search,
)


SEARCH_WORLD_TOOLS: list[FunctionTool] = [
    search_modules_tool,
    read_module_tool,
    list_sessions_tool,
    read_session_tool,
    web_search_tool,
]
