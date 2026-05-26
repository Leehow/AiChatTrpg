"""TRPG framework — portable engine shared between chatlab and chatrpg.

Sync direction for this package: chatlab -> chatrpg (one-way rsync).
Adapter implementations live in each project, not in this package.

Design contract: see docs/design/2026-04-27-trpg-framework.md
"""

from .events import (
    BpSnapshotEvent,
    ContentDeltaEvent,
    DoneEvent,
    ErrorEvent,
    MarkerEvent,
    MetadataEvent,
    SideEffectEvent,
    ThinkingEvent,
    TurnEvent,
)
from .models import (
    CharacterTemplate,
    FeatureFlags,
    IcContext,
    LayeredPrompt,
    Message,
    MessagePhase,
    MessageRole,
    ModelConfig,
    ModuleData,
    PromptMessage,
    RulesetData,
    SessionState,
    SessionStateDiff,
    StableText,
    TrpgServices,
    TurnInputs,
    TurnResult,
)
from .modes import Mode, ModeHint, select_mode
from .pipeline import run_trpg_turn

__all__ = [
    "BpSnapshotEvent",
    "CharacterTemplate",
    "ContentDeltaEvent",
    "DoneEvent",
    "ErrorEvent",
    "FeatureFlags",
    "IcContext",
    "MarkerEvent",
    "Message",
    "MessagePhase",
    "MessageRole",
    "MetadataEvent",
    "Mode",
    "ModeHint",
    "ModelConfig",
    "ModuleData",
    "PromptMessage",
    "RulesetData",
    "SessionState",
    "SessionStateDiff",
    "SideEffectEvent",
    "StableText",
    "ThinkingEvent",
    "TrpgServices",
    "TurnEvent",
    "TurnInputs",
    "TurnResult",
    "run_trpg_turn",
    "select_mode",
]
