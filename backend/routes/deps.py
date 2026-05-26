"""FastAPI dependency helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import AuthError, decode_token
from core.config import Settings, get_settings
from core.database import get_session_factory
from orm.models import ROLE_ADMIN, User


async def db_session() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> User:
    """Resolve the caller from a bearer token.

    The token is issued by /api/auth/login against the config-file user
    store (see core/auth.py). 401 if missing/invalid; 401 also if the
    DB row was deleted out from under the token.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        user_id = decode_token(settings, token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")
    return user


async def current_admin(user: User = Depends(current_user)) -> User:
    """403 unless the caller has the admin role."""
    if user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="admin role required")
    return user
