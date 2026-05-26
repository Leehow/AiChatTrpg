from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class NPCRuntimeProfile(Base, TimestampMixin):
    """Runtime V2 profile snapshot for one NPC in one session."""

    __tablename__ = "npc_runtime_profiles"
    __table_args__ = (
        Index("ix_npc_runtime_profiles_session_npc", "session_id", "npc_id"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    npc_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    tier: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class NPCRuntimeState(Base, TimestampMixin):
    """Runtime V2 mutable NPC state snapshot."""

    __tablename__ = "npc_runtime_states"
    __table_args__ = (
        Index("ix_npc_runtime_states_session_npc", "session_id", "npc_id"),
        Index("ix_npc_runtime_states_session_scene", "session_id", "scene_id"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    npc_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    scene_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class NPCRuntimeRelationship(Base, TimestampMixin):
    """Runtime V2 relationship vector from one NPC to a target actor."""

    __tablename__ = "npc_runtime_relationships"
    __table_args__ = (
        Index(
            "ix_npc_runtime_relationships_session_npc",
            "session_id",
            "npc_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(240), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    npc_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    relationship_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class NPCRuntimeMemory(Base, TimestampMixin):
    """Concise event memory owned by an NPC."""

    __tablename__ = "npc_runtime_memories"
    __table_args__ = (
        Index("ix_npc_runtime_memories_session_npc", "session_id", "npc_id"),
    )

    memory_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    npc_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False, default="episodic")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    source_event_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    tags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    memory_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class NPCRuntimeActionCard(Base, TimestampMixin):
    """Persisted ActionBoard intent card."""

    __tablename__ = "npc_runtime_action_cards"
    __table_args__ = (
        Index("ix_npc_runtime_action_cards_session_scene", "session_id", "scene_id"),
        Index("ix_npc_runtime_action_cards_session_npc", "session_id", "npc_id"),
    )

    card_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    npc_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    based_on_turn_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_until_turn: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    card_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class NPCRuntimeEvent(Base, TimestampMixin):
    """Canonical structured event consumed by NPC Runtime V2."""

    __tablename__ = "npc_runtime_events"
    __table_args__ = (
        Index("ix_npc_runtime_events_session_turn", "session_id", "turn_id"),
        Index("ix_npc_runtime_events_session_scene", "session_id", "scene_id"),
    )

    event_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    turn_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    actor_id: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    target_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    visibility_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    event_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
