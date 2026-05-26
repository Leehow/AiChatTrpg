"""Setup-time conversational character-creation flows.

Four entry points that drive the back-and-forth between the player and the
in-world guide voice. Each one handles its own chat persistence, BP
snapshotting, ready-marker propagation, and final snapshot return.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from llm import ChatMessage
from orm.models import GameSession, Ruleset

from services.character_creator_context import _build_context
from services.character_creator_llm import (
    _call_llm,
    _extract_json_object,
    _framework_guide_output,
    _stream_reply_events,
)
from services.character_creator_prompts import (
    _chat_stream_system_prompt,
    _chat_system_prompt,
    _opening_stream_prompt,
    _opening_system_prompt,
)
from services.character_creator_state import (
    CARD_KEY,
    CHAT_KEY,
    READY_KEY,
    _build_bp_snapshot,
    _chat_messages,
    _copy_setup_state,
    _load_chat_history,
    _migrate_chat_if_needed,
    _save_chat_message,
    character_snapshot,
    utc_iso,
)


async def start_character_creation(
    db: AsyncSession,
    session: GameSession,
    ruleset: Ruleset,
    *,
    target_language: str = "",
) -> dict[str, Any]:
    await _migrate_chat_if_needed(db, session)
    chat = await _load_chat_history(db, session.id)
    if chat:
        return character_snapshot(session, chat=chat)

    context = await _build_context(db, session, ruleset)
    user_msg = "我来报到了，准备开始创建角色。[CREATE_CHARACTER]"
    _fw_inputs, fw_out = await _framework_guide_output(
        db, session, ruleset, [], user_msg,
        target_language=target_language,
    )
    raw, provider, model = await _call_llm(
        db,
        [
            ChatMessage(
                role="system",
                content=_opening_system_prompt(
                    context,
                    fw_out.variable_text_block,
                ),
            ),
            ChatMessage(
                role="user",
                content=user_msg,
            ),
        ],
        temperature=0.78,
    )
    parsed = _extract_json_object(raw)
    assistant = ""
    if isinstance(parsed, dict):
        assistant = str(parsed.get("assistant") or "").strip()
    if not assistant:
        assistant = raw.strip() or "Before the game begins, tell me who you might become."

    bp_snap = _build_bp_snapshot(session, chat_until_message_id=None)
    await _save_chat_message(
        db, session.id, "assistant", assistant,
        metadata={
            "trpg_mode": "guide",
            "provider": provider,
            "model": model,
            "bp_snapshot": bp_snap,
        },
    )
    state = _copy_setup_state(session)
    state.pop(CHAT_KEY, None)
    state[READY_KEY] = False
    session.setup_state = state
    await db.commit()
    await db.refresh(session)
    return character_snapshot(session, chat=await _load_chat_history(db, session.id))


async def stream_character_creation_start(
    db: AsyncSession,
    session: GameSession,
    ruleset: Ruleset,
    *,
    target_language: str = "",
):
    await _migrate_chat_if_needed(db, session)
    chat = await _load_chat_history(db, session.id)
    if chat:
        yield {"type": "done", "result": character_snapshot(session, chat=chat)}
        return

    user_msg = "我来报到了，准备开始创建角色。[CREATE_CHARACTER]"
    temperature = 0.78

    # Framework canonical: BP1/2/3 thinking + structured prompt come from
    # the portable framework. chatrpg's hand-rolled prompt template still
    # wraps the framework system text to preserve GM tone instructions.
    fw_inputs, fw_out = await _framework_guide_output(
        db, session, ruleset, chat, user_msg,
        target_language=target_language,
    )
    system_prompt = _opening_stream_prompt(fw_out.prompt_messages[0].content)
    thinking_lines = list(fw_out.thinking_lines)
    for line in thinking_lines:
        yield {"type": "thinking", "content": line}

    assistant = ""
    metadata: dict[str, Any] = {"trpg_mode": "guide"}
    async for event in _stream_reply_events(
        db,
        [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_msg),
        ],
        temperature=temperature,
    ):
        if event["type"] == "_final":
            assistant = str(event["assistant"])
            metadata["provider"] = event.get("provider", "")
            metadata["model"] = event.get("model", "")
        else:
            yield event

    if not assistant:
        assistant = "Before the game begins, tell me who you might become."

    # Framework marker parsing: detect [CREATE_CHARACTER] etc. uniformly
    # across chatlab + chatrpg.
    from agents.trpg.framework.markers import apply_markers, parse_markers
    markers = parse_markers(assistant)
    diff = apply_markers(markers, fw_inputs.session_state)
    ready = bool(diff.state_transitions.get("character_ready"))
    if ready:
        metadata["create_character_ready"] = True
        yield {"type": "metadata", "metadata": {"create_character_ready": True}}

    result_line = f"[result] reply_chars={len(assistant)} ready={str(ready).lower()}"
    thinking_lines.append(result_line)
    yield {"type": "thinking", "content": result_line}
    bp_snap = _build_bp_snapshot(session, chat_until_message_id=None)
    metadata["bp_snapshot"] = bp_snap
    await _save_chat_message(
        db, session.id, "assistant", assistant,
        thinking_steps=thinking_lines, metadata=metadata,
    )
    state = _copy_setup_state(session)
    state.pop(CHAT_KEY, None)
    state[READY_KEY] = ready
    session.setup_state = state
    await db.commit()
    await db.refresh(session)
    yield {"type": "done", "result": character_snapshot(
        session, chat=await _load_chat_history(db, session.id),
    )}


async def stream_character_creation_chat(
    db: AsyncSession,
    session: GameSession,
    ruleset: Ruleset,
    user_message: str,
    *,
    target_language: str = "",
):
    text = user_message.strip()
    if not text:
        raise ValueError("message is required")

    await _migrate_chat_if_needed(db, session)
    chat = await _load_chat_history(db, session.id)
    # Append user msg locally so the prompt-builder sees it; it'll be
    # persisted to messages table after the LLM call finishes successfully.
    chat.append({
        "role": "user", "content": text,
        "created_at": utc_iso(), "metadata": {}, "thinking_steps": [],
    })
    temperature = 0.7

    # Framework canonical (see stream_character_creation_start for rationale).
    fw_inputs, fw_out = await _framework_guide_output(
        db, session, ruleset, chat, text,
        target_language=target_language,
    )
    system_prompt = _chat_stream_system_prompt(fw_out.prompt_messages[0].content)
    thinking_lines = list(fw_out.thinking_lines)
    thinking_lines.append(f"[input] user_chars={len(text)}")
    for line in thinking_lines:
        yield {"type": "thinking", "content": line}

    assistant = ""
    metadata: dict[str, Any] = {"trpg_mode": "guide"}
    async for event in _stream_reply_events(
        db,
        [
            ChatMessage(role="system", content=system_prompt),
            *_chat_messages(chat),
        ],
        temperature=temperature,
    ):
        if event["type"] == "_final":
            assistant = str(event["assistant"])
            metadata["provider"] = event.get("provider", "")
            metadata["model"] = event.get("model", "")
        else:
            yield event

    if not assistant:
        assistant = "Tell me a little more about the person behind that choice."

    from agents.trpg.framework.markers import apply_markers, parse_markers
    markers = parse_markers(assistant)
    diff = apply_markers(markers, fw_inputs.session_state)
    ready = bool(diff.state_transitions.get("character_ready"))
    if ready:
        metadata["create_character_ready"] = True
        yield {"type": "metadata", "metadata": {"create_character_ready": True}}
    thinking_lines.append(f"[result] reply_chars={len(assistant)} ready={str(ready).lower()}")
    user_msg_id = await _save_chat_message(db, session.id, "user", text)
    state = _copy_setup_state(session)
    state.pop(CHAT_KEY, None)
    state[READY_KEY] = ready
    state.pop(CARD_KEY, None)
    session.setup_state = state
    bp_snap = _build_bp_snapshot(session, chat_until_message_id=user_msg_id)
    metadata["bp_snapshot"] = bp_snap
    await _save_chat_message(
        db, session.id, "assistant", assistant,
        thinking_steps=thinking_lines, metadata=metadata,
    )
    await db.commit()
    await db.refresh(session)
    yield {"type": "done", "result": character_snapshot(
        session, chat=await _load_chat_history(db, session.id),
    )}


async def chat_character_creation(
    db: AsyncSession,
    session: GameSession,
    ruleset: Ruleset,
    user_message: str,
    *,
    target_language: str = "",
) -> dict[str, Any]:
    text = user_message.strip()
    if not text:
        raise ValueError("message is required")

    await _migrate_chat_if_needed(db, session)
    chat = await _load_chat_history(db, session.id)
    chat.append({
        "role": "user", "content": text,
        "created_at": utc_iso(), "metadata": {}, "thinking_steps": [],
    })

    context = await _build_context(db, session, ruleset)
    _fw_inputs, fw_out = await _framework_guide_output(
        db, session, ruleset, chat, text,
        target_language=target_language,
    )
    raw, provider, model = await _call_llm(
        db,
        [
            ChatMessage(
                role="system",
                content=_chat_system_prompt(
                    context,
                    fw_out.variable_text_block,
                ),
            ),
            *_chat_messages(chat),
        ],
        temperature=0.7,
    )
    parsed = _extract_json_object(raw)
    assistant = ""
    ready = False
    if isinstance(parsed, dict):
        assistant = str(parsed.get("assistant") or "").strip()
        ready = bool(parsed.get("ready"))
    if not assistant:
        assistant = raw.strip() or "Tell me a little more about the character."

    asst_meta = {
        "trpg_mode": "guide",
        "provider": provider,
        "model": model,
        **({"create_character_ready": True} if ready else {}),
    }
    user_msg_id = await _save_chat_message(db, session.id, "user", text)
    state = _copy_setup_state(session)
    state.pop(CHAT_KEY, None)
    state[READY_KEY] = ready
    session.setup_state = state
    asst_meta["bp_snapshot"] = _build_bp_snapshot(
        session, chat_until_message_id=user_msg_id,
    )
    await _save_chat_message(
        db, session.id, "assistant", assistant, metadata=asst_meta,
    )
    await db.commit()
    await db.refresh(session)
    chat = await _load_chat_history(db, session.id)
    return {**character_snapshot(session, chat=chat), "assistant": assistant}
