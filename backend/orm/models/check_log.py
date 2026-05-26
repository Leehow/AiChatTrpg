"""Persistent CHECK execution log.

`sessions.dice_history` remains the compact compatibility mirror used by
existing prompts and panels. This table stores the full replay payload for
debugging, audit, and future filtering.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class CheckLog(Base, TimestampMixin):
    __tablename__ = "check_logs"
    __table_args__ = (
        Index("ix_check_logs_session_created", "session_id", "created_at"),
        Index("ix_check_logs_session_procedure", "session_id", "procedure_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_id: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    procedure_id: Mapped[str] = mapped_column(String(160), nullable=False, default="", index=True)
    engine: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    skill: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    seed: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    roll_trace_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    trace_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
