"""Login / current-user endpoints.

Login goes against the DB users table. auth.json bootstraps the admin
account on every startup (see core/user_bootstrap.py); after that,
admins manage users through /api/users (see routes/users.py).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from core.auth import AuthError, hash_invite_code, hash_password, issue_token
from core.config import Settings, get_settings
from core.user_bootstrap import find_user_by_login
from orm.models import ROLE_PLAYER, InviteCode, User
from orm.models.base import utcnow
from routes.deps import current_user, db_session
from schemas.auth import (
    LoginRequest,
    LoginResponse,
    PreferencesUpdateRequest,
    RegisterRequest,
    RegistrationStatusResponse,
    UserInfo,
)
from schemas.common import OkResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_info(u: User) -> UserInfo:
    return UserInfo(
        id=u.id,
        name=u.name,
        username=u.username,
        role=u.role,
        preferences=u.preferences or {},
    )


def _invite_expired(invite: InviteCode) -> bool:
    if invite.expires_at is None:
        return False
    expires_at = invite.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=utcnow().tzinfo)
    return expires_at <= utcnow()


async def _consume_invite(
    db: AsyncSession, invite_code: str | None
) -> None:
    if not invite_code:
        raise HTTPException(422, "invite code required")
    try:
        code_hash = hash_invite_code(invite_code)
    except AuthError as exc:
        raise HTTPException(422, str(exc)) from exc
    invite = (
        await db.execute(
            select(InviteCode)
            .where(InviteCode.code_hash == code_hash)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if (
        invite is None
        or invite.disabled
        or _invite_expired(invite)
        or invite.use_count >= invite.max_uses
    ):
        raise HTTPException(403, "invalid invite code")
    invite.use_count += 1


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(db_session),
) -> LoginResponse:
    user = await find_user_by_login(db, body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = issue_token(settings, user.id)
    return LoginResponse(token=token, user=_user_info(user))


@router.get("/registration-status", response_model=RegistrationStatusResponse)
async def registration_status(
    settings: Settings = Depends(get_settings),
) -> RegistrationStatusResponse:
    return RegistrationStatusResponse(
        enabled=settings.registration_enabled,
        invite_required=settings.registration_invite_required,
    )


@router.post("/register", response_model=LoginResponse)
async def register(
    body: RegisterRequest,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(db_session),
) -> LoginResponse:
    if not settings.registration_enabled:
        raise HTTPException(403, "registration disabled")

    username = body.username.strip()
    existing = (
        await db.execute(select(User.id).where(User.username == username))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, "username already exists")

    if settings.registration_invite_required:
        await _consume_invite(db, body.invite_code)

    user = User(
        id=str(uuid.uuid4()),
        username=username,
        password=hash_password(
            body.password,
            iterations=settings.password_hash_iterations,
        ),
        name=body.name or username,
        role=ROLE_PLAYER,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "username already exists") from exc
    await db.refresh(user)
    token = issue_token(settings, user.id)
    return LoginResponse(token=token, user=_user_info(user))


@router.get("/me", response_model=UserInfo)
async def me(user: User = Depends(current_user)) -> UserInfo:
    return _user_info(user)


@router.post("/preferences", response_model=UserInfo)
async def update_preferences(
    body: PreferencesUpdateRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(db_session),
) -> UserInfo:
    """Partial-merge update of the caller's preferences blob.
    Keys with value `None` are deleted; other keys overwrite. Use POST
    not PATCH because some CDNs block PATCH (see CLAUDE.md)."""
    merged = dict(user.preferences or {})
    for key, value in body.patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    user.preferences = merged
    flag_modified(user, "preferences")
    await db.commit()
    await db.refresh(user)
    return _user_info(user)


@router.post("/logout", response_model=OkResponse)
async def logout() -> OkResponse:
    """Stateless logout — the client just drops the token. This endpoint
    exists so SPAs can fire-and-forget on sign-out without a 404."""
    return OkResponse()
