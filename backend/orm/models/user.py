from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


# Roles: "admin" can open the debug panel and manage users; "player"
# is a regular game participant.
ROLE_ADMIN = "admin"
ROLE_PLAYER = "player"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="Player")
    # username is the login handle. Unique across the system.
    username: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    # auth.json bootstrap users may still be plaintext for local installs;
    # DB-created users are stored as encoded password hashes.
    password: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=ROLE_PLAYER)
    # Free-form per-user preferences. Known keys:
    #   last_active_session_id: str | None — session the UI auto-resumes after refresh.
    #   music_settings: dict — music player volume / loop / shuffle / style.
    #   character_ui_fold: dict[system_id -> dict[node_id -> "open"|"closed"]]
    #     — per-ruleset fold state for character-card sections.
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
