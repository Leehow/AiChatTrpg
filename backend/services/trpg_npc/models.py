"""Core data contracts for the chatrpg NPC runtime.

The whole NPC system is built around one rule:
NPC agents propose actions; the scene/runtime resolves and integrates them.

These dataclasses are deliberately simple. If your backend uses Pydantic,
you can wrap or convert them at the API boundary without changing the runtime
logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from .utils import clamp, clamp_signed, deep_to_dict, new_id, now_iso


class NPCTier(str, Enum):
    BACKGROUND = "L0_BACKGROUND"
    MINOR = "L1_MINOR"
    SUPPORTING = "L2_SUPPORTING"
    MAJOR = "L3_MAJOR"
    FACTION = "L4_FACTION"


class ActionType(str, Enum):
    SAY = "SAY"
    EMOTE = "EMOTE"
    MOVE = "MOVE"
    ATTACK = "ATTACK"
    FLEE = "FLEE"
    HELP = "HELP"
    DECEIVE = "DECEIVE"
    REVEAL_CLUE = "REVEAL_CLUE"
    DELAY = "DELAY"
    OBSERVE = "OBSERVE"
    OFFSCREEN = "OFFSCREEN"
    NOOP = "NOOP"


class ProposalStatus(str, Enum):
    PREDICTED = "predicted"
    PROPOSED = "proposed"
    RESOLVED = "resolved"
    TRANSFORMED = "transformed"
    BLOCKED = "blocked"
    EXPIRED = "expired"


class ResolveDecision(str, Enum):
    ALLOW = "allow"
    TRANSFORM = "transform"
    BLOCK = "block"


@dataclass(slots=True)
class Serializable:
    def to_dict(self) -> dict[str, Any]:
        return deep_to_dict(self)


@dataclass(slots=True)
class PersonaVector(Serializable):
    openness: float = 0.50
    conscientiousness: float = 0.50
    extraversion: float = 0.50
    agreeableness: float = 0.50
    neuroticism: float = 0.50
    dominance: float = 0.50
    empathy: float = 0.50
    impulse_control: float = 0.50
    paranoia: float = 0.30
    ambition: float = 0.50
    fanaticism: float = 0.00
    deception_skill: float = 0.30

    def normalized(self) -> "PersonaVector":
        for name in self.__dataclass_fields__:
            setattr(self, name, clamp(getattr(self, name)))
        return self


@dataclass(slots=True)
class MoodVector(Serializable):
    # Summary affect dimensions
    valence: float = 0.0              # [-1, 1], negative -> bad mood
    arousal: float = 0.35             # [0, 1], high -> activated/urgent
    dominance_feeling: float = 0.50   # [0, 1], high -> feels in control

    # Concrete emotions / states
    fear: float = 0.0
    anger: float = 0.0
    sadness: float = 0.0
    joy: float = 0.0
    disgust: float = 0.0
    shame: float = 0.0
    curiosity: float = 0.25
    suspicion: float = 0.25
    stress: float = 0.20
    fatigue: float = 0.0

    def normalized(self) -> "MoodVector":
        self.valence = clamp_signed(self.valence)
        self.arousal = clamp(self.arousal)
        self.dominance_feeling = clamp(self.dominance_feeling)
        for name in [
            "fear", "anger", "sadness", "joy", "disgust", "shame",
            "curiosity", "suspicion", "stress", "fatigue",
        ]:
            setattr(self, name, clamp(getattr(self, name)))
        return self

    def as_float_dict(self) -> dict[str, float]:
        return self.to_dict()  # type: ignore[return-value]


@dataclass(slots=True)
class RelationshipVector(Serializable):
    trust: float = 0.30
    respect: float = 0.30
    fear: float = 0.0
    suspicion: float = 0.30
    resentment: float = 0.0
    debt: float = 0.0                 # [-1, 1]; positive means NPC owes target
    affinity: float = 0.0             # [-1, 1]

    def normalized(self) -> "RelationshipVector":
        self.trust = clamp(self.trust)
        self.respect = clamp(self.respect)
        self.fear = clamp(self.fear)
        self.suspicion = clamp(self.suspicion)
        self.resentment = clamp(self.resentment)
        self.debt = clamp_signed(self.debt)
        self.affinity = clamp_signed(self.affinity)
        return self


@dataclass(slots=True)
class VoiceCard(Serializable):
    tone: str = "neutral"
    register: str = "plain"
    sentence_length: str = "medium"
    catchphrases: list[str] = field(default_factory=list)
    forbidden_style: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    address_style: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class NPCMode(Serializable):
    mode_id: str
    title: str
    description: str = ""
    visible_expression: str = "neutral"
    tone_bias: str = ""
    trigger_conditions: list[str] = field(default_factory=list)
    policy_bias: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class PlotConstraints(Serializable):
    can_reveal_core_secret: bool = False
    can_attack_players: str = "only_if_exposed_or_cornered"
    can_flee: bool = True
    must_preserve_clue_path: bool = True
    max_clue_reveals_per_turn: int = 1
    minimum_clue_output: str | None = None
    forbidden_fact_ids: list[str] = field(default_factory=list)
    core_secret_ids: list[str] = field(default_factory=list)
    blocked_escalations: list[str] = field(default_factory=list)
    allowed_escalations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class NPCProfile(Serializable):
    npc_id: str
    name: str
    tier: NPCTier = NPCTier.MINOR
    narrative_role: str = "ambient"
    anchor: dict[str, str] = field(default_factory=dict)
    public_card: dict[str, str] = field(default_factory=dict)
    private_card: dict[str, str] = field(default_factory=dict)
    persona: PersonaVector = field(default_factory=PersonaVector)
    baseline_mood: MoodVector = field(default_factory=MoodVector)
    voice_card: VoiceCard = field(default_factory=VoiceCard)
    modes: list[NPCMode] = field(default_factory=list)
    plot_constraints: PlotConstraints = field(default_factory=PlotConstraints)
    mechanics: dict[str, Any] = field(default_factory=dict)
    knowledge_fact_ids: list[str] = field(default_factory=list)
    secret_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def default_mode_id(self) -> str:
        if self.modes:
            return self.modes[0].mode_id
        return "default"


@dataclass(slots=True)
class NPCState(Serializable):
    npc_id: str
    scene_id: str | None = None
    location_id: str | None = None
    status: str = "active"
    current_mode: str = "default"
    mood: MoodVector = field(default_factory=MoodVector)
    goal_pressure: dict[str, float] = field(default_factory=dict)
    physical_state: dict[str, Any] = field(default_factory=dict)
    active_flags: dict[str, Any] = field(default_factory=dict)
    state_version: int = 0
    updated_at: str = field(default_factory=now_iso)


@dataclass(slots=True)
class Fact(Serializable):
    fact_id: str
    content: str
    truth: bool = True
    known_by: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    confidence: float = 1.0
    gm_only: bool = False
    player_visible: bool = False
    source_event_id: str | None = None


@dataclass(slots=True)
class GameEvent(Serializable):
    event_id: str
    type: str
    scene_id: str
    turn_id: int
    actor_id: str | None = None
    target_ids: list[str] = field(default_factory=list)
    content: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    visibility: dict[str, bool] = field(default_factory=lambda: {"player_visible": True, "gm_visible": True})
    created_at: str = field(default_factory=now_iso)

    @classmethod
    def player_input(cls, scene_id: str, turn_id: int, actor_id: str, content: str, target_ids: list[str] | None = None) -> "GameEvent":
        return cls(
            event_id=new_id("event"),
            type="PLAYER_INPUT",
            scene_id=scene_id,
            turn_id=turn_id,
            actor_id=actor_id,
            target_ids=target_ids or [],
            content=content,
        )


@dataclass(slots=True)
class EventAppraisal(Serializable):
    help: float = 0.0
    threat: float = 0.0
    insult: float = 0.0
    betrayal: float = 0.0
    secret_exposure: float = 0.0
    goal_block: float = 0.0
    uncertainty: float = 0.0
    social_exposure: float = 0.0
    physical_threat: float = 0.0
    offer: float = 0.0
    evidence: float = 0.0
    protected: float = 0.0
    public_pressure: float = 0.0

    def magnitude(self) -> float:
        return clamp(max(self.to_dict().values()) if self.to_dict() else 0.0)


@dataclass(slots=True)
class BehaviorPolicy(Serializable):
    dominant_mood: str = "neutral"
    inner_state: dict[str, float] = field(default_factory=dict)
    visible_expression: str = "neutral"
    tone: str = "neutral"
    speech_style: list[str] = field(default_factory=list)
    cooperation_level: float = 0.5
    deception_level: float = 0.0
    aggression_level: float = 0.0
    risk_tolerance: float = 0.5
    forbidden_behaviors: list[str] = field(default_factory=list)
    strategy_summary: str = ""


@dataclass(slots=True)
class HotStatePatch(Serializable):
    npc_id: str
    patch_reason: str
    temporary_mood_delta: dict[str, float] = field(default_factory=dict)
    temporary_relationship_delta: dict[str, RelationshipVector] = field(default_factory=dict)
    temporary_goal_pressure_delta: dict[str, float] = field(default_factory=dict)
    temporary_policy: BehaviorPolicy | None = None


@dataclass(slots=True)
class NPCPerceptionPacket(Serializable):
    npc_id: str
    scene_id: str
    turn_id: int
    visible_events: list[GameEvent] = field(default_factory=list)
    heard_dialogues: list[GameEvent] = field(default_factory=list)
    visible_entities: list[dict[str, Any]] = field(default_factory=list)
    known_facts: list[Fact] = field(default_factory=list)
    relevant_memories: list[dict[str, Any]] = field(default_factory=list)
    relationship_snapshot: dict[str, RelationshipVector] = field(default_factory=dict)
    rule_constraints: dict[str, Any] = field(default_factory=dict)
    forbidden_fact_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ActionProposal(Serializable):
    actor_id: str
    intent: str
    action_type: ActionType
    target_ids: list[str] = field(default_factory=list)
    priority: float = 0.5
    player_facing: dict[str, str] = field(default_factory=dict)
    gm_facing: dict[str, Any] = field(default_factory=dict)
    mechanics: dict[str, Any] = field(default_factory=dict)
    state_updates: list[dict[str, Any]] = field(default_factory=list)
    memory_writes: list[dict[str, Any]] = field(default_factory=list)
    reveal_fact_ids: list[str] = field(default_factory=list)
    known_fact_ids: list[str] = field(default_factory=list)
    forbidden_fact_ids: list[str] = field(default_factory=list)
    source_card_id: str | None = None
    status: ProposalStatus = ProposalStatus.PROPOSED
    consume_action_budget: bool = True


@dataclass(slots=True)
class NPCIntentCard(Serializable):
    card_id: str
    npc_id: str
    based_on_turn_id: int
    valid_until_turn: int
    priority: float
    trigger_conditions: list[Any]
    preferred_action: ActionProposal
    fallback_actions: list[ActionProposal] = field(default_factory=list)
    motivation: str = ""
    known_fact_ids: list[str] = field(default_factory=list)
    forbidden_fact_ids: list[str] = field(default_factory=list)
    plot_constraints: PlotConstraints = field(default_factory=PlotConstraints)
    status: ProposalStatus = ProposalStatus.PREDICTED
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_valid_for_turn(self, turn_id: int) -> bool:
        return self.status != ProposalStatus.EXPIRED and self.valid_until_turn >= turn_id


@dataclass(slots=True)
class ResolvedAction(Serializable):
    decision: ResolveDecision
    proposal: ActionProposal
    reason: str = ""
    transformed_from: ActionProposal | None = None


@dataclass(slots=True)
class ScenePlotContract(Serializable):
    scene_id: str
    scene_goal: str = ""
    core_clue_ids: list[str] = field(default_factory=list)
    optional_clue_ids: list[str] = field(default_factory=list)
    forbidden_reveals: list[str] = field(default_factory=list)
    allowed_escalations: list[str] = field(default_factory=list)
    blocked_escalations: list[str] = field(default_factory=list)
    max_clue_reveals_per_turn: int = 1
    notes: str = ""


@dataclass(slots=True)
class SceneState(Serializable):
    scene_id: str
    turn_id: int
    location_id: str | None = None
    active_npc_ids: list[str] = field(default_factory=list)
    plot_contract: ScenePlotContract | None = None
    facts_by_id: dict[str, Fact] = field(default_factory=dict)
    action_budget: dict[str, int] = field(default_factory=lambda: {
        "max_primary_npc_actions": 1,
        "max_secondary_npc_reactions": 2,
        "max_ambient_npc_mentions": 3,
        "max_clue_reveals_per_turn": 1,
        "max_hard_world_changes": 1,
    })


@dataclass(slots=True)
class SceneBeat(Serializable):
    type: str
    beat: str
    npc_id: str | None = None
    reason: str = ""
    visibility: Literal["player_visible", "gm_only", "system"] = "player_visible"
    must_include: bool = False
    allowed_reveal_ids: list[str] = field(default_factory=list)
    forbidden_fact_ids: list[str] = field(default_factory=list)
    source_action_id: str | None = None


@dataclass(slots=True)
class SceneBeatPlan(Serializable):
    turn_id: int
    scene_id: str
    player_action_summary: str
    must_include_beats: list[SceneBeat] = field(default_factory=list)
    optional_beats: list[SceneBeat] = field(default_factory=list)
    blocked_actions: list[dict[str, Any]] = field(default_factory=list)
    tone_guidance: dict[str, str] = field(default_factory=dict)
    action_budget: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryRecord(Serializable):
    memory_id: str
    npc_id: str
    memory_type: str
    content: str
    importance: float = 0.5
    source_event_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    tags: list[str] = field(default_factory=list)
