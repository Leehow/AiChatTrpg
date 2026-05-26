"""Authentication helpers: load config-backed credentials, sign/verify JWTs.

The credential store is a JSON file at the path given by Settings.auth_file
(default: repo-root/auth.json). Each entry is:

    {"id": "<user_id>", "username": "...", "password": "...",
     "display_name": "..."}

auth.json remains a local bootstrap path for open-source installs. DB-created
users use PBKDF2-SHA256 hashes so hosted test deployments never store public
account passwords in plaintext.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jwt

from .config import Settings

logger = logging.getLogger("chatrpg.auth")


class AuthError(Exception):
    """Raised when credentials are invalid or a token is malformed/expired."""


PASSWORD_HASH_SCHEME = "pbkdf2_sha256"


def hash_password(password: str, *, iterations: int) -> str:
    """Return an encoded PBKDF2-SHA256 password hash.

    This keeps the open-source install dependency-light while avoiding
    plaintext storage for DB-created public-test users. Legacy auth.json users
    may still be stored as plaintext and are verified by `verify_password`.
    """
    if not password:
        raise AuthError("password required")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{PASSWORD_HASH_SCHEME}${iterations}${salt_b64}${digest_b64}"


def _decode_b64(value: str) -> bytes:
    padded = value + ("=" * (-len(value) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def verify_password(stored_password: str, candidate: str) -> bool:
    """Verify either a PBKDF2 hash or a legacy plaintext password."""
    if stored_password.startswith(f"{PASSWORD_HASH_SCHEME}$"):
        try:
            _, raw_iterations, raw_salt, raw_digest = stored_password.split("$", 3)
            iterations = int(raw_iterations)
            salt = _decode_b64(raw_salt)
            expected = _decode_b64(raw_digest)
        except Exception:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", candidate.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(expected, actual)
    return hmac.compare_digest(stored_password, candidate)


def normalize_invite_code(code: str) -> str:
    return code.strip().upper()


def hash_invite_code(code: str) -> str:
    normalized = normalize_invite_code(code)
    if not normalized:
        raise AuthError("invite code required")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_auth_users(settings: Settings) -> list[dict[str, str]]:
    """Read the credential file. Returns an empty list if the file is missing
    so that a fresh checkout doesn't crash on startup — but login will then
    fail until the operator copies auth.example.json to auth.json."""
    path = Path(settings.auth_file)
    if not path.exists():
        logger.warning(
            "auth_file %s missing — no users will be able to log in until it exists",
            path,
        )
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AuthError(f"auth_file is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise AuthError("auth_file must be a JSON array of user entries")
    out: list[dict[str, str]] = []
    for entry in data:
        if not isinstance(entry, dict):
            raise AuthError("each auth_file entry must be an object")
        for field in ("id", "username", "password"):
            if not entry.get(field):
                raise AuthError(f"auth entry missing required field {field!r}")
        out.append(
            {
                "id": str(entry["id"]),
                "username": str(entry["username"]),
                "password": str(entry["password"]),
                "display_name": str(entry.get("display_name") or entry["username"]),
            }
        )
    return out


def issue_token(settings: Settings, user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_ttl_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(settings: Settings, token: str) -> str:
    """Verify token signature/expiry and return the user_id (sub claim)."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("invalid token") from exc
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise AuthError("token missing subject")
    return sub
