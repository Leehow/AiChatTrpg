from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SetupState(BaseModel):
    """Resumable setup-wizard progress carried by every session row."""
    step: int = 0
    ruleset_id: str | None = None
    module_id: str | None = None
    module_title: str | None = None
    start_unit_index: int | None = None
    start_unit_id: str | None = None
    start_unit_title: str | None = None
    completed: bool = False


class SessionSummary(BaseModel):
    """Lean shape used by the rooms panel listing."""
    id: str
    title: str
    # Null for drafts that haven't picked a ruleset yet.
    ruleset_id: str | None = None
    ruleset_title: str = ""
    ruleset_short_name: str | None = None
    archived: bool
    title_auto: bool = True
    setup_state: SetupState = Field(default_factory=SetupState)
    last_active_at: datetime
    created_at: datetime
    updated_at: datetime


class SessionDetail(SessionSummary):
    character: dict[str, Any]
    module_state: dict[str, Any]
    memory_state: dict[str, Any]
    narrative_summary: str
    last_summarized_msg_count: int
    dice_history: list[dict[str, Any]]
    narrative_style: str
    difficulty_style: str


class SessionCreateRequest(BaseModel):
    """Body for `POST /api/sessions`. All fields optional — an empty
    body creates a blank draft that the setup wizard will fill in."""
    ruleset_id: str | None = None
    title: str | None = None
    character: dict[str, Any] | None = None


class SessionUpdateRequest(BaseModel):
    """All fields optional — only provided fields are touched."""
    title: str | None = None
    title_auto: bool | None = None
    ruleset_id: str | None = None
    setup_state: SetupState | None = None
    archived: bool | None = None
    character: dict[str, Any] | None = None
    module_state: dict[str, Any] | None = None
    memory_state: dict[str, Any] | None = None
    narrative_summary: str | None = None
    last_summarized_msg_count: int | None = None
    dice_history: list[dict[str, Any]] | None = None
    narrative_style: str | None = None
    difficulty_style: str | None = None


class CharacterStartRequest(BaseModel):
    language: str | None = None


class CharacterChatRequest(BaseModel):
    message: str
    language: str | None = None
    # IC-only: when set to "resolve" the chat-stream endpoint treats this
    # turn as a "投出" click on a pending check — skips persisting a user
    # message, resolves the selected latest-GM `[pending_check ...]`
    # placeholder, then runs a continuation IC turn so the GM narrates the
    # consequence. If `roll_result` is present, it is the already-rolled
    # client-side 3D dice value used for that pending check.
    intent: str | None = None
    pending_check_id: str | None = None
    roll_result: Any | None = None


class ForceInGameTimeRequest(BaseModel):
    """Operator-controlled override of the in-game clock. The GM normally
    advances time via `[TAKE_TIME]` markers; this endpoint exists so a player
    or admin can correct drift, jump to a story-relevant moment, or undo a
    bad time-leap. Frontend confirms intent via a checkbox before sending."""
    day: int
    clock: str  # HH:MM, 24-hour
    date: str | None = None


class ForceInGameTimeResponse(BaseModel):
    day: int
    clock: str
    period: str
    date: str | None = None
    elapsed_minutes: int = 0


class AdvanceInGameTimeRequest(BaseModel):
    """Player-triggered relative in-game time advance. Frontend uses this for
    quick deltas next to the scene clock; the absolute setter remains the
    drift-correction modal."""
    minutes: int
    reason: str | None = None


class PlayerNoteOut(BaseModel):
    """One row in ``memory_state.player_notes[]`` as surfaced to clients.

    Legacy `[ADD_NOTE]` rows persisted via ``trpg_ic_markers.apply_chatrpg_markers``
    carry ``id``, ``content``, ``tags``, ``created_at`` but no ``source``;
    those are lazily normalized to ``source="gm"`` on read.
    """
    id: str
    content: str
    tags: list[str] = Field(default_factory=list)
    source: str = "player"
    created_at: str | None = None
    updated_at: str | None = None


class PlayerNotesListResponse(BaseModel):
    notes: list[PlayerNoteOut] = Field(default_factory=list)


class PlayerNoteCreateRequest(BaseModel):
    content: str
    tags: list[str] | None = None


class PlayerNoteUpdateRequest(BaseModel):
    content: str | None = None
    tags: list[str] | None = None


class PlayerNoteWriteResponse(BaseModel):
    status: str = "ok"
    note: PlayerNoteOut


class PlayerNoteDeleteResponse(BaseModel):
    status: str = "ok"


class CharacterGenerateRequest(BaseModel):
    mode: str = "from_chat"
    seed: str | None = None
    language: str | None = None


class CharacterImportRequest(BaseModel):
    character: dict[str, Any]
    source: str = "uploaded"
    pool_id: str | None = None


class AdventureStartUnit(BaseModel):
    index: int = 0
    unit_id: str | None = None
    title: str
    kind: str = "chapter"
    summary: str = ""
    line_start: int = 0
    line_end: int = 0
    section_indexes: list[int] = Field(default_factory=list)


class AdventureStartOptions(BaseModel):
    has_module: bool = False
    module_id: str | None = None
    module_title: str = ""
    semantic_status: str = ""
    semantic_error: str = ""
    anchor_type: str = "freeform"
    progression: str = "freeform"
    selection_rule: str = ""
    needs_selection: bool = False
    units: list[AdventureStartUnit] = Field(default_factory=list)


class AdventureStartRequest(BaseModel):
    module_id: str | None = None
    unit_index: int | None = None
    unit_id: str | None = None


