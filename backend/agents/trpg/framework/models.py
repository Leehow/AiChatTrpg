"""Pure dataclasses — the framework's I/O contract.

No fastapi / sqlalchemy / project-specific imports here. Anything that wants
to call into the framework hands it dataclass values; anything the framework
returns is a dataclass too. Persistence, transport, and side effects all
happen at the boundary via the adapter Protocols in `adapters/protocols.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:  # pragma: no cover - typing-only imports
    from .adapters.protocols import (
        Clock,
        LlmAdapter,
        MultimediaAdapter,
        RetrievalAdapter,
        RulesetAdapter,
    )


MessageRole = Literal["user", "gm", "system", "dice"]
MessagePhase = Literal["guide", "ic", "break"]


@dataclass
class Message:
    """A single chat-history entry. The framework treats `chat_history` as a
    single unified timeline regardless of phase — `phase` is just a label so
    adapters can render or filter."""

    role: MessageRole
    content: str
    phase: MessagePhase
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    thinking_steps: list[str] = field(default_factory=list)


@dataclass
class PromptMessage:
    """One message ready to feed an LLM. Distinct from Message: this has no
    phase, no timestamps, no thinking steps — just role + content."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class LayeredPrompt:
    """Stability-graded prompt for cache-aware providers.

    The framework's BP1/BP2/BP3 split projects onto three text layers:
      stable_prefix    — BP1: ruleset, scene guide, parameter families,
                          module text; never changes between turns.
      semi_stable_context — BP2: memory snapshot (narrative summary, scenes,
                              plot threads, world facts, active chapter);
                              changes only when memory is updated.
      variable_suffix  — BP3: PC + active NPCs + inventory + per-turn extras
                          (time, dice pool, RAG hits, today's events,
                          corrections); changes every turn.

    Each provider's adapter decides where to put each layer (system blocks
    with cache_control for Claude; system + user-message pairs for OpenAI-
    compatible clients; systemInstruction + user prefix for Gemini)."""

    stable_prefix: str = ""
    semi_stable_context: str = ""
    variable_suffix: str = ""
    history: list[PromptMessage] = field(default_factory=list)
    user_message: str = ""


@dataclass
class CharacterTemplate:
    """The shape of a character card for a given ruleset."""

    fields: list[dict[str, Any]] = field(default_factory=list)
    raw_text: str = ""


@dataclass
class StableText:
    """The stable BP1 payload a RulesetAdapter exposes to the framework. Each
    side fills it differently (chatlab from distilled session fields, chatrpg
    from parsed_v6 directly) but the framework only sees this shape."""

    resident_prompt: str = ""
    scene_guide: str = ""
    chargen_pack: str = ""
    parameter_families: str = ""
    core_rules_excerpt: str = ""


@dataclass
class RulesetData:
    """A ruleset row, flattened. Adapters slice this into the bits they need."""

    id: str
    book_title: str
    world_mode: str
    parsed_v6: dict[str, Any] = field(default_factory=dict)
    # Optional: distilled fields chatlab populates ahead of time. NoOp on chatrpg.
    resident_prompt: str = ""
    scene_guide: str = ""
    character_creation_pack: str = ""


@dataclass
class ModuleData:
    """A parsed module (adventure)."""

    id: str
    title: str
    markdown: str
    sections: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SessionState:
    """A flat snapshot of the GameSession ORM row. Each project has its own
    ORM ↔ SessionState converter; the framework only ever sees this shape.

    Pre-distilled fields (resident_prompt / scene_guide / character_creation_pack
    / character_build_rules / character_template) are populated by chatlab where
    they exist on the GameSession row. chatrpg leaves them empty and lets its
    RulesetAdapter slice parsed_v6 directly."""

    id: str
    user_id: str
    game_started: bool = False
    in_break: bool = False
    character_ready: bool = False
    # `characters` is the chatlab convention: {"pc": dict, "npcs": list[dict]}.
    # chatrpg adapter wraps single character into this same shape.
    characters: dict[str, Any] = field(default_factory=dict)
    module_state: dict[str, Any] = field(default_factory=dict)
    memory_state: dict[str, Any] = field(default_factory=dict)
    setup_state: dict[str, Any] = field(default_factory=dict)
    chat_history: list[Message] = field(default_factory=list)
    dice_history: list[dict[str, Any]] = field(default_factory=list)
    dice_pool: dict[str, list[int]] = field(default_factory=dict)
    narrative_summary: str = ""
    last_summarized_msg_count: int = 0
    adventure_start_msg_count: int = 0
    player_notes: list[dict[str, Any]] = field(default_factory=list)
    # Pre-distilled context fragments. chatlab populates these from session row;
    # chatrpg leaves them empty and slices parsed_v6 directly inside its adapter.
    resident_prompt: str = ""
    scene_guide: str = ""
    character_creation_pack: str = ""
    character_build_rules: str = ""
    character_template: dict[str, Any] | None = None


