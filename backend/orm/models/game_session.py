"""ORM model for a TRPG game session (a 'room').

A session is one ongoing TRPG run: it pins a ruleset, holds the player
character card, current module/scene state, structured memory, and a
rolling narrative summary of older messages. Chat messages live in their
own table (FK back to session.id) so we can stream and paginate them
independently of the session row.

Single-user mode today, but the schema is multi-user from day one
(`user_id` FK) so commercial forks can flip on multi-tenant by changing
auth — no migration needed.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, utcnow


def _empty_character() -> dict[str, Any]:
    return {}


def _empty_module_state() -> dict[str, Any]:
    return {
        "tag": "Freeform",
        "title": "—",
        "scene": "—",
        "desc": "(no module loaded)",
        "progress": [False, False, False, False, False],
    }


def _empty_memory_state() -> dict[str, Any]:
    return {"scenes": [], "npcs": [], "plot_threads": [], "world_facts": []}


def _empty_setup_state() -> dict[str, Any]:
    # Lives on every row, including completed ones — the UI checks `completed`
    # to decide whether to land in setup or jump straight into the game.
    return {
        "step": 0,
        "ruleset_id": None,
        "module_id": None,
        "module_title": None,
        "completed": False,
    }


class GameSession(Base, TimestampMixin):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id"), nullable=False, index=True
    )
    # Nullable so a freshly-created draft (no ruleset chosen yet) can still
    # exist as a row. Becomes non-null once setup finishes.
    ruleset_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("rulesets.id", ondelete="SET NULL"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # False once the user manually edits the title — disables the auto
    # `[coc]<module>` rename that runs as setup progresses.
    title_auto: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_active_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Resumable setup-wizard progress.
    setup_state: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=_empty_setup_state
    )

    # Player character card. Free-form JSON shaped by the chosen ruleset's
    # character_sheet template.
    character: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=_empty_character
    )

    # Current module/scene state shown in the right-rail Module panel.
    module_state: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=_empty_module_state
    )

    # Structured game memory: scenes / NPCs / plot threads / world facts.
    memory_state: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=_empty_memory_state
    )

    # Rolling LLM-compressed narrative for messages that have aged out of
    # the live context window.
    narrative_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_summarized_msg_count: Mapped[int] = mapped_column(
        default=0, nullable=False
    )

    # Recent dice rolls: [{expression, result, detail, reason, time}].
    dice_history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )

    # Style controls.
    narrative_style: Mapped[str] = mapped_column(
        String(32), default="second_person", nullable=False
    )
    difficulty_style: Mapped[str] = mapped_column(
        String(32), default="auto", nullable=False
    )

    messages = relationship(
        "Message",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
