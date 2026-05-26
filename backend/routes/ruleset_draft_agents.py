"""Agent message SSE endpoints for the rule editor + dice agent.

Split out of `routes/ruleset_drafts.py` so the CRUD/promote/recompile
file stays under the 400-line cap. Both endpoints share the same router
instance via `add_agent_routes(router)` registration.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from agents.rule_editor.agent import AgentConfig, run_agent_turn
from agents.rule_editor_dice.agent import DiceAgentConfig, run_dice_agent_turn
from core.database import get_session_factory
from orm.models import User
from routes.deps import current_user
from routes.rulesets import _resolve_default_compiler_config
from services import model_pool, ruleset_drafts as svc


logger = logging.getLogger("chatrpg.ruleset_draft_agents")


def add_agent_routes(router: APIRouter) -> None:
    """Attach the two agent SSE endpoints to the given router."""
    router.add_api_route(
        "/{draft_id}/messages",
        post_message,
        methods=["POST"],
    )
    router.add_api_route(
        "/{draft_id}/dice-agent/messages",
        post_dice_message,
        methods=["POST"],
    )


async def _resolve_llm_config(factory) -> tuple[str, dict[str, Any]]:
    """Resolve provider + LLM config, raising HTTPException on failure."""
    async with factory() as auth_db:
        cfg_dict = await _resolve_default_compiler_config(auth_db)
        entry = await model_pool.get_default(auth_db)
        provider = entry.provider if entry else "openai"
    if not cfg_dict.get("api_key") or not cfg_dict.get("base_url"):
        raise HTTPException(
            400, "no API config available for the default compiler model",
        )
    return provider, cfg_dict


async def post_message(
    draft_id: str,
    body: dict[str, Any],
    user: User = Depends(current_user),
):
    """Append a user message + run the rule editor agent for one turn.

    Streams SSE events: `user_message_saved`, `message_started`,
    `text_delta`, `tool_call_started`, `tool_call_delta`, `tool_result`,
    `edit_applied`, `message_completed`, `turn_done`.
    """
    user_text = str(body.get("text") or "").strip()
    if not user_text:
        raise HTTPException(400, "text is required")

    factory = get_session_factory()
    async with factory() as auth_db:
        await svc.get_draft(auth_db, draft_id=draft_id, owner_id=user.id)
    provider, cfg_dict = await _resolve_llm_config(factory)

    config = AgentConfig(
        provider=provider,
        model=str(cfg_dict.get("model") or ""),
        base_url=str(cfg_dict.get("base_url") or ""),
        api_key=str(cfg_dict.get("api_key") or ""),
    )
    owner_id = user.id

    async def _generator():
        async with factory() as stream_db:
            try:
                async for event in run_agent_turn(
                    db=stream_db,
                    owner_id=owner_id,
                    draft_id=draft_id,
                    user_text=user_text,
                    config=config,
                ):
                    yield {"data": json.dumps(event, ensure_ascii=False)}
            except Exception as exc:
                logger.exception("[chatrpg] rule editor agent stream failed")
                yield {
                    "data": json.dumps(
                        {
                            "type": "turn_done",
                            "stop_reason": "error",
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                    ),
                }

    return EventSourceResponse(_generator())


async def post_dice_message(
    draft_id: str,
    body: dict[str, Any],
    user: User = Depends(current_user),
):
    """Run one turn of the dice rule design agent.

    Body: `{ text: str }`. The dice agent now persists its transcript
    just like the main rule editor — every user/assistant/tool row
    lands in `ruleset_draft_messages` with `kind='dice'`. Reload
    rebuilds the chat from DB (caller-supplied `history` is ignored).
    Same SSE wire format as `POST /messages`, plus `dice_state_changed`
    when a procedure compiles successfully.
    """
    user_text = str(body.get("text") or "").strip()
    if not user_text:
        raise HTTPException(400, "text is required")

    factory = get_session_factory()
    async with factory() as auth_db:
        await svc.get_draft(auth_db, draft_id=draft_id, owner_id=user.id)
    provider, cfg_dict = await _resolve_llm_config(factory)

    config = DiceAgentConfig(
        provider=provider,
        model=str(cfg_dict.get("model") or ""),
        base_url=str(cfg_dict.get("base_url") or ""),
        api_key=str(cfg_dict.get("api_key") or ""),
    )
    owner_id = user.id

    # Hydrate history from DB (kind="dice") — ignore caller-supplied
    # history; DB is the source of truth now.
    async with factory() as hist_db:
        rows = await svc.list_messages(
            hist_db, draft_id=draft_id, owner_id=owner_id, kind="dice",
        )
    history_raw: list[dict[str, Any]] = [dict(r.content or {}) for r in rows]

    async def _generator():
        async with factory() as stream_db:
            # Persist the user message FIRST so even a mid-stream
            # crash leaves an audit trail of what the player asked.
            user_message_id: str | None = None
            try:
                user_msg = await svc.append_message(
                    stream_db,
                    draft_id=draft_id,
                    owner_id=owner_id,
                    role="user",
                    content={"role": "user", "content": user_text},
                    kind="dice",
                )
                user_message_id = user_msg.id
            except Exception:
                logger.exception("[chatrpg] dice user_message persist failed")
            try:
                async for event in run_dice_agent_turn(
                    db=stream_db,
                    owner_id=owner_id,
                    draft_id=draft_id,
                    user_text=user_text,
                    history=history_raw,
                    config=config,
                    user_message_id=user_message_id,
                ):
                    # Tap completed assistant + tool events so we can
                    # mirror them into ruleset_draft_messages.
                    try:
                        if event.get("type") == "message_completed":
                            asst: dict[str, Any] = {"role": "assistant"}
                            text = str(event.get("text") or "")
                            asst["content"] = text or None
                            tool_calls = event.get("tool_calls")
                            if isinstance(tool_calls, list) and tool_calls:
                                asst["tool_calls"] = tool_calls
                            await svc.append_message(
                                stream_db,
                                draft_id=draft_id,
                                owner_id=owner_id,
                                role="assistant",
                                content=asst,
                                kind="dice",
                            )
                        elif event.get("type") == "tool_result":
                            tool_msg = {
                                "role": "tool",
                                "tool_call_id": event.get("call_id"),
                                "content": json.dumps(
                                    event.get("result") or {},
                                    ensure_ascii=False,
                                ),
                            }
                            await svc.append_message(
                                stream_db,
                                draft_id=draft_id,
                                owner_id=owner_id,
                                role="tool",
                                content=tool_msg,
                                kind="dice",
                            )
                    except Exception:
                        logger.exception(
                            "[chatrpg] dice transcript mirror failed",
                        )
                    yield {"data": json.dumps(event, ensure_ascii=False)}
            except Exception as exc:
                logger.exception("[chatrpg] dice agent stream failed")
                yield {
                    "data": json.dumps(
                        {
                            "type": "turn_done",
                            "stop_reason": "error",
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                    ),
                }

    return EventSourceResponse(_generator())
