"""Seed a self-contained demo session showcasing the new NPC visual blocks.

Creates a session for the SINGLE_USER_ID configured in the running
backend (default ``local``), pre-populates ``memory_state.npcs`` with
two characters (one hidden / one already-revealed), and inserts a
single GM message containing every new marker so the player can open
the room and verify the rendering end to end.

Run from the backend dir with the venv active:
    cd backend && source .venv/bin/activate
    python debug/trpg/seed_npc_card_demo.py

Output: prints the new session id. Open the app, the room shows up at
the top of the rooms panel.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from core.config import get_settings
from core.database import get_session_factory
from orm.models import GameSession, Message, User


_DEMO_TITLE = "[demo] NPC card + name reveal"

_GM_MESSAGE = """\
你压低身形走近加油站。烈日把柏油晒得发软，金属外壳烫得近乎融化。

[CREATE_NPC key=gas_owner name="加油站老板" gender=male role="埃索加油站老板" portrait_prompt="瘦削干瘪的中年男人，眼神冷漠，工装连体衣沾满油污" voice_hint="低沉沙哑，慢吞吞"]\
First time the PC sees the gas station owner. Cold-eyed, slow speech, evasive demeanor.\
[/CREATE_NPC]

[npc_card name="加油站老板" role="埃索加油站老板" key="gas_owner"]\
瘦削干瘪的中年男人，眼神冷漠，工装连体衣上沾满油污，正坐在遮阳棚下盯着你的车。\
[/npc_card]

「这地方很久没人来了，朋友。」[speak:calm]加油站老板[/speak]

他从口袋掏出一张油渍斑斑的工卡塞进上衣口袋，但你眼快地瞥见上面的名字——"拉斯·罗素"。

[name_reveal npc_key="gas_owner" name="拉斯·罗素"]工卡上的名字露出来了[/name_reveal]

「**拉斯·罗素**？」[speak]PC[/speak]你试探性地念出他的名字。

