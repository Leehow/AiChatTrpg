"""Database-backed model pool — (provider, model) registry with role flags.

The pool lives in `model_pool_entries`. Independent role flags exist —
each role's flag is held by exactly one row at a time (or zero if the
pool is empty); a single row may hold any combination of flags. See
`ROLES` for the canonical role set and `orm.models.ModelPoolEntry` for
per-role semantics.

On first use we seed the table with the codex-relay debug entry that
is already in active use, marked with every role flag, so the UI shows
a sensible setup instead of an empty list.

All mutations commit before returning so route handlers don't have to
think about transaction boundaries.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from llm import list_providers
from orm.models import ModelPoolEntry

SEED_PROVIDER = "debug"
SEED_MODEL = "gpt-5.5"

# role_name -> ORM column name. Order matters for UI display.
ROLES: dict[str, str] = {
    "default": "is_default",
    "fast": "is_fast",
    "dialogue": "is_dialogue",
    "avatar": "is_avatar",
    "illustration": "is_illustration",
    "narration": "is_narration",
}


async def _ordered(db: AsyncSession) -> list[ModelPoolEntry]:
    res = await db.execute(
        select(ModelPoolEntry).order_by(
            ModelPoolEntry.position, ModelPoolEntry.id
        )
    )
    return list(res.scalars())


async def _seed_if_empty(db: AsyncSession) -> None:
    rows = await _ordered(db)
    if rows:
        return
    seed = ModelPoolEntry(
        provider=SEED_PROVIDER,
        model=SEED_MODEL,
        position=0,
    )
    for flag in ROLES.values():
        setattr(seed, flag, True)
    db.add(seed)
    await db.commit()


async def list_entries(db: AsyncSession) -> list[ModelPoolEntry]:
    await _seed_if_empty(db)
    return await _ordered(db)


async def add_entry(
    db: AsyncSession, provider: str, model: str
) -> list[ModelPoolEntry]:
    if provider not in list_providers():
        raise ValueError(f"unknown provider '{provider}'")
    model = model.strip()
    if not model:
        raise ValueError("model is required")
    rows = await _ordered(db)
    for r in rows:
        if r.provider == provider and r.model == model:
            return rows  # already there — no-op
    next_pos = (rows[-1].position + 1) if rows else 0
    new_row = ModelPoolEntry(
        provider=provider,
        model=model,
        position=next_pos,
    )
    # Auto-assign any role that has no holder yet, so a freshly added
    # entry "fills" empty role slots without the admin needing to click.
    for flag in ROLES.values():
        setattr(new_row, flag, not any(getattr(r, flag) for r in rows))
    db.add(new_row)
    await db.commit()
    return await _ordered(db)


async def remove_entry(
    db: AsyncSession, provider: str, model: str
) -> list[ModelPoolEntry]:
    rows = await _ordered(db)
    target = next(
        (r for r in rows if r.provider == provider and r.model == model),
        None,
    )
    if target is None:
        return rows
    vacated = [flag for flag in ROLES.values() if getattr(target, flag)]
    await db.delete(target)
    await db.flush()
    remaining = await _ordered(db)
    if remaining:
        # Promote the first remaining row to fill any role we just
        # vacated, so the pool never has rows but no holder for a role.
        for flag in vacated:
            if not any(getattr(r, flag) for r in remaining):
                setattr(remaining[0], flag, True)
    await db.commit()
    return await _ordered(db)


async def _set_role(
    db: AsyncSession,
    provider: str,
    model: str,
    role: str,
) -> list[ModelPoolEntry]:
    flag = ROLES.get(role)
    if flag is None:
        raise ValueError(f"unknown role '{role}'")
    rows = await _ordered(db)
    target = next(
        (r for r in rows if r.provider == provider and r.model == model),
        None,
    )
    if target is None:
        raise ValueError(f"({provider}, {model}) not in pool")
    if getattr(target, flag):
        return rows
    for r in rows:
        setattr(r, flag, r is target)
    await db.commit()
    return await _ordered(db)


async def set_role(
    db: AsyncSession, role: str, provider: str, model: str
) -> list[ModelPoolEntry]:
    return await _set_role(db, provider, model, role)


# Convenience shims for runtime callers; one per role.
async def _get_role(db: AsyncSession, role: str) -> ModelPoolEntry | None:
    flag = ROLES[role]
    rows = await _ordered(db)
    for r in rows:
        if getattr(r, flag):
            return r
    return rows[0] if rows else None


async def get_default(db: AsyncSession) -> ModelPoolEntry | None:
    return await _get_role(db, "default")


async def get_fast(db: AsyncSession) -> ModelPoolEntry | None:
    return await _get_role(db, "fast")


async def get_dialogue(db: AsyncSession) -> ModelPoolEntry | None:
    return await _get_role(db, "dialogue")


async def get_avatar(db: AsyncSession) -> ModelPoolEntry | None:
    return await _get_role(db, "avatar")


async def get_illustration(db: AsyncSession) -> ModelPoolEntry | None:
    return await _get_role(db, "illustration")


async def get_narration(db: AsyncSession) -> ModelPoolEntry | None:
    return await _get_role(db, "narration")


# Back-compat shims: existing callers use set_default / set_fast.
async def set_default(
    db: AsyncSession, provider: str, model: str
) -> list[ModelPoolEntry]:
    return await _set_role(db, provider, model, "default")


async def set_fast(
    db: AsyncSession, provider: str, model: str
) -> list[ModelPoolEntry]:
    return await _set_role(db, provider, model, "fast")