@dataclass
class ModelConfig:
    provider: str
    model: str
    temperature: float = 0.7
    api_key: str = ""
    base_url: str = ""


@dataclass
class FeatureFlags:
    enable_retrieval: bool = True
    enable_scene: bool = True
    enable_dice_pool: bool = True
    enable_memory_compression: bool = True
    enable_multimedia: bool = True


@dataclass
class TurnInputs:
    session_state: SessionState
    ruleset: RulesetData
    module: ModuleData | None
    user_message: str | None
    model: ModelConfig
    mode_hint: Literal["auto", "guide", "break", "ic"] = "auto"
    flags: FeatureFlags = field(default_factory=FeatureFlags)
    # Pre-computed IC state. Required for IC / BREAK modes; ignored in GUIDE.
    # GUIDE callers can leave this None (default) and the framework supplies
    # an empty IcContext internally if needed.
    ic_context: "IcContext | None" = None


@dataclass
class IcContext:
    """Per-turn IC state computed by the caller (chatlab's phase_preprocess
    runs NpcStore / scene_runtime / time_tracker / dice_pool / etc. before
    invoking the framework, then hands the result here).

    Framework treats this as opaque pre-computed data — it only renders.
    chatrpg, which has no IC pipeline today, will pass an empty IcContext
    until it grows one."""

    # Active NPC dicts, post scene_runtime + npc_store filtering. Each entry
    # mirrors chatlab npc dict shape (name / key / stats / actions / etc.).
    active_npcs: list[dict[str, Any]] = field(default_factory=list)
    # Module navigation: which chapter is currently in scope.
    module_chapter_name: str = ""
    module_chapter_text: str = ""
    # Scene + time formatting.
    scene_key: str = ""
    time_context: str = ""
    # Pre-rolled dice pool summary, e.g. "d100x12, d6x8".
    dice_pool_summary: str = ""
    # Today's events / GM corrections / player tendencies / narrative variation
    # — chatlab IC pipeline tracks these as advisory blocks for the GM prompt.
    today_events: list[dict[str, Any]] = field(default_factory=list)
    gm_corrections: list[dict[str, Any]] = field(default_factory=list)
    player_tendencies: str = ""
    narrative_variation_text: str = ""
    # Retrieval hits (filtered RAG content already rendered as a single text).
    rag_text: str = ""
    # Free-form extras a project wants to surface as BP3 content (e.g. presim
    # NPC predictions, scene runtime context, module navigation event).
    extras_text: str = ""
    # Campaign history block — filled in BREAK mode, empty in IC.
    campaign_history_text: str = ""


@dataclass
class TrpgServices:
    """Bundle of adapters injected by the caller. Each project plugs in its
    own concrete implementations; framework code only depends on the
    Protocol interfaces in adapters/protocols.py."""

    llm: "LlmAdapter"
    ruleset: "RulesetAdapter"
    retrieval: "RetrievalAdapter"
    multimedia: "MultimediaAdapter"
    clock: "Clock"


@dataclass
class MemoryUpdate:
    """One change to apply to SessionState.memory_state."""

    op: Literal["append", "replace", "delete", "merge"]
    bucket: Literal["scenes", "npcs", "plot_threads", "world_facts", "narrative"]
    key: str | None = None
    value: Any = None


@dataclass
class SceneTransition:
    from_scene: str | None
    to_scene: str
    reason: str = ""


@dataclass
class SessionStateDiff:
    """Describes what to write back. Framework returns this — caller persists.

    The framework never opens a transaction or calls db.commit; it computes
    everything in-memory and hands back this diff. This keeps the SSE
    generator decoupled from FastAPI's Depends(db_session) lifecycle and
    avoids the InvalidRequestError-on-detached-instance class of bugs."""

    new_messages: list[Message] = field(default_factory=list)
    memory_updates: list[MemoryUpdate] = field(default_factory=list)
    dice_consumed: list[str] = field(default_factory=list)
    scene_transitions: list[SceneTransition] = field(default_factory=list)
    state_transitions: dict[str, Any] = field(default_factory=dict)


# Forward declaration: BpSnapshot lives in bp/snapshot.py to keep this
# module pure. Importers should pull it from `framework.bp.snapshot` or
# from the package root.
@dataclass
class TurnResult:
    assistant: str
    metadata: dict[str, Any]
    state_diff: SessionStateDiff
    thinking_events: list[str]
    bp_snapshot: Any  # BpSnapshot — typed loosely to avoid circular imports
