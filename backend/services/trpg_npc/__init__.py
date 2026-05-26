"""ChatRPG NPC agent — single import surface for everything NPC-related.

Submodules:

- :mod:`services.trpg_npc.agent`      ``NpcAgent`` facade — the canonical
                                       entry point for create / update /
                                       read / delete / asset queue calls.
- :mod:`services.trpg_npc.visibility` Real-name vs player-known-name fields.
- :mod:`services.trpg_npc.psychology` ``inner_state`` + ``player_knowledge``
                                       (motivation, mood, interest 0-10,
                                       interest_drive, relationship level).
- :mod:`services.trpg_npc.params`     LLM-backed mechanical stat generator
                                       (HP / core attributes / role traits).
- :mod:`services.trpg_npc.assets`     Portrait + TTS voice assignment and
                                       background queue management.

Module-side NPC card extraction (``services.module_npc_cards``) is
*module-parse-time*, not session-time, so it deliberately lives outside
this package — it produces the cards, the agent here consumes them.

For new code, prefer the agent::

    from services.trpg_npc import NpcAgent
    agent = NpcAgent(session)
    agent.add(npc_dict, default_revealed=False)
    await agent.ensure_assets(db)
    agent.save(db)

The submodule helpers stay re-exported for the existing call sites
(character_intake, adventure_start, ic_runner, tts) until they migrate.
"""

from services.trpg_npc.action_summary import (
    SUMMARY_MAX_CHARS,
    update_action_summary,
)
from services.trpg_npc.action_board import ActionBoard, TriggerMatcher
from services.trpg_npc.action_resolver import ActionResolver
from services.trpg_npc.agent import NpcAgent
from services.trpg_npc.assets import (
    MALE_VOICES,
    FEMALE_VOICES,
    GEMINI_MALE,
    GEMINI_FEMALE,
    MINIMAX_MALE,
    MINIMAX_FEMALE,
    ModelRuntime,
    NpcAssetSummary,
    PORTRAIT_GENERATOR_VERSION,
    ensure_npc_assets,
    spawn_npc_portrait_task,
)
from services.trpg_npc.background_planner import (
    append_background_planner_observation,
    background_planner_snapshot,
    build_cards_from_planner_response,
    compact_background_planner_summary,
    plan_background_npc_actions,
    select_background_planner_npc_ids,
    spawn_background_npc_planner_task,
)
from services.trpg_npc.params import (
    MAX_FAILURES,
    build_rules_hint_from_parsed_v6,
    generate_missing_npc_params,
)
from services.trpg_npc.models import (
    ActionProposal,
    ActionType,
    Fact,
    GameEvent,
    MemoryRecord,
    NPCIntentCard,
    NPCProfile,
    NPCState,
    NPCTier,
    PlotConstraints,
    RelationshipVector,
    ResolveDecision,
    ResolvedAction,
    SceneBeat,
    SceneBeatPlan,
    ScenePlotContract,
    SceneState,
)
from services.trpg_npc.npc_generation import NPCFactory, NPCGenerationSpec
from services.trpg_npc.orchestrator import (
    NPCTurnOrchestrator,
    PostTurnResult,
    PreTurnResult,
)
from services.trpg_npc.plot_integrator import PlotIntegrator
from services.trpg_npc.post_visible_worker import (
    run_npc_post_visible_work,
    spawn_npc_post_visible_work,
)
from services.trpg_npc.runtime_adapter import (
    NPCActionBoardWarmResult,
    NPCPreTurnRuntimeResult,
    apply_post_turn_result_to_memory_state,
    build_npc_pre_turn_runtime,
    prompt_safe_active_npcs,
    warm_npc_action_board_after_turn,
)
from services.trpg_npc.runtime_diagnostics import (
    NPCRuntimeSnapshotDiagnostics,
    compare_npc_runtime_v2_snapshot,
)
from services.trpg_npc.runtime_persistence import (
    NPCRuntimeTablePayload,
    apply_npc_runtime_v2_table_snapshot_to_session,
    build_npc_pre_turn_runtime_from_table_rows,
    build_npc_pre_turn_runtime_from_tables,
    build_npc_runtime_v2_table_payloads,
    build_npc_runtime_v2_table_payloads_from_session_snapshot,
    hydrate_npc_runtime_v2_from_tables,
    persist_npc_runtime_v2_table_payload,
    persist_npc_runtime_v2_tables,
    persist_npc_runtime_v2_tables_authority,
)
from services.trpg_npc.psychology import (
    INTEREST_RUBRIC,
    INNER_STATE_THOUGHT_CAP,
    append_inner_thought,
    derive_interaction_drive,
    derive_player_interest,
    ensure_npc_inner_state,
    ensure_npc_player_knowledge,
    ensure_npc_psychology,
    player_interest_profile,
)
from services.trpg_npc.visibility import (
    derive_public_npc_name,
    ensure_npc_visibility_fields,
    is_female_gender,
    is_male_gender,
    mask_hidden_npc_names_in_text,
    mask_hidden_true_name,
    reveal_name,
)
from services.trpg_npc.visibility_llm import (
    enhance_player_known_name,
    enhance_player_known_names,
)
from services.trpg_npc.turn_sync import (
    collect_runtime_state_versions,
    spawn_turn_sync_task,
    sync_npcs_after_turn,
)
from services.trpg_npc.voice_card import (
    generate_missing_voice_cards,
    generate_voice_card,
)


