from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orm.models import CharacterPoolEntry, Ruleset


def extract_character_name(character: dict[str, Any]) -> str:
    identity = character.get("identity") if isinstance(character.get("identity"), dict) else {}
    for value in (
        character.get("display_name"),
        character.get("name"),
        character.get("character_name"),
        identity.get("display_name"),
        identity.get("name"),
        identity.get("character_name"),
        identity.get("full_name"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()[:255]
    return "Unnamed character"


async def save_character_to_pool(
    db: AsyncSession,
    *,
    user_id: str,
    ruleset: Ruleset,
    character: dict[str, Any],
    source: str,
    source_session_id: str | None = None,
    pool_id: str | None = None,
) -> CharacterPoolEntry:
    card = _json_copy(character)
    entry: CharacterPoolEntry | None = None
    if pool_id:
        existing = await db.get(CharacterPoolEntry, pool_id)
        if existing is not None and existing.user_id == user_id:
            entry = existing

    if entry is None:
        entry = CharacterPoolEntry(
            id=str(uuid.uuid4()),
            user_id=user_id,
        )
        db.add(entry)

    entry.ruleset_id = ruleset.id
    entry.ruleset_title = ruleset.book_title
    entry.ruleset_short_name = ruleset.short_name
    entry.name = extract_character_name(card)
    entry.source = source[:32] or "generated"
    entry.source_session_id = source_session_id
    entry.character = card
    return entry


async def list_character_pool(
    db: AsyncSession,
    *,
    user_id: str,
    ruleset_id: str | None = None,
) -> list[CharacterPoolEntry]:
    stmt = select(CharacterPoolEntry).where(CharacterPoolEntry.user_id == user_id)
    if ruleset_id:
        stmt = stmt.where(CharacterPoolEntry.ruleset_id == ruleset_id)
    stmt = stmt.order_by(CharacterPoolEntry.updated_at.desc(), CharacterPoolEntry.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _json_copy(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False))
