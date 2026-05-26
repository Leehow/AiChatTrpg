"""Character-card generation flows (blocking + streaming).

Both flows ask the LLM to produce one complete playable card, apply the
mechanical seed, strip non-template fields, persist the draft, and queue
the post-creation intake (PC portrait + significant-NPC extraction).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from llm import ChatMessage, build_client
from orm.models import GameSession, Ruleset
from services.character_generation_adapter import (
    apply_character_mechanical_seed,
    build_character_mechanical_seed,
    character_seed_summary,
)
from services.character_pool import save_character_to_pool
from services.character_template_filter import (
    filter_card_by_template,
    render_template_schema_hint,
)

from services.character_creator_context import (
    _build_context,
    _ruleset_template_json,
)
from services.character_creator_llm import (
    _call_llm,
    _character_output_language,
    _character_summary,
    _extract_json_object,
    _framework_guide_output,
    _looks_like_card,
    _resolve_model,
)
from services.character_creator_prompts import _generate_system_prompt
from services.character_creator_state import (
    CARD_KEY,
    CHAT_KEY,
    POOL_KEY,
    READY_KEY,
    _build_bp_snapshot,
    _copy_setup_state,
    _format_transcript,
    _load_chat_history,
    _migrate_chat_if_needed,
    _save_chat_message,
    character_snapshot,
    utc_iso,
)


async def generate_character_card(
    db: AsyncSession,
    session: GameSession,
    ruleset: Ruleset,
    *,
    mode: str = "from_chat",
    seed: str = "",
    target_language: str = "",
    thinking_steps: list[str] | None = None,
) -> dict[str, Any]:
    await _migrate_chat_if_needed(db, session)
    chat = await _load_chat_history(db, session.id)
    seed_text = seed.strip()
    if seed_text:
        chat.append({
            "role": "user", "content": seed_text,
            "created_at": utc_iso(), "metadata": {}, "thinking_steps": [],
        })

    context = await _build_context(db, session, ruleset)
    transcript = _format_transcript(chat)
    mechanical_seed = build_character_mechanical_seed(
        ruleset,
        session_id=session.id,
        user_seed=seed_text,
        mode=mode,
        transcript=transcript,
    )
    if mode == "auto" and not transcript:
        instruction = (
            "The player chose one-click creation. Generate one complete, "
            "ready-to-play character and make all missing choices yourself."
        )
    else:
        instruction = (
            "Use the setup conversation as the seed. Preserve player choices, "
            "then complete every missing field using the rules."
        )

    language = _character_output_language(ruleset, target_language)
    template_json = _ruleset_template_json(ruleset)
    template_hint = render_template_schema_hint(template_json)
    system_prompt = _generate_system_prompt(
        context, language, template_hint=template_hint,
    )
    seed_block = mechanical_seed.prompt_block()
    user_content = (
        f"{instruction}\n\n## Setup Conversation\n{transcript or '(none)'}"
        + (f"\n\n{seed_block}" if seed_block else "")
    )
    if thinking_steps is not None:
        thinking_steps.append(
            f"[prompt] system={len(system_prompt)} user={len(user_content)} "
            f"total={len(system_prompt) + len(user_content)} mode={mode} "
            f"seed_chars={len(seed_text)} language={language}"
        )
        thinking_steps.append(f"[mechanics] {character_seed_summary(mechanical_seed)}")

    raw, provider, model = await _call_llm(
        db,
        [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_content),
        ],
        temperature=0.75,
    )
    parsed = _extract_json_object(raw)
    assistant = ""
    card: dict[str, Any] | None = None

    if isinstance(parsed, dict):
        assistant = str(parsed.get("assistant") or "").strip()
        if isinstance(parsed.get("card"), dict):
            card = parsed["card"]
        elif _looks_like_card(parsed):
            card = parsed

    if card is None:
        raise ValueError("LLM did not return a character card JSON object.")
    card = apply_character_mechanical_seed(card, mechanical_seed)
    card, dropped = filter_card_by_template(card, template_json)
    if dropped and thinking_steps is not None:
        thinking_steps.append(
            f"[strict-filter] dropped {len(dropped)} hallucinated fields: "
            f"{', '.join(d['path'] for d in dropped[:8])}"
            + (f" …+{len(dropped) - 8}" if len(dropped) > 8 else "")
        )
    if not assistant:
        assistant = _character_summary(card)

    if thinking_steps is not None:
        thinking_steps.append(
            f"[result] reply_chars={len(assistant)} card_fields={len(card)}"
        )
    user_msg_id: str | None = None
    if seed_text:
        user_msg_id = await _save_chat_message(db, session.id, "user", seed_text)
    state = _copy_setup_state(session)
    state.pop(CHAT_KEY, None)
    state[READY_KEY] = True
    state[CARD_KEY] = card
    state["character_generated_at"] = utc_iso()
    state["character_generation_seed"] = mechanical_seed.to_metadata()
    pool_entry = await save_character_to_pool(
        db,
        user_id=session.user_id,
        ruleset=ruleset,
        character=card,
        source="generated",
        source_session_id=session.id,
        pool_id=str(state.get(POOL_KEY) or "") or None,
    )
    state[POOL_KEY] = pool_entry.id
    session.setup_state = state
    session.last_active_at = datetime.now(timezone.utc)
    asst_meta = {
        "create_character_ready": True,
        "character_generated": True,
        "provider": provider,
        "model": model,
        "character_generation_seed": mechanical_seed.to_metadata(),
        "bp_snapshot": _build_bp_snapshot(
            session, chat_until_message_id=user_msg_id,
        ),
    }
    await _save_chat_message(
        db, session.id, "assistant", assistant,
        thinking_steps=thinking_steps,
        metadata=asst_meta,
    )
    await db.commit()
    await db.refresh(session)
    chat_after = await _load_chat_history(db, session.id)
    # Same intake hook as the streaming path — see comment there.
    from services.character_intake import enqueue_character_intake
    enqueue_character_intake(session.id, session.user_id)
    return {
        **character_snapshot(session, chat=chat_after),
        "assistant": assistant,
    }


async def stream_generate_character_card(
    db: AsyncSession,
    session: GameSession,
    ruleset: Ruleset,
    *,
    mode: str = "from_chat",
    seed: str = "",
    target_language: str = "",
):
    """Stream LLM tokens as they arrive so the player sees the character JSON
    materialise progressively. After the stream completes, the raw output is
    parsed, the card persisted, and the canonical draft returned via `done`.
    """
    await _migrate_chat_if_needed(db, session)
    chat = await _load_chat_history(db, session.id)
    seed_text = seed.strip()
    if seed_text:
        chat.append({
            "role": "user", "content": seed_text,
            "created_at": utc_iso(), "metadata": {}, "thinking_steps": [],
        })

    _fw_inputs, fw_out = await _framework_guide_output(
        db, session, ruleset, chat, "",
    )
    thinking_steps = [
        l for l in fw_out.thinking_lines if not l.startswith("[prompt]")
    ]
    thinking_steps.append("[stage] character_card_generation")
    for line in thinking_steps:
        yield {"type": "thinking", "content": line}

    context = await _build_context(db, session, ruleset)
    transcript = _format_transcript(chat)
    mechanical_seed = build_character_mechanical_seed(
        ruleset,
        session_id=session.id,
        user_seed=seed_text,
        mode=mode,
        transcript=transcript,
    )
    if mode == "auto" and not transcript:
        instruction = (
            "The player chose one-click creation. Generate one complete, "
            "ready-to-play character and make all missing choices yourself."
        )
    else:
        instruction = (
            "Use the setup conversation as the seed. Preserve player choices, "
            "then complete every missing field using the rules."
        )
    language = _character_output_language(ruleset, target_language)
    template_json = _ruleset_template_json(ruleset)
    template_hint = render_template_schema_hint(template_json)
    system_prompt = _generate_system_prompt(
        context, language, template_hint=template_hint,
    )
    seed_block = mechanical_seed.prompt_block()
    user_content = (
        f"{instruction}\n\n## Setup Conversation\n{transcript or '(none)'}"
        + (f"\n\n{seed_block}" if seed_block else "")
    )
    prompt_step = (
        f"[prompt] system={len(system_prompt)} user={len(user_content)} "
        f"total={len(system_prompt) + len(user_content)} mode={mode} "
        f"seed_chars={len(seed_text)} language={language} "
        f"template_keys={len(template_json or {})}"
    )
    thinking_steps.append(prompt_step)
    thinking_steps.append(f"[mechanics] {character_seed_summary(mechanical_seed)}")
    yield {"type": "thinking", "content": prompt_step}
    yield {"type": "thinking", "content": thinking_steps[-1]}

    # Stream LLM tokens straight to the client so the JSON materialises live.
    provider, model, api_key, base_url = await _resolve_model(db)
    client = build_client(provider, model, api_key, base_url)
    raw_parts: list[str] = []
    async for chunk in client.stream_chat(
        [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_content),
        ],
        temperature=0.75,
    ):
        if chunk.delta:
            raw_parts.append(chunk.delta)
            yield {"type": "content", "content": chunk.delta}
    raw = "".join(raw_parts).strip()

    parsed = _extract_json_object(raw)
    assistant = ""
    card: dict[str, Any] | None = None
    if isinstance(parsed, dict):
        assistant = str(parsed.get("assistant") or "").strip()
        if isinstance(parsed.get("card"), dict):
            card = parsed["card"]
        elif _looks_like_card(parsed):
            card = parsed
    if card is None:
        raise ValueError("LLM did not return a character card JSON object.")
    card = apply_character_mechanical_seed(card, mechanical_seed)
    card, dropped = filter_card_by_template(card, template_json)
    if dropped:
        filter_step = (
            f"[strict-filter] dropped {len(dropped)} hallucinated fields: "
            + ", ".join(d["path"] for d in dropped[:8])
            + (f" …+{len(dropped) - 8}" if len(dropped) > 8 else "")
        )
        thinking_steps.append(filter_step)
        yield {"type": "thinking", "content": filter_step}
    if not assistant:
        assistant = _character_summary(card)

    result_step = (
        f"[result] reply_chars={len(assistant)} card_fields={len(card)}"
    )
    thinking_steps.append(result_step)
    yield {"type": "thinking", "content": result_step}

    user_msg_id: str | None = None
    if seed_text:
        user_msg_id = await _save_chat_message(
            db, session.id, "user", seed_text,
        )
    state = _copy_setup_state(session)
    state.pop(CHAT_KEY, None)
    state[READY_KEY] = True
    state[CARD_KEY] = card
    state["character_generated_at"] = utc_iso()
    state["character_generation_seed"] = mechanical_seed.to_metadata()
    pool_entry = await save_character_to_pool(
        db,
        user_id=session.user_id,
        ruleset=ruleset,
        character=card,
        source="generated",
        source_session_id=session.id,
        pool_id=str(state.get(POOL_KEY) or "") or None,
    )
    state[POOL_KEY] = pool_entry.id
    session.setup_state = state
    session.last_active_at = datetime.now(timezone.utc)
    asst_meta = {
        "create_character_ready": True,
        "character_generated": True,
        "provider": provider,
        "model": model,
        "character_generation_seed": mechanical_seed.to_metadata(),
        "bp_snapshot": _build_bp_snapshot(
            session, chat_until_message_id=user_msg_id,
        ),
    }
    await _save_chat_message(
        db, session.id, "assistant", assistant,
        thinking_steps=thinking_steps,
        metadata=asst_meta,
    )
    await db.commit()
    await db.refresh(session)
    chat_after = await _load_chat_history(db, session.id)
    # Kick off post-creation enrichment: avatar generation + LLM scan for
    # significant NPCs (前妻 / 警局旧识 / 委托人 …) that should be auto-
    # added to memory_state.npcs[]. Fire-and-forget — the player enters
    # the game immediately; portraits and NPCs populate as they finish.
    from services.character_intake import enqueue_character_intake
    enqueue_character_intake(session.id, session.user_id)
    result = {
        **character_snapshot(session, chat=chat_after),
        "assistant": assistant,
    }
    yield {"type": "metadata", "metadata": {"create_character_ready": True}}
    yield {"type": "done", "result": result}