老人愣了一下，没否认。
"""


async def main() -> int:
    factory = get_session_factory()
    async with factory() as db:
        # Find or create the single-user account.
        user_id = get_settings().single_user_id
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            print(
                f"User '{user_id}' not found. Open the app once to provision "
                f"the single-user account, then re-run this script.",
                file=sys.stderr,
            )
            return 1

        # Find an existing ruleset to satisfy the FK; falls back to None.
        from orm.models import Ruleset
        rs_row = await db.execute(select(Ruleset).limit(1))
        ruleset = rs_row.scalar_one_or_none()

        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        session = GameSession(
            id=session_id,
            user_id=user_id,
            title=_DEMO_TITLE,
            ruleset_id=ruleset.id if ruleset is not None else None,
            archived=False,
            title_auto=False,
            setup_state={
                "step": 2,
                "ruleset_id": ruleset.id if ruleset is not None else None,
                "module_id": None,
                "module_title": None,
                "completed": True,
                "game_started": True,
            },
            character={
                "identity": {"name": "侦探·埃文斯"},
                "name": "侦探·埃文斯",
                "active_tts_voice": "Charon",
            },
            module_state={
                "scene": "scene_gas_station",
                "scene_name": "埃索加油站",
                "title": "血色公路",
                "day_count": 1,
                "in_game_time": "12:30",
                "in_game_period": "afternoon",
                "elapsed_minutes": 0,
            },
            memory_state={
                "scenes": [],
                "plot_threads": [],
                "world_facts": {},
                "npcs": [
                    {
                        "key": "gas_owner",
                        "name": "拉斯·罗素",
                        "player_known_name": "加油站老板",
                        "name_revealed": False,
                        "gender": "male",
                        "role": "埃索加油站老板",
                        "summary": "Gas station owner who saw what came through last week.",
                        "appearance": "瘦削干瘪的中年男人，眼神冷漠",
                        # PC just met this NPC in the gas station scene →
                        # shows up in sidebar as 在场.
                        "last_seen_scene": "scene_gas_station",
                        "source": "dialogue_speaker",
                    },
                    {
                        "key": "ghost_witness",
                        "name": "Karen Vex",
                        "player_known_name": "未透露姓名的市民",
                        "name_revealed": False,
                        "gender": "female",
                        "role": "目击者",
                        "summary": "Mentioned in a missing-persons file the PC has not opened. "
                                   "Should NOT appear in the sidebar — only in the debug roster.",
                    },
                ],
                "player_notes": [],
            },
            narrative_summary="",
            last_active_at=now,
        )
        db.add(session)
        await db.flush()

        # Pre-seed a believable post-process timeline so the UI renders the
        # collapsible timeline strip immediately when the user opens the
        # session. Mix of done events to exercise both the running-state
        # spinner is gone path and the `phase3_complete` total-duration
        # readout.
        ts_now = now.isoformat()
        seeded_steps = [
            {"type": "postprocess_step", "name": "action_board_warm",
             "status": "done", "duration_ms": 64, "detail": "npcs=2 cards=4", "ts": ts_now},
            {"type": "postprocess_step", "name": "runtime_state_persist",
             "status": "done", "duration_ms": 91, "detail": "tables synced", "ts": ts_now},
            {"type": "postprocess_step", "name": "routine_events",
             "status": "done", "duration_ms": 18, "detail": "1 events", "ts": ts_now},
            {"type": "postprocess_step", "name": "npc_text_sync",
             "status": "done", "duration_ms": 1820,
             "detail": "gemini-3.1-flash-lite-preview | updated=1 reveals=1 claims=0",
             "ts": ts_now},
            {"type": "postprocess_step", "name": "intent_planner",
             "status": "done", "duration_ms": 1430,
             "detail": "gemini-3.1-flash-lite-preview | cards=2 npcs=2",
             "ts": ts_now},
            {"type": "postprocess_step", "name": "portrait_generation",
             "status": "done", "duration_ms": 5210,
             "detail": "grok-imagine-image | 2/2 done", "ts": ts_now},
            {"type": "postprocess_step", "name": "phase3_complete",
             "status": "done", "duration_ms": 8740,
             "detail": "phase 3 settled", "ts": ts_now},
        ]

        gm_msg_id = str(uuid.uuid4())
        gm_msg = Message(
            id=gm_msg_id,
            session_id=session_id,
            role="gm",
            content=_GM_MESSAGE,
            metadata_json={
                "phase": "ic",
                "scene_key": "scene_gas_station",
                "scene_name": "埃索加油站",
                "current_time": {
                    "day_count": 1,
                    "in_game_time": "12:30",
                    "in_game_period": "afternoon",
                },
                "demo": True,
                "postprocess_steps": seeded_steps,
                "postprocess_done": True,
                "name_reveals": [{
                    "npc_key": "gas_owner",
                    "name": "拉斯·罗素",
                    "reason": "工卡上的名字露出来了",
                    "flipped": True,
                }],
            },
        )
        db.add(gm_msg)

        # Add a leading user message so the conversation reads naturally
        # in the chat panel.
        user_msg = Message(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="user",
            content="我走过去看看那家加油站，找老板打听一下镇里最近的事。",
            metadata_json={"phase": "ic"},
        )
        db.add(user_msg)
        flag_modified(session, "memory_state")
        await db.commit()

    print(f"Created demo session id: {session_id}")
    print()
    print("How to view:")
    print("  1. Open the frontend (http://localhost:3010)")
    print("  2. Open the rooms panel — the demo session is at the top")
    print(f"     (title: '{_DEMO_TITLE}')")
    print("  3. The single GM message contains:")
    print("     - [CREATE_NPC] (state-only, hidden in prose)")
    print("     - [npc_card]   → heavy card with portrait placeholder")
    print("     - [speak]      → tinted dialogue with avatar")
    print("     - [name_reveal] → light chip with speaker color")
    print("     - **拉斯·罗素** in narration (colored via name-mention pass)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
