from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from orm.models import CharacterPoolEntry, Ruleset, User
from routes.deps import current_user, db_session
from schemas.character_pool import CharacterPoolCreateRequest, CharacterPoolOut
from schemas.common import OkResponse
from services.character_pool import list_character_pool, save_character_to_pool

router = APIRouter(prefix="/api/characters", tags=["characters"])


def _out(entry: CharacterPoolEntry) -> CharacterPoolOut:
    return CharacterPoolOut(
        id=entry.id,
        ruleset_id=entry.ruleset_id,
        ruleset_title=entry.ruleset_title,
        ruleset_short_name=entry.ruleset_short_name,
        name=entry.name,
        source=entry.source,
        source_session_id=entry.source_session_id,
        character=entry.character or {},
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


async def _get_visible_ruleset(
    db: AsyncSession,
    ruleset_id: str,
    user: User,
) -> Ruleset:
    """Mine ∪ shared. Saving a character against a ruleset doesn't mutate
    the ruleset, so non-owners on a shared ruleset can use it as the
    reference point for their own pool entries."""
    rs = await db.get(Ruleset, ruleset_id)
    if rs is None or not (rs.owner_id == user.id or rs.is_shared):
        raise HTTPException(404, "ruleset not found")
    return rs


@router.get("", response_model=list[CharacterPoolOut])
async def list_characters(
    ruleset_id: str | None = Query(default=None),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> list[CharacterPoolOut]:
    if ruleset_id:
        await _get_visible_ruleset(db, ruleset_id, user)
    rows = await list_character_pool(db, user_id=user.id, ruleset_id=ruleset_id)
    return [_out(row) for row in rows]


@router.post("", response_model=CharacterPoolOut)
async def create_character(
    body: CharacterPoolCreateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> CharacterPoolOut:
    rs = await _get_visible_ruleset(db, body.ruleset_id, user)
    entry = await save_character_to_pool(
        db,
        user_id=user.id,
        ruleset=rs,
        character=body.character,
        source=body.source,
        source_session_id=body.source_session_id,
    )
    await db.commit()
    await db.refresh(entry)
    return _out(entry)


@router.delete("/{character_id}", response_model=OkResponse)
async def delete_character(
    character_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> OkResponse:
    entry = await db.get(CharacterPoolEntry, character_id)
    if entry is None or entry.user_id != user.id:
        raise HTTPException(404, "character not found")
    await db.delete(entry)
    await db.commit()
    return OkResponse()
