"""ORM model for chat messages within a TRPG session.

Tool markers (e.g. [ROLL], [UPDATE_MEMORY]) live inline in `content` so
we don't need a parallel events table. Anything the postprocess pipeline
extracts (parsed dice payloads, applied state diffs, etc.) goes into
`metadata_json` next to the message.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class Message(Base, TimestampMixin):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_session_created", "session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # role: "user" | "gm" | "system" | "dice"
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON, nullable=True
    )

    session = relationship("GameSession", back_populates="messages")