__all__ = [
    # Agent facade
    "NpcAgent",
    # Background planner
    "append_background_planner_observation",
    "background_planner_snapshot",
    "build_cards_from_planner_response",
    "compact_background_planner_summary",
    "plan_background_npc_actions",
    "select_background_planner_npc_ids",
    "spawn_background_npc_planner_task",
    # Runtime V2 orchestration
    "NPCTurnOrchestrator",
    "PreTurnResult",
    "PostTurnResult",
    "ActionBoard",
    "TriggerMatcher",
    "ActionResolver",
    "PlotIntegrator",
    # Runtime V2 models
    "ActionProposal",
    "ActionType",
    "Fact",
    "GameEvent",
    "MemoryRecord",
    "NPCFactory",
    "NPCGenerationSpec",
    "NPCIntentCard",
    "NPCProfile",
    "NPCState",
    "NPCTier",
    "PlotConstraints",
    "RelationshipVector",
    "ResolveDecision",
    "ResolvedAction",
    "SceneBeat",
    "SceneBeatPlan",
    "ScenePlotContract",
    "SceneState",
    "NPCActionBoardWarmResult",
    "NPCPreTurnRuntimeResult",
    "NPCRuntimeSnapshotDiagnostics",
    "apply_post_turn_result_to_memory_state",
    "build_npc_pre_turn_runtime",
    "build_npc_pre_turn_runtime_from_table_rows",
    "build_npc_pre_turn_runtime_from_tables",
    "apply_npc_runtime_v2_table_snapshot_to_session",
    "build_npc_runtime_v2_table_payloads",
    "build_npc_runtime_v2_table_payloads_from_session_snapshot",
    "hydrate_npc_runtime_v2_from_tables",
    "NPCRuntimeTablePayload",
    "persist_npc_runtime_v2_table_payload",
    "persist_npc_runtime_v2_tables",
    "persist_npc_runtime_v2_tables_authority",
    "compare_npc_runtime_v2_snapshot",
    "prompt_safe_active_npcs",
    "run_npc_post_visible_work",
    "spawn_npc_post_visible_work",
    "warm_npc_action_board_after_turn",
    # Action summary
    "SUMMARY_MAX_CHARS",
    "update_action_summary",
    # Assets
    "MALE_VOICES",
    "FEMALE_VOICES",
    "GEMINI_MALE",
    "GEMINI_FEMALE",
    "MINIMAX_MALE",
    "MINIMAX_FEMALE",
    "ModelRuntime",
    "NpcAssetSummary",
    "PORTRAIT_GENERATOR_VERSION",
    "ensure_npc_assets",
    "spawn_npc_portrait_task",
    # Params
    "MAX_FAILURES",
    "build_rules_hint_from_parsed_v6",
    "generate_missing_npc_params",
    # Psychology
    "INTEREST_RUBRIC",
    "INNER_STATE_THOUGHT_CAP",
    "append_inner_thought",
    "derive_interaction_drive",
    "derive_player_interest",
    "ensure_npc_inner_state",
    "ensure_npc_player_knowledge",
    "ensure_npc_psychology",
    "player_interest_profile",
    # Visibility
    "derive_public_npc_name",
    "ensure_npc_visibility_fields",
    "enhance_player_known_name",
    "enhance_player_known_names",
    "is_female_gender",
    "is_male_gender",
    "mask_hidden_npc_names_in_text",
    "mask_hidden_true_name",
    "reveal_name",
    # Voice cards
    "generate_voice_card",
    "generate_missing_voice_cards",
    # Per-turn state sync
    "collect_runtime_state_versions",
    "spawn_turn_sync_task",
    "sync_npcs_after_turn",
]
