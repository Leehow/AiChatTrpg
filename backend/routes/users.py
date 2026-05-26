"""Admin-only user management.

The first admin is bootstrapped from auth.json on every server start
(see core/user_bootstrap.py). Additional users are created here and
default to the player role unless explicitly promoted.

Self-protection: an admin cannot delete their own account or downgrade
their own role from the API. This avoids locking the install out by
accident; emergency recovery is always possible by editing auth.json
and restarting (the bootstrap re-applies admin role on the configured
auth.json users).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import AuthError, hash_invite_code, hash_password
from core.config import Settings, get_settings
from orm.models import ROLE_ADMIN, ROLE_PLAYER, InviteCode, User
from routes.deps import current_admin, db_session
from schemas.common import OkResponse
from schemas.user import (
    InviteCodeCreateRequest,
    InviteCodeOut,
    UserCreateRequest,
    UserOut,
    UserUpdateRequest,
)

router = APIRouter(prefix="/api/users", tags=["users"])

VALID_ROLES = {ROLE_ADMIN, ROLE_PLAYER}


def _to_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        name=u.name,
        username=u.username,
        role=u.role,
        preferences=u.preferences or {},
        created_at=u.created_at,
        updated_at=u.updated_at,
    )


def _invite_to_out(invite: InviteCode) -> InviteCodeOut:
    return InviteCodeOut(
        id=invite.id,
        label=invite.label,
        max_uses=invite.max_uses,
        use_count=invite.use_count,
        remaining_uses=max(invite.max_uses - invite.use_count, 0),
        disabled=invite.disabled,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
        updated_at=invite.updated_at,
    )


def _validate_role(role: str) -> str:
    if role not in VALID_ROLES:
        raise HTTPException(
            422, f"role must be one of {sorted(VALID_ROLES)}"
        )
    return role


async def _username_taken(
    db: AsyncSession, username: str, exclude_id: str | None = None
) -> bool:
    stmt = select(User).where(User.username == username)
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return (await db.execute(stmt)).scalar_one_or_none() is not None


@router.get("", response_model=list[UserOut])
async def list_users(
    _admin: User = Depends(current_admin),
    db: AsyncSession = Depends(db_session),
) -> list[UserOut]:
    rows = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    return [_to_out(u) for u in rows]


@router.post("", response_model=UserOut)
async def create_user(
    body: UserCreateRequest,
    settings: Settings = Depends(get_settings),
    _admin: User = Depends(current_admin),
    db: AsyncSession = Depends(db_session),
) -> UserOut:
    role = _validate_role(body.role)
    username = body.username.strip()
    if not username:
        raise HTTPException(422, "username required")
    if await _username_taken(db, username):
        raise HTTPException(409, "username already exists")
    user = User(
        id=str(uuid.uuid4()),
        username=username,
        password=hash_password(
            body.password,
            iterations=settings.password_hash_iterations,
        ),
        name=(body.name or username).strip(),
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _to_out(user)


@router.put("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    settings: Settings = Depends(get_settings),
    admin: User = Depends(current_admin),
    db: AsyncSession = Depends(db_session),
) -> UserOut:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "user not found")
    if body.role is not None:
        new_role = _validate_role(body.role)
        if user.id == admin.id and new_role != ROLE_ADMIN:
            raise HTTPException(400, "cannot downgrade your own admin role")
        user.role = new_role
    if body.name is not None:
        user.name = body.name.strip() or user.name
    if body.password is not None:
        user.password = hash_password(
            body.password,
            iterations=settings.password_hash_iterations,
        )
    await db.commit()
    await db.refresh(user)
    return _to_out(user)


@router.delete("/{user_id}", response_model=OkResponse)
async def delete_user(
    user_id: str,
    admin: User = Depends(current_admin),
    db: AsyncSession = Depends(db_session),
) -> OkResponse:
    if user_id == admin.id:
        raise HTTPException(400, "cannot delete your own account")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "user not found")
    await db.delete(user)
    await db.commit()
    return OkResponse()


@router.get("/invites", response_model=list[InviteCodeOut])
async def list_invites(
    _admin: User = Depends(current_admin),
    db: AsyncSession = Depends(db_session),
) -> list[InviteCodeOut]:
    rows = (
        await db.execute(select(InviteCode).order_by(InviteCode.created_at.desc()))
    ).scalars().all()
    return [_invite_to_out(row) for row in rows]


@router.post("/invites", response_model=InviteCodeOut)
async def create_invite(
    body: InviteCodeCreateRequest,
    admin: User = Depends(current_admin),
    db: AsyncSession = Depends(db_session),
) -> InviteCodeOut:
    try:
        code_hash = hash_invite_code(body.code)
    except AuthError as exc:
        raise HTTPException(422, str(exc)) from exc
    invite = InviteCode(
        id=str(uuid.uuid4()),
        code_hash=code_hash,
        label=(body.label or "").strip(),
        max_uses=body.max_uses,
        expires_at=body.expires_at,
        created_by_user_id=admin.id,
    )
    db.add(invite)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "invite code already exists") from exc
    await db.refresh(invite)
    return _invite_to_out(invite)


@router.post("/invites/{invite_id}/disable", response_model=InviteCodeOut)
async def disable_invite(
    invite_id: str,
    _admin: User = Depends(current_admin),
    db: AsyncSession = Depends(db_session),
) -> InviteCodeOut:
    invite = await db.get(InviteCode, invite_id)
    if invite is None:
        raise HTTPException(404, "invite not found")
    invite.disabled = True
    await db.commit()
    await db.refresh(invite)
    return _invite_to_out(invite)
