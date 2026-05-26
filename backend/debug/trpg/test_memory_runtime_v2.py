"""Smoke tests for Memory Runtime v2 integration.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_memory_runtime_v2.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orm.models import Base, GameSession  # noqa: E402
from agents.trpg.framework.models import LayeredPrompt, PromptMessage  # noqa: E402
from services.trpg_auto_memory import (  # noqa: E402
    AutoMemoryResult,
    build_auto_memory_proposals,
)
from services.trpg_context.block_store import InMemoryBlockStore  # noqa: E402
from services.trpg_context.context_builder import ContextBuilder  # noqa: E402
from services.trpg_context.models import (  # noqa: E402
    ActorScope,
    BlockKind,
    CacheZone,
    ContextBlock,
    ContextProfile,
    ContextRequest,
    DynamicContext,
    Provider,
    Stability,
    Visibility,
)
from services.trpg_context.layered_prompt_projection import (  # noqa: E402
    compile_layered_prompt_context,
)
from services.trpg_memory.memory_models import (  # noqa: E402
    MemoryKind,
    MemoryOperation,
    MemoryProposal,
    TruthStatus,
)
from services.trpg_memory.runtime_store import (  # noqa: E402
    build_public_memory_view,
    commit_memory_proposals,
    list_session_memory_items,
    public_memory_view_to_dict,
)
from services.trpg_runtime.runtime_store import list_turn_traces, save_turn_trace  # noqa: E402
from services.trpg_runtime.turn_trace import TurnTrace  # noqa: E402


def assert_true(label: str, cond: bool, why: str = "") -> None:
    if not cond:
        print(f"FAIL: {label} {why}")
        sys.exit(1)
    print(f"OK: {label}")


async def case_commit_gate_persists_and_dedupes() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        session = GameSession(id="sess-memory-v2", user_id="user-memory-v2", title="Memory v2")
        db.add(session)
        await db.flush()

        auto = AutoMemoryResult(
            events=["门廊上的血迹被玩家注意到。"],
            discoveries=["血迹一路通向仓库侧门。"],
            plot_threads=[{
                "title": "warehouse_bloodtrail",
                "status": "active",
                "summary": "玩家正在追查血迹来源。",
            }],
        )
        gm_text = "门廊上的血迹被玩家注意到。血迹一路通向仓库侧门。"
        proposals = build_auto_memory_proposals(
            auto,
            player_message="我检查门廊。",
            gm_content=gm_text,
            turn_marker="turn_7",
        )
        assert_true("auto result builds proposals", len(proposals) == 3, repr(proposals))

        first = await commit_memory_proposals(
            db,
            session,
            proposals,
            transcript_text="我检查门廊。\n" + gm_text,
        )
        assert_true("first commit stores all proposals", len(first.committed) == 3, repr(first))
        assert_true("no rejected proposals", not first.rejected, repr(first.rejected))

        second = await commit_memory_proposals(
            db,
            session,
            proposals,
            transcript_text="我检查门廊。\n" + gm_text,
        )
        assert_true("second commit dedupes", len(second.committed) == 0, repr(second))
        assert_true("event duplicate tracked", len(second.duplicate_noops) == 1, repr(second))
        assert_true("durable facts reinforced", len(second.reinforced) == 2, repr(second))

        visible = await list_session_memory_items(
            db,
            session.id,
            visibility=(Visibility.PARTY_KNOWN,),
        )
        assert_true("visible memory rows reload", len(visible) == 3, repr(visible))
        assert_true("source turn persisted", visible[0].source_turn_ids == ("turn_7",), repr(visible[0]))

        secret_proposals = (
            MemoryProposal(
                operation=MemoryOperation.ADD,
                kind=MemoryKind.SECRET,
                text="管家是凶手。",
                visibility=Visibility.GM_ONLY,
                owner_id=None,
                subject_ids=("npc_butler",),
                source_turn_ids=("turn_7",),
                truth_status=TruthStatus.GM_SECRET,
                confidence=1.0,
                salience=0.9,
            ),
            MemoryProposal(
                operation=MemoryOperation.ADD,
                kind=MemoryKind.BELIEF,
                text="艾琳怀疑玩家隐瞒线索。",
                visibility=Visibility.NPC_PRIVATE,
                owner_id="npc_erin",
                subject_ids=("party",),
                source_turn_ids=("turn_7",),
                source_quote="艾琳怀疑玩家隐瞒线索。",
                truth_status=TruthStatus.BELIEF,
            ),
        )
        secret_commit = await commit_memory_proposals(
            db,
            session,
            secret_proposals,
            transcript_text="艾琳怀疑玩家隐瞒线索。",
        )
        assert_true("private memories commit", len(secret_commit.committed) == 2, repr(secret_commit))

        public_view = await build_public_memory_view(db, session.id)
        public_payload = public_memory_view_to_dict(public_view)
        public_text = repr(public_payload)
        assert_true("public view shows clue", "血迹一路通向仓库侧门" in public_text, public_text)
        assert_true("public view hides gm secret", "管家是凶手" not in public_text, public_text)
        assert_true("public view hides npc private", "艾琳怀疑" not in public_text, public_text)

        trace = await save_turn_trace(
            db,
            session,
            TurnTrace(
                turn_id="turn_7",
                campaign_id=session.id,
                player_input="我检查门廊。",
                parsed_contract_summary={
                    "auto_memory_v2": {
                        "memory_ids": [item.memory_id for item in first.committed],
                    },
                },
                memory_proposal_count=len(proposals),
                committed_memory_ids=tuple(item.memory_id for item in first.committed),
            ),
        )
        rows, has_more = await list_turn_traces(db, session.id, limit=10)
        assert_true("turn trace stored", rows and rows[0].id == trace.id, repr(rows))
        assert_true("turn trace memory count", rows[0].memory_proposal_count == 3, repr(rows[0]))
        assert_true("turn trace no pagination", has_more is False)

    await engine.dispose()


def case_context_builder_visibility_and_prefix_hash() -> None:
    store = InMemoryBlockStore([
        ContextBlock(
            block_id="engine.protocol",
            kind=BlockKind.ENGINE_PROTOCOL,
            title="Engine protocol",
            content={"rule": "respect visibility"},
            visibility=Visibility.PUBLIC,
            stability=Stability.IMMUTABLE,
            cache_zone=CacheZone.PREFIX,
            priority=100,
        ),
        ContextBlock(
            block_id="campaign.secret",
            kind=BlockKind.CAMPAIGN_STATIC,
            title="GM secret",
            content={"villain": "hidden cultist"},
            visibility=Visibility.GM_ONLY,
            stability=Stability.IMMUTABLE,
            cache_zone=CacheZone.PREFIX,
            scope_type="campaign",
            scope_id="sess-memory-v2",
            priority=90,
        ),
    ])
    builder = ContextBuilder(store)

    def build(profile: ContextProfile, text: str):
        return builder.build(
            ContextRequest(
                actor=ActorScope(
                    profile=profile,
                    campaign_id="sess-memory-v2",
                    session_id="sess-memory-v2",
                ),
                provider=Provider.OPENAI,
                model="debug",
                ruleset_id="rules",
                campaign_id="sess-memory-v2",
                dynamic=DynamicContext(turn_id="turn_1", current_input=text),
            )
        )

    player_ctx = build(ContextProfile.PLAYER, "look")
    gm_ctx_1 = build(ContextProfile.GM, "look")
    gm_ctx_2 = build(ContextProfile.GM, "open door")
    assert_true("player context hides gm secret", "hidden cultist" not in player_ctx.prefix_text)
    assert_true("gm context sees gm secret", "hidden cultist" in gm_ctx_1.prefix_text)
    assert_true("dynamic input keeps prefix hash stable", gm_ctx_1.prefix_hash == gm_ctx_2.prefix_hash)
    assert_true("dynamic input changes tail", gm_ctx_1.dynamic_text != gm_ctx_2.dynamic_text)


def case_layered_prompt_projection_records_cache_metadata() -> None:
    base_prompt = LayeredPrompt(
        stable_prefix="# Ruleset: Debug\nWorld mode: test\n\n## Module\nThe locked study exists.",
        semi_stable_context="## Narrative Summary\nThe party reached the foyer.",
        variable_suffix="## PC\nAlice is cautious.",
        history=[
            PromptMessage(role="user", content="我检查门。"),
            PromptMessage(role="assistant", content="门上有黄铜把手。"),
        ],
        user_message="我听门后。",
    )
    changed_input = LayeredPrompt(
        stable_prefix=base_prompt.stable_prefix,
        semi_stable_context=base_prompt.semi_stable_context,
        variable_suffix=base_prompt.variable_suffix,
        history=list(base_prompt.history),
        user_message="我打开门。",
    )

    first = compile_layered_prompt_context(
        layered_prompt=base_prompt,
        provider="openrouter",
        model="debug-model",
        ruleset_id="rules-debug",
        campaign_id="sess-memory-v2",
        session_id="sess-memory-v2",
        scene_id="scene_foyer",
        turn_id="turn_11",
    ).metadata
    second = compile_layered_prompt_context(
        layered_prompt=changed_input,
        provider="openrouter",
        model="debug-model",
        ruleset_id="rules-debug",
        campaign_id="sess-memory-v2",
        session_id="sess-memory-v2",
        scene_id="scene_foyer",
        turn_id="turn_11",
    ).metadata

    assert_true("layered projection normalizes provider", first["provider"] == "openai", repr(first))
    assert_true("layered projection has cache key", bool(first["cache_key"]), repr(first))
    assert_true("layered projection has blocks", first["block_count"] >= 4, repr(first))
    assert_true("layered projection records bp1", first["prefix_block_count"] == 1, repr(first))
    assert_true("layered projection records bp2", first["pinned_block_count"] == 1, repr(first))
    assert_true("layered projection records bp3 tail", first["dynamic_block_count"] >= 2, repr(first))
    assert_true("layered prefix stable across input", first["prefix_hash"] == second["prefix_hash"])
    assert_true("layered user hash changes", first["user_message_hash"] != second["user_message_hash"])


async def main() -> None:
    await case_commit_gate_persists_and_dedupes()
    case_context_builder_visibility_and_prefix_hash()
    case_layered_prompt_projection_records_cache_metadata()
    print("All memory runtime v2 cases passed.")


if __name__ == "__main__":
    asyncio.run(main())
