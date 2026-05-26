"""Runtime memory and turn-trace tables.

These tables are the durable counterpart to the in-memory scaffold under
``services.trpg_memory`` and ``services.trpg_runtime``. Existing
``sessions.memory_state`` JSON remains a compatibility projection; the rows
here carry source, visibility, lifecycle, and idempotency metadata so memory
can become auditable without breaking the current prompt/UI paths.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class TRPGMemoryItem(Base, TimestampMixin):
    __tablename__ = "trpg_memory_items"
    __table_args__ = (
        Index("ix_trpg_memory_items_session_visibility", "session_id", "visibility", "status"),
        Index("ix_trpg_memory_items_session_owner", "session_id", "owner_id", "status"),
        Index("ix_trpg_memory_items_session_kind", "session_id", "kind", "status"),
        Index("ux_trpg_memory_items_session_idempotency", "session_id", "idempotency_key", unique=True),
    )

    memory_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    campaign_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    visibility: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    owner_id: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    subject_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_turn_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_event_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_quotes_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    confirmed_state_change_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    identity_scope: Mapped[str] = mapped_column(String(40), nullable=False, default="durable_fact")
    reinforcement_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    salience: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    truth_status: Mapped[str] = mapped_column(String(40), nullable=False, default="unverified")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    pin_policy: Mapped[str] = mapped_column(String(48), nullable=False, default="dynamic_retrieval_only")
    supersedes_memory_id: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    superseded_by: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    invalidated_by_turn_id: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    correction_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    idempotency_key: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    created_at_turn: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    last_reinforced_turn: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    tags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class TRPGMemoryRevision(Base, TimestampMixin):
    __tablename__ = "trpg_memory_revisions"
    __table_args__ = (
        Index("ix_trpg_memory_revisions_memory", "memory_id", "created_at"),
        Index("ix_trpg_memory_revisions_session_turn", "session_id", "turn_id"),
    )

    id: Mapped[str] = mapped_column(String(96), primary_key=True, default=lambda: str(uuid.uuid4()))
    memory_id: Mapped[str] = mapped_column(
        String(96),
        ForeignKey("trpg_memory_items.memory_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    campaign_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    turn_id: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    operation: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    before_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    after_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class TRPGWorldStateSnapshot(Base, TimestampMixin):
    __tablename__ = "trpg_world_state_snapshots"
    __table_args__ = (
        Index("ix_trpg_world_state_snapshots_session", "session_id", "version"),
    )

    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    campaign_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class TRPGStateChange(Base, TimestampMixin):
    __tablename__ = "trpg_state_changes"
    __table_args__ = (
        Index("ix_trpg_state_changes_session_turn", "session_id", "turn_id"),
        Index("ix_trpg_state_changes_session_target", "session_id", "target_id"),
        Index("ux_trpg_state_changes_session_change", "session_id", "change_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(96), primary_key=True, default=lambda: str(uuid.uuid4()))
    change_id: Mapped[str] = mapped_column(String(96), nullable=False, default="", index=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    campaign_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    turn_id: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    change_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    target_id: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    operation: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    path_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    previous_value_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    new_value_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    actor_id: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    visibility: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requires_rule_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rule_check_id: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    tags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class TRPGTurnTrace(Base, TimestampMixin):
    __tablename__ = "trpg_turn_traces"
    __table_args__ = (
        Index("ix_trpg_turn_traces_session_created", "session_id", "created_at"),
        Index("ux_trpg_turn_traces_session_turn", "session_id", "turn_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(96), primary_key=True, default=lambda: str(uuid.uuid4()))
    turn_id: Mapped[str] = mapped_column(String(96), nullable=False, default="", index=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    campaign_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    player_input: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context_cache_key: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    context_prefix_hash: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    retrieved_context_block_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    visibility_signature: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    model_raw_output_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    parsed_contract_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    state_change_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    memory_proposal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    committed_memory_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    rejected_memory_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audit_warnings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    cache_metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