class CharacterDraftResponse(BaseModel):
    messages: list[dict[str, Any]] = Field(default_factory=list)
    character: dict[str, Any] | None = None
    ready: bool = False
    assistant: str | None = None
    pool_id: str | None = None


class MessageOut(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    # `metadata_json` is accepted as an input alias for ergonomic construction
    # from the ORM row (`MessageOut(metadata_json=m.metadata_json, ...)`), but
    # the JSON field name on the wire stays `metadata` — that's what the
    # frontend `MessageDTO` expects.
    metadata: dict[str, Any] | None = Field(
        default=None, validation_alias="metadata_json",
    )
    created_at: datetime

    model_config = {"populate_by_name": True}


class MessageListResponse(BaseModel):
    items: list[MessageOut]
    total: int
    # True if there exist messages strictly older than the oldest item in
    # `items`. Frontend uses this to know whether more pages can be fetched
    # via the `before_id` cursor.
    has_more: bool = False


class PostprocessStep(BaseModel):
    """One event in a message's post-processing timeline (running → done
    pair, or one-shot ``done``). Mirrors the dict shape persisted under
    ``messages.metadata_json["postprocess_steps"]``."""
    name: str
    status: str  # "running" | "done"
    duration_ms: int = 0
    detail: str = ""
    ts: str = ""


class PostprocessStepsResponse(BaseModel):
    steps: list[PostprocessStep] = Field(default_factory=list)
    # True once a ``phase3_complete`` event has been recorded; the
    # frontend stops polling on this flag.
    done: bool = False


class CheckLogOut(BaseModel):
    id: str
    session_id: str
    message_id: str | None = None
    actor_id: str = ""
    procedure_id: str = ""
    engine: str = ""
    skill: str = ""
    seed: str = ""
    source: str = ""
    request: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    roll_trace: dict[str, Any] = Field(default_factory=dict)
    trace: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime


class CheckLogListResponse(BaseModel):
    items: list[CheckLogOut]
    total: int
    has_more: bool = False


class TurnTraceOut(BaseModel):
    id: str
    turn_id: str
    session_id: str
    campaign_id: str
    player_input: str = ""
    context_cache_key: str = ""
    context_prefix_hash: str = ""
    retrieved_context_block_ids: list[str] = Field(default_factory=list)
    visibility_signature: str = ""
    model_raw_output: dict[str, Any] = Field(default_factory=dict)
    parsed_contract_summary: dict[str, Any] = Field(default_factory=dict)
    state_change_ids: list[str] = Field(default_factory=list)
    memory_proposal_count: int = 0
    committed_memory_ids: list[str] = Field(default_factory=list)
    rejected_memory_count: int = 0
    audit_warnings: list[dict[str, Any]] = Field(default_factory=list)
    cache_metrics: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class TurnTraceListResponse(BaseModel):
    items: list[TurnTraceOut]
    total: int
    has_more: bool = False


class PublicRelationshipOut(BaseModel):
    npc_id: str
    summary: str
    confidence: float = 0.0
    known_reasons: list[str] = Field(default_factory=list)


class PublicClueOut(BaseModel):
    clue_id: str | None = None
    title: str
    status: str
    points_to: list[str] = Field(default_factory=list)
    summary: str = ""


class PublicMemoryViewOut(BaseModel):
    relationships: list[PublicRelationshipOut] = Field(default_factory=list)
    clues: list[PublicClueOut] = Field(default_factory=list)
    open_threads: list[str] = Field(default_factory=list)
    remembered_facts: list[str] = Field(default_factory=list)


class NpcRuntimeDebugOut(BaseModel):
    counts: dict[str, int] = Field(default_factory=dict)
    planner_latest: dict[str, Any] = Field(default_factory=dict)
    planner_runs: list[dict[str, Any]] = Field(default_factory=list)
    action_board: dict[str, Any] = Field(default_factory=dict)
    action_cards: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    sample_memories: list[dict[str, Any]] = Field(default_factory=list)


class MessageCreateRequest(BaseModel):
    role: str
    content: str
    metadata: dict[str, Any] | None = None


class ContextSnapshotBP1(BaseModel):
    """Stable context: ruleset + module text injected into the LLM prompt."""

    ruleset_title: str
    ruleset_world_mode: str
    core_rules: str
    sheet_template: str
    sheet_guide: str
    scene_guide: str = ""
    module_title: str | None = None
    module_text: str = ""


class ContextSnapshotBP2(BaseModel):
    """Semi-stable snapshot derived from module_state, memory_state, and
    narrative_summary.

    The element shape inside the *_facts / threads / scenes / npcs lists is
    intentionally permissive: the GM auto-memory pass can write either
    structured dicts (e.g. an NPC record) or free-form strings (e.g. a
    one-sentence world fact). Locking these to `list[dict]` would 500 on
    any session whose memory contains a plain string.
    """

    module_state: dict[str, Any] = Field(default_factory=dict)
    scenes: list[Any] = Field(default_factory=list)
    npcs: list[Any] = Field(default_factory=list)
    plot_threads: list[Any] = Field(default_factory=list)
    world_facts: list[Any] = Field(default_factory=list)
    narrative_summary: str = ""


class ContextSnapshotBP3(BaseModel):
    """Per-turn live state: setup chat + character draft + dice."""

    chat: list[dict[str, Any]] = Field(default_factory=list)
    pc: dict[str, Any] | None = None
    draft_card: dict[str, Any] | None = None
    ready: bool = False
    dice_history: list[dict[str, Any]] = Field(default_factory=list)


class ContextSnapshot(BaseModel):
    bp1: ContextSnapshotBP1
    bp2: ContextSnapshotBP2
    bp3: ContextSnapshotBP3
