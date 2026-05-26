from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class CharacterPoolEntry(Base, TimestampMixin):
    """Reusable player-owned character card.

    A finished setup character is copied here so future rooms can import
    the card without replaying creation chat. `ruleset_*` fields are a
    snapshot label: the referenced ruleset may be renamed or deleted later.
    """

    __tablename__ = "character_pool_entries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=False, index=True
    )

    ruleset_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ruleset_title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    ruleset_short_name: Mapped[str | None] = mapped_column(String(16), nullable=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="generated")
    source_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    character: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
