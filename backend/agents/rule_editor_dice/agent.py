"""Dice agent loop — same Chat-Completions tool-calling pattern as the
main editor agent (`agents.rule_editor.agent`), specialized to dice.

The route mirrors dice user / assistant / tool messages into
RulesetDraftMessage with kind="dice". This loop stays transport-focused:
it receives OpenAI-format history from the route, streams events, and
persists compiled specs into `draft.parsed_v6.dice_ir` through tools.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from agents.grep_retrieval.runtime_openai import (
    apply_openai_request_defaults,
    build_openai_client,
    resolve_openai_compat_base_url,
)
from agents.rule_editor.tools import ToolContext

from .prompts import build_dice_system_prompt
from .tools import DICE_TOOLS


logger = logging.getLogger("chatrpg.rule_editor_dice.agent")

MAX_ITERS = 6


@dataclass
class DiceAgentConfig:
    provider: str
    model: str
    base_url: str
    api_key: str


@dataclass
class _ToolCallAcc:
    index: int
    call_id: str = ""
    name: str = ""
    arguments_buf: list[str] = field(default_factory=list)
    started_emitted: bool = False

    @property
    def arguments(self) -> str:
        return "".join(self.arguments_buf)


_TOOL_INDEX = {t.name: t for t in DICE_TOOLS}


def _build_tools_schema() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.json_schema,
            },
        }
        for t in DICE_TOOLS
    ]


async def run_dice_agent_turn(
    *,
    db: AsyncSession,
    owner_id: str,
    draft_id: str,
    user_text: str,
    history: list[dict[str, Any]] | None,
    config: DiceAgentConfig,
    user_message_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run one dice agent turn. `history` is the persisted dice
    transcript in OpenAI Chat Completions message format.
    """
    yield {
        "type": "user_message_saved",
        "message_id": user_message_id or "ephemeral",
    }

    # Pull the draft so we can bake the manifest index into the system
    # prompt — without it the dice agent has no view of the rule
    # editor's work and can compile a procedure whose value range is
    # incompatible with the character_sheet's attribute scale.
    from services import ruleset_drafts as svc
    from services.draft_manifest import manifest_block_for_draft
    draft = await svc.get_draft(db, draft_id=draft_id, owner_id=owner_id)
    manifest_block = manifest_block_for_draft(draft)
    sys_prompt = build_dice_system_prompt()
    if manifest_block:
        sys_prompt = sys_prompt + "\n\n" + manifest_block

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": sys_prompt},
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    tools = _build_tools_schema()
    base_url = resolve_openai_compat_base_url(config.provider, config.base_url)
    if not base_url:
        yield {
            "type": "turn_done",
            "stop_reason": "error",
            "error": (
                f"no OpenAI-compat base_url for provider `{config.provider}`"
            ),
        }
        return
    client = build_openai_client(base_url=base_url, api_key=config.api_key)

    for _iter in range(MAX_ITERS):
        msg_id = f"asst_{uuid.uuid4().hex[:16]}"
        yield {
            "type": "message_started",
            "message_id": msg_id,
            "role": "assistant",
        }
        text_chunks: list[str] = []
        tool_accs: dict[int, _ToolCallAcc] = {}
        finish_reason: str | None = None

        kwargs = apply_openai_request_defaults({
            "model": config.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": True,
        })

        try:
            stream = await client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = getattr(choice, "delta", None)
                if delta is None:
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason
                    continue

                if delta.content:
                    text_chunks.append(delta.content)
                    yield {"type": "text_delta", "delta": delta.content}

                tcs = getattr(delta, "tool_calls", None) or []
                for tc in tcs:
                    idx = getattr(tc, "index", 0)
                    acc = tool_accs.setdefault(idx, _ToolCallAcc(index=idx))
                    if getattr(tc, "id", None):
                        acc.call_id = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            acc.name = fn.name
                        if getattr(fn, "arguments", None):
                            acc.arguments_buf.append(fn.arguments)
                    if (
                        not acc.started_emitted
                        and acc.call_id
                        and acc.name
                    ):
                        acc.started_emitted = True
                        yield {
                            "type": "tool_call_started",
                            "call_id": acc.call_id,
                            "tool_name": acc.name,
                            "index": idx,
                        }
                    if (
                        acc.started_emitted
                        and fn
                        and getattr(fn, "arguments", None)
                    ):
                        yield {
                            "type": "tool_call_delta",
                            "call_id": acc.call_id,
                            "args_delta": fn.arguments,
                        }

                if choice.finish_reason:
                    finish_reason = choice.finish_reason
        except Exception as exc:
            logger.exception("[chatrpg] dice agent stream failed")
            yield {"type": "turn_done", "stop_reason": "error", "error": str(exc)}
            return

        for acc in tool_accs.values():
            if not acc.started_emitted and acc.call_id:
                acc.started_emitted = True
                yield {
                    "type": "tool_call_started",
                    "call_id": acc.call_id,
                    "tool_name": acc.name,
                    "index": acc.index,
                }

        assistant_text = "".join(text_chunks)
        ordered_calls = sorted(tool_accs.values(), key=lambda a: a.index)

        # Emit message_completed with the assembled assistant text/calls.
        yield {
            "type": "message_completed",
            "message_id": msg_id,
            "text": assistant_text,
            "tool_calls": [
                {
                    "id": acc.call_id,
                    "type": "function",
                    "function": {
                        "name": acc.name,
                        "arguments": acc.arguments,
                    },
                }
                for acc in ordered_calls
            ],
        }

        if ordered_calls:
            messages.append({
                "role": "assistant",
                "content": assistant_text or None,
                "tool_calls": [
                    {
                        "id": acc.call_id,
                        "type": "function",
                        "function": {
                            "name": acc.name,
                            "arguments": acc.arguments,
                        },
                    }
                    for acc in ordered_calls
                ],
            })
        else:
            messages.append({
                "role": "assistant",
                "content": assistant_text,
            })

        if not ordered_calls:
            yield {
                "type": "turn_done",
                "stop_reason": (
                    "length" if finish_reason == "length" else "end_turn"
                ),
            }
            return

        for acc in ordered_calls:
            tool = _TOOL_INDEX.get(acc.name)
            try:
                args = json.loads(acc.arguments) if acc.arguments else {}
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}

            if tool is None:
                tool_result_payload: dict[str, Any] = {
                    "error": True,
                    "code": "unknown_tool",
                    "message": f"no such tool `{acc.name}`",
                }
                edit_id: str | None = None
            else:
                tctx = ToolContext(
                    db=db, owner_id=owner_id, draft_id=draft_id,
                    assistant_message_id=None,
                )
                try:
                    result = await tool.execute(tctx, args)
                    tool_result_payload = result.payload
                    edit_id = result.edit_id
                except Exception as exc:
                    code = getattr(exc, "code", "tool_error")
                    msg_str = getattr(exc, "message", str(exc))
                    tool_result_payload = {
                        "error": True, "code": code, "message": msg_str,
                    }
                    edit_id = None

            yield {
                "type": "tool_result",
                "call_id": acc.call_id,
                "tool_name": acc.name,
                "result": tool_result_payload,
                "edit_id": edit_id,
            }

            # If the dice tool persisted into parsed_v6.dice_ir, emit a
            # state-changed event so the frontend reloads the left preview.
            if acc.name == "design_dice_procedure" and not (
                tool_result_payload.get("error")
            ):
                yield {
                    "type": "dice_state_changed",
                }

            tool_content_str = json.dumps(
                tool_result_payload, ensure_ascii=False,
            )
            messages.append({
                "role": "tool",
                "tool_call_id": acc.call_id,
                "content": tool_content_str,
            })

    yield {"type": "turn_done", "stop_reason": "max_iters"}
