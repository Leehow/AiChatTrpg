"""P6 end-to-end checks for NPC knowledge boundaries.

Run:
    cd backend && source .venv/bin/activate
    PYTHONPATH=. python debug/trpg/test_memory_runtime_p6.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import services.trpg_npc.turn_sync as turn_sync_module  # noqa: E402
from orm.models import Base, GameSession  # noqa: E402
from services.trpg_context.models import Visibility  # noqa: E402
from services.trpg_memory.memory_models import (  # noqa: E402
    MemoryKind,
    MemoryOperation,
    MemoryProposal,
    TruthStatus,
)
from services.trpg_memory.runtime_store import commit_memory_proposals  # noqa: E402
from services.trpg_npc.background_planner import (  # noqa: E402
    build_background_planner_prompt,
    build_cards_from_planner_response_detailed,
)
from services.trpg_npc.knowledge_runtime import build_npc_knowledge_runtime  # noqa: E402
from services.trpg_npc.models import NPCProfile, NPCTier  # noqa: E402
from services.trpg_npc.turn_sync import sync_npcs_after_turn  # noqa: E402


def assert_true(label: str, cond: bool, why: str = "") -> None:
    if not cond:
        print(f"FAIL: {label} {why}")
        sys.exit(1)
    print(f"OK: {label}")


async def seed_session(db) -> GameSession:
    session = GameSession(
        id="sess-p6-memory",
        user_id="user-p6-memory",
        title="P6 Memory Boundary",
        character={"identity": {"name": "Jack Marlow"}},
        module_state={"scene": "tavern"},
        memory_state={
            "current_scene": "tavern",
            "npcs": [
                {
                    "key": "keeper",
                    "name": "Elaine Marsh",
                    "player_known_name": "店主",
                    "name_revealed": False,
                    "role": "shopkeeper",
                    "last_seen_scene": "tavern",
                    "inner_state": {"emotional_state": "wary"},
                    "player_knowledge": {"interest": 4},
                }
            ],
        },
    )
    db.add(session)
    await db.flush()

    transcript = "\n".join([
        "Everyone can see the red door.",
        "The party found a hidden knife.",
        "Elaine suspects the party is lying.",
    ])
    proposals = (
        MemoryProposal(
            operation=MemoryOperation.ADD,
            kind=MemoryKind.CLUE,
            text="The red door is marked with a brass sun.",
            visibility=Visibility.PUBLIC,
            owner_id=None,
            subject_ids=("red_door",),
            source_turn_ids=("turn_1",),
            source_quote="Everyone can see the red door.",
            truth_status=TruthStatus.TRUE,
        ),
        MemoryProposal(
            operation=MemoryOperation.ADD,
            kind=MemoryKind.CLUE,
            text="The party found a hidden knife.",
            visibility=Visibility.PARTY_KNOWN,
            owner_id=None,
            subject_ids=("knife",),
            source_turn_ids=("turn_1",),
            source_quote="The party found a hidden knife.",
            truth_status=TruthStatus.TRUE,
        ),
        MemoryProposal(
            operation=MemoryOperation.ADD,
            kind=MemoryKind.BELIEF,
            text="Elaine suspects the party is lying.",
            visibility=Visibility.NPC_PRIVATE,
            owner_id="keeper",
            subject_ids=("party",),
            source_turn_ids=("turn_1",),
            source_quote="Elaine suspects the party is lying.",
            truth_status=TruthStatus.BELIEF,
        ),
        MemoryProposal(
            operation=MemoryOperation.ADD,
            kind=MemoryKind.SECRET,
            text="The butler is the killer.",
            visibility=Visibility.GM_ONLY,
            owner_id=None,
            subject_ids=("butler",),
            source_turn_ids=("module",),
            truth_status=TruthStatus.GM_SECRET,
        ),
    )
    result = await commit_memory_proposals(
        db,
        session,
        proposals,
        transcript_text=transcript,
    )
    assert_true("p6 seed commits memories", len(result.committed) == 4, repr(result))
    return session


async def case_npc_knowledge_boundary_and_leak_gates() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        session = await seed_session(db)

        knowledge = await build_npc_knowledge_runtime(
            db,
            session,
            npc_ids=("keeper",),
            scene_id="tavern",
        )
        payload = knowledge.prompt_payloads_by_npc_id()["keeper"]
        payload_text = repr(payload)
        assert_true("npc sees public memory", "red door" in payload_text, payload_text)
        assert_true("npc sees own private belief", "Elaine suspects" in payload_text, payload_text)
        assert_true("npc does not see party-known clue", "hidden knife" not in payload_text, payload_text)
        assert_true("npc does not see gm secret", "butler is the killer" not in payload_text, payload_text)
        assert_true(
            "withheld memories available for audit",
            len(knowledge.forbidden_memories_by_npc_id["keeper"]) == 2,
            knowledge.summary().__repr__(),
        )

        prompt = build_background_planner_prompt(
            profiles_by_id={
                "keeper": NPCProfile(
                    npc_id="keeper",
                    name="Elaine Marsh",
                    tier=NPCTier.SUPPORTING,
                    private_card={"secret_agenda": "The butler is the killer."},
                )
            },
            states_by_id={},
            relationships_by_npc={},
            knowledge_profiles_by_npc_id=knowledge.prompt_payloads_by_npc_id(),
            scene_id="tavern",
            turn_id=3,
            player_text="I ask Elaine what she knows.",
            gm_reply="Elaine looks toward the back room.",
        )
        assert_true("planner prompt includes npc knowledge profile", "knowledge_profile" in prompt)
        assert_true("planner prompt excludes raw private card", "private_card" not in prompt)
        assert_true("planner prompt excludes party-known clue", "hidden knife" not in prompt)
        assert_true("planner prompt excludes gm secret", "butler is the killer" not in prompt)

        raw_cards = json.dumps({
            "cards": [
                {
                    "npc_id": "keeper",
                    "intent": "reveal_forbidden_secret",
                    "action_type": "SAY",
                    "speech_intent": "Tell the PC that the butler is the killer.",
                }
            ]
        })
        card_result = build_cards_from_planner_response_detailed(
            raw_cards,
            profiles_by_id={"keeper": NPCProfile(npc_id="keeper", name="Elaine Marsh")},
            based_on_turn_id=3,
            forbidden_memories_by_npc_id=knowledge.forbidden_memories_by_npc_id,
        )
        card_diag = card_result.diagnostics.to_dict()
        assert_true("leaking planner card blocked", not card_result.cards, repr(card_diag))
        assert_true("planner leak counted", card_diag["knowledge_leak_blocked"] == 1, repr(card_diag))

        original_call = turn_sync_module.call_llm_json_task

        async def fake_call(*, stage, **_kwargs):
            if stage == "npc_turn_sync":
                return json.dumps({
                    "npc_updates": [
                        {
                            "key": "keeper",
                            "motivation": "Tell Jack that the butler is the killer.",
                        }
                    ]
                })
            raise AssertionError(f"unexpected stage: {stage}")

        turn_sync_module.call_llm_json_task = fake_call
        try:
            sync_summary = await sync_npcs_after_turn(
                db,
                session,
                player_text="I ask Elaine what she knows.",
                gm_reply="Elaine hesitates.",
                cfg={"model": "test", "base_url": "http://test", "api_key": "key"},
                based_on_turn_id=3,
            )
        finally:
            turn_sync_module.call_llm_json_task = original_call

        npc = session.memory_state["npcs"][0]
        assert_true("turn sync leak counted", sync_summary["knowledge_leak_blocked"] == 1, repr(sync_summary))
        assert_true("turn sync leaking update skipped", npc["inner_state"].get("motivation") != "Tell Jack that the butler is the killer.", repr(npc))

    await engine.dispose()


async def main() -> None:
    await case_npc_knowledge_boundary_and_leak_gates()
    print("All P6 memory runtime boundary cases passed.")


if __name__ == "__main__":
    asyncio.run(main())
