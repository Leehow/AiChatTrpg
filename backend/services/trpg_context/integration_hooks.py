"""Example integration points for existing chatrpg services.

These functions are deliberately thin. In the actual repo, wire them into
trpg_scene_runtime.py and trpg_auto_memory.py rather than copying wholesale.
"""

from __future__ import annotations

from .block_store import ContextBlockStore
from .context_builder import ContextBuilder
from .models import ActorScope, ContextProfile, ContextRequest, DynamicContext, Provider
from .prompt_compiler import PromptCompiler


def build_gm_prompt_for_turn(
    *,
    block_store: ContextBlockStore,
    provider: str,
    model: str,
    campaign_id: str,
    session_id: str,
    scene_id: str,
    ruleset_id: str,
    chapter_id: str | None,
    location_id: str | None,
    turn_id: str,
    world_state: dict,
    retrieved_memories: list[dict],
    recent_transcript: list[dict],
    player_input: str,
    npc_ids_in_scene: tuple[str, ...] = (),
):
    builder = ContextBuilder(block_store)
    compiler = PromptCompiler()
    request = ContextRequest(
        actor=ActorScope(
            profile=ContextProfile.GM,
            campaign_id=campaign_id,
            session_id=session_id,
            scene_id=scene_id,
        ),
        provider=Provider(provider),
        model=model,
        ruleset_id=ruleset_id,
        campaign_id=campaign_id,
        chapter_id=chapter_id,
        location_id=location_id,
        npc_ids_in_scene=npc_ids_in_scene,
        dynamic=DynamicContext(
            turn_id=turn_id,
            world_state=world_state,
            retrieved_memories=retrieved_memories,
            recent_transcript=recent_transcript,
            current_input=player_input,
        ),
    )
    compiled_context = builder.build(request)
    return compiler.compile(provider=Provider(provider), model=model, context=compiled_context)


def build_npc_prompt_for_turn(
    *,
    block_store: ContextBlockStore,
    provider: str,
    model: str,
    campaign_id: str,
    session_id: str,
    scene_id: str,
    npc_id: str,
    ruleset_id: str,
    chapter_id: str | None,
    location_id: str | None,
    turn_id: str,
    npc_visible_state: dict,
    npc_private_memories: list[dict],
    recent_transcript: list[dict],
    player_input: str,
):
    builder = ContextBuilder(block_store)
    compiler = PromptCompiler()
    request = ContextRequest(
        actor=ActorScope(
            profile=ContextProfile.NPC,
            campaign_id=campaign_id,
            session_id=session_id,
            scene_id=scene_id,
            npc_id=npc_id,
        ),
        provider=Provider(provider),
        model=model,
        ruleset_id=ruleset_id,
        campaign_id=campaign_id,
        chapter_id=chapter_id,
        location_id=location_id,
        npc_ids_in_scene=(npc_id,),
        dynamic=DynamicContext(
            turn_id=turn_id,
            world_state=npc_visible_state,
            retrieved_memories=npc_private_memories,
            recent_transcript=recent_transcript,
            current_input=player_input,
        ),
    )
    compiled_context = builder.build(request)
    return compiler.compile(provider=Provider(provider), model=model, context=compiled_context)
