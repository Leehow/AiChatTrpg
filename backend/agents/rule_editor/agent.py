"""Rule editor agent loop — streaming Chat Completions with tool calling.

Yields a stream of plain dict events (`{"type": "...", ...}`) suitable
for chatrpg's SSE wire format. The route layer wraps these in
`EventSourceResponse`.

Iteration cap MAX_ITERS prevents runaway. Tool errors come back as
`role: "tool"` content with `{"error": True, ...}` so the LLM can
self-correct.

The agent uses raw AsyncOpenAI directly — chatrpg's `LLMClient` base
protocol is text-only and doesn't support tool calling.
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
from orm.models import RulesetDraftMessage
from services import ruleset_drafts as svc

from .agent_context import (
    build_design_context_block,
    events_from_tool_payload,
    strip_internal_markers,
)
from .phase_skills import select_skill_for_draft
from .prompts import build_system_prompt
from .tools import (
    ToolContext,
    build_tools_schema_for_draft,
    get_allowed_tool_for_draft,
)


logger = logging.getLogger("chatrpg.rule_editor.agent")

MAX_ITERS = 8


@dataclass
class AgentConfig:
    provider: str
    model: str
    base_url: str
    api_key: str


@dataclass
class _ToolCallAccumulator:
    """Collected from streamed tool_call deltas."""
    index: int
    call_id: str = ""
    name: str = ""
    arguments_buf: list[str] = field(default_factory=list)
    started_emitted: bool = False

    @property
    def arguments(self) -> str:
        return "".join(self.arguments_buf)


def _msg_to_openai(m: RulesetDraftMessage) -> dict[str, Any]:
    """Convert a stored draft message into an OpenAI Chat Completions msg."""
    c = m.content or {}
    if m.role == "user":
        return {"role": "user", "content": str(c.get("text") or "")}
    if m.role == "assistant":
        out: dict[str, Any] = {"role": "assistant"}
        text = c.get("text")
        out["content"] = text if text else None
        if c.get("tool_calls"):
            out["tool_calls"] = c["tool_calls"]
        return out
    if m.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": str(c.get("tool_call_id") or ""),
            "content": str(c.get("content") or ""),
        }
    return {"role": "user", "content": ""}


async def run_agent_turn(
    *,
    db: AsyncSession,
    owner_id: str,
    draft_id: str,
    user_text: str,
    config: AgentConfig,
) -> AsyncIterator[dict[str, Any]]:
    """Single-turn entrypoint. Persists user msg, runs tool loop, persists
    assistant + tool messages, yields SSE events as they happen."""
    user_msg = await svc.append_message(
        db, draft_id=draft_id, owner_id=owner_id,
        role="user", content={"text": user_text},
    )
    yield {"type": "user_message_saved", "message_id": user_msg.id}

    # Pull the current draft so we can bake the live design-state
    # context block + the manifest into the system prompt. The
    # design-state block reflects the most recent persisted snapshot;
    # tool payloads inside the loop carry the intra-turn updates.
    draft = await svc.get_draft(
        db, draft_id=draft_id, owner_id=owner_id,
    )
    from services.draft_manifest import manifest_block_for_draft
    design_block = build_design_context_block(draft)
    manifest_block = manifest_block_for_draft(draft)
    skill = select_skill_for_draft(draft)
    sys_prompt = build_system_prompt(
        context_block=design_block,
        skill_fragment=skill.prompt_fragment,
    )
    if manifest_block:
        sys_prompt = sys_prompt + "\n\n" + manifest_block

    history = await svc.list_messages(
        db, draft_id=draft_id, owner_id=owner_id, after_seq=0,
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": sys_prompt},
    ]
    for m in history:
        messages.append(_msg_to_openai(m))

    tools = build_tools_schema_for_draft(draft)
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

    for iteration in range(MAX_ITERS):
        msg_id = f"asst_{uuid.uuid4().hex[:16]}"
        yield {
            "type": "message_started",
            "message_id": msg_id,
            "role": "assistant",
        }
        text_chunks: list[str] = []
        tool_accs: dict[int, _ToolCallAccumulator] = {}
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
        except Exception as exc:
            logger.exception("[chatrpg] rule editor LLM open failed")
            yield {"type": "turn_done", "stop_reason": "error", "error": str(exc)}
            return

        try:
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
                    acc = tool_accs.setdefault(
                        idx, _ToolCallAccumulator(index=idx),
                    )
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
            logger.exception("[chatrpg] rule editor LLM stream failed")
            yield {"type": "turn_done", "stop_reason": "error", "error": str(exc)}
            return

        # Backfill tool_call_started for any acc that didn't get the
        # `started_emitted` flag (rare — some providers send id after name).
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

        # Persist assistant turn.
        msg_payload: dict[str, Any] = {}
        if assistant_text:
            msg_payload["text"] = assistant_text
        if ordered_calls:
            msg_payload["tool_calls"] = [
                {
                    "id": acc.call_id,
                    "type": "function",
                    "function": {
                        "name": acc.name,
                        "arguments": acc.arguments,
                    },
                }
                for acc in ordered_calls
            ]
        if not msg_payload:
            msg_payload["text"] = ""
        saved = await svc.append_message(
            db, draft_id=draft_id, owner_id=owner_id,
            role="assistant", content=msg_payload,
        )
        yield {"type": "message_completed", "message_id": saved.id}

        # Add to OpenAI history for the next iteration.
        if ordered_calls:
            messages.append({
                "role": "assistant",
                "content": assistant_text or None,
                "tool_calls": msg_payload["tool_calls"],
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

        # Execute each tool call.
        for acc in ordered_calls:
            # Re-resolve the draft per call so phase-aware gating sees
            # mutations from any prior tool call in the same turn.
            draft = await svc.get_draft(
                db, draft_id=draft_id, owner_id=owner_id,
            )
            tool = get_allowed_tool_for_draft(draft, acc.name)
            try:
                args = json.loads(acc.arguments) if acc.arguments else {}
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}

            if tool is None:
                tool_result_payload: dict[str, Any] = {
                    "error": True,
                    "code": "tool_not_advertised",
                    "message": (
                        f"tool `{acc.name}` is not in the advertised "
                        "set for this draft -- legacy parsed_v6 "
                        "writers are hidden in P0.6; use "
                        "apply_design_ops / apply_blueprint / "
                        "compile_design instead"
                    ),
                }
                edit_id: str | None = None
            else:
                tctx = ToolContext(
                    db=db, owner_id=owner_id, draft_id=draft_id,
                    assistant_message_id=saved.id,
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

            for ev in events_from_tool_payload(
                payload=tool_result_payload, edit_id=edit_id,
            ):
                yield ev

            public_payload = strip_internal_markers(tool_result_payload)
            yield {
                "type": "tool_result",
                "call_id": acc.call_id,
                "tool_name": acc.name,
                "result": public_payload,
                "edit_id": edit_id,
            }

            if edit_id:
                draft = await svc.get_draft(
                    db, draft_id=draft_id, owner_id=owner_id,
                )
                yield {
                    "type": "edit_applied",
                    "edit_id": edit_id,
                    "diff": public_payload.get("diff") or [],
                    "parsed_v6_after": draft.parsed_v6 or {},
                    "needs_dice_compile": bool(draft.needs_dice_compile),
                    "needs_character_ui_compile": bool(
                        draft.needs_character_ui_compile,
                    ),
                }

            tool_content_str = json.dumps(
                public_payload, ensure_ascii=False,
            )
            await svc.append_message(
                db, draft_id=draft_id, owner_id=owner_id,
                role="tool",
                content={
                    "tool_call_id": acc.call_id,
                    "tool_name": acc.name,
                    "content": tool_content_str,
                },
            )
            messages.append({
                "role": "tool",
                "tool_call_id": acc.call_id,
                "content": tool_content_str,
            })

        # Refresh the tools schema for the next outer iteration so a
        # tool call that advanced `draft.design_phase` (set_phase,
        # apply_blueprint, ...) narrows the advertised surface for the
        # next LLM call in this same turn. `draft` is the most recent
        # version because it was re-fetched per tool call inside the
        # loop above (and again after every edit_applied).
        tools = build_tools_schema_for_draft(draft)

    yield {"type": "turn_done", "stop_reason": "max_iters"}
