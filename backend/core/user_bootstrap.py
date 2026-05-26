"""Bootstrap auth users into the application database."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import AuthError, hash_invite_code, load_auth_users, verify_password
from core.config import Settings
from orm.models import ROLE_ADMIN, InviteCode, User

logger = logging.getLogger("chatrpg.user_bootstrap")


async def sync_auth_users(db: AsyncSession, settings: Settings) -> None:
    """Upsert each auth.json entry as an admin user.

    auth.json entries are always treated as admins — they're the
    bootstrap operators of the install. UI-created users default to
    "player" and get promoted only via the admin UI.
    """
    try:
        entries = load_auth_users(settings)
    except AuthError as exc:
        logger.error("auth.json invalid: %s", exc)
        return
    for entry in entries:
        user = await db.get(User, entry["id"])
        if user is None:
            db.add(
                User(
                    id=entry["id"],
                    name=entry["display_name"],
                    username=entry["username"],
                    password=entry["password"],
                    role=ROLE_ADMIN,
                )
            )
        else:
            # Refresh the persisted credentials/role from config on every
            # boot so editing auth.json takes effect immediately.
            user.name = entry["display_name"]
            user.username = entry["username"]
            user.password = entry["password"]
            user.role = ROLE_ADMIN
    await db.commit()


def _configured_invite_codes(raw: str) -> list[str]:
    return [
        code.strip()
        for code in raw.replace("\n", ",").split(",")
        if code.strip()
    ]


async def sync_registration_invites(db: AsyncSession, settings: Settings) -> None:
    """Bootstrap operator-supplied invite codes from env.

    Raw invite codes never persist; the env value can be rotated out after
    startup once the hashed row exists.
    """
    if not settings.registration_enabled:
        return

    max_uses = max(1, settings.registration_invite_max_uses)
    changed = False
    for raw_code in _configured_invite_codes(settings.registration_invite_codes):
        try:
            code_hash = hash_invite_code(raw_code)
        except AuthError:
            continue
        existing = (
            await db.execute(
                select(InviteCode).where(InviteCode.code_hash == code_hash)
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                InviteCode(
                    id=str(uuid.uuid4()),
                    code_hash=code_hash,
                    label="env bootstrap",
                    max_uses=max_uses,
                )
            )
            changed = True
        elif existing.label == "env bootstrap" and existing.max_uses != max_uses:
            existing.max_uses = max_uses
            changed = True
    if changed:
        await db.commit()


async def find_user_by_login(
    db: AsyncSession, username: str, password: str
) -> User | None:
    """Look up a user by username + password. Returns None on miss.

    Callers should treat None as "invalid credentials" — don't disclose
    whether the username exists.
    """
    stmt = select(User).where(User.username == username.strip())
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        return None
    if not verify_password(user.password, password):
        return None
    return user
