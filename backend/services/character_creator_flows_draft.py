"""Character draft import / confirm / clear flows.

These do not involve the LLM. `import_character_draft` stages a JSON card
the player pasted, `confirm_character_card` promotes a draft (imported or
generated) into the canonical session character + intake queue, and
`clear_character_draft` wipes the setup chat and any in-progress card.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from orm.models import GameSession, Message, Ruleset
from services.character_pool import save_character_to_pool

from services.character_creator_state import (
    CARD_KEY,
    CHAT_KEY,
    POOL_KEY,
    READY_KEY,
    _copy_setup_state,
    _load_chat_history,
    character_snapshot,
    utc_iso,
)


async def import_character_draft(
    db: AsyncSession,
    session: GameSession,
    character: dict[str, Any],
    *,
    pool_id: str | None = None,
) -> dict[str, Any]:
    if not character:
        raise ValueError("character is required")
    state = _copy_setup_state(session)
    state[CARD_KEY] = character
    state[READY_KEY] = True
    if pool_id:
        state[POOL_KEY] = pool_id
    else:
        state.pop(POOL_KEY, None)
    state["character_imported_at"] = utc_iso()
    session.setup_state = state
    await db.commit()
    await db.refresh(session)
    chat = await _load_chat_history(db, session.id)
    return character_snapshot(session, chat=chat)


async def confirm_character_card(
    db: AsyncSession,
    session: GameSession,
    ruleset: Ruleset,
) -> dict[str, Any]:
    state = _copy_setup_state(session)
    card = state.get(CARD_KEY) if isinstance(state.get(CARD_KEY), dict) else None
    if card is None and session.character:
        card = session.character
    if card is None:
        raise ValueError("generate or import a character before confirming")

    pool_entry = await save_character_to_pool(
        db,
        user_id=session.user_id,
        ruleset=ruleset,
        character=card,
        source="confirmed",
        source_session_id=session.id,
        pool_id=str(state.get(POOL_KEY) or "") or None,
    )
    state[POOL_KEY] = pool_entry.id
    state[CARD_KEY] = card
    state[READY_KEY] = True
    state["character_confirmed_at"] = utc_iso()
    session.setup_state = state
    session.character = card
    session.last_active_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(session)
    # Confirm covers both "imported a JSON" and "reused from pool" entry
    # paths, so this is where they get the same intake (PC portrait + NPC
    # extraction) as freshly-generated characters. Idempotent: if a
    # portrait or NPC keys already exist, the inner steps no-op.
    from services.character_intake import enqueue_character_intake
    enqueue_character_intake(session.id, session.user_id)
    chat = await _load_chat_history(db, session.id)
    return character_snapshot(session, chat=chat)


async def clear_character_draft(
    db: AsyncSession,
    session: GameSession,
) -> dict[str, Any]:
    # Drop all chat rows for this session — chat is the only thing the
    # messages table holds in chatrpg today.
    await db.execute(delete(Message).where(Message.session_id == session.id))
    state = _copy_setup_state(session)
    state.pop(CHAT_KEY, None)
    state.pop(READY_KEY, None)
    state.pop(CARD_KEY, None)
    state.pop(POOL_KEY, None)
    state.pop("character_generated_at", None)
    session.setup_state = state
    session.character = {}
    await db.commit()
    await db.refresh(session)
    return character_snapshot(session, chat=[])
