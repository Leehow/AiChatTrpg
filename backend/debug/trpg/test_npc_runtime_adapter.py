"""Smoke tests for the NPC Runtime V2 adapter."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from services.trpg_npc.runtime_adapter import (
    build_npc_pre_turn_runtime,
    prompt_safe_active_npcs,
    warm_npc_action_board_after_turn,
)
from services.trpg_scene_runtime import build_ic_context


def _session() -> SimpleNamespace:
    return SimpleNamespace(
        id="session_1",
        user_id="user_1",
        last_summarized_msg_count=2,
        narrative_summary="",
        module_state={
            "scene": "tavern",
            "objective": "find the missing student lead",
            "day_count": 1,
            "in_game_time": "21:00",
        },
        memory_state={
            "current_scene": "tavern",
            "npcs": [
                {
                    "key": "keeper",
                    "name": "Elaine Marsh",
                    "player_known_name": "店主",
                    "name_revealed": False,
                    "role": "clue holder shopkeeper",
                    "summary": "Knows about the missing student.",
                    "inner_state": {
                        "emotional_state": "wary",
                        "motivation": "protect herself",
                        "secret_agenda": "hide the cult ledger",
                    },
                    "player_knowledge": {
                        "interest": 7,
                        "relationship": "stranger",
                    },
                }
            ],
        },
    )


class NPCRuntimeAdapterTests(unittest.TestCase):
    def test_pre_turn_builds_beat_plan(self):
        session = _session()
        active = session.memory_state["npcs"]
        result = build_npc_pre_turn_runtime(
            session,
            player_text="我问店主失踪学生和邪教符号的事",
            active_npcs=active,
            turn_id=3,
        )

        self.assertIsNotNone(result.beat_plan)
        self.assertEqual(result.target_ids, ["keeper"])
        self.assertTrue(result.beat_plan.must_include_beats)
        event_types = {
            event["type"]
            for event in result.beat_plan.metadata.get("classified_player_events", [])
        }
        self.assertIn("ASKED_SENSITIVE_QUESTION", event_types)
        self.assertIsNotNone(result.scene_state)
        self.assertIn(
            "secret:keeper:agenda",
            result.scene_state.plot_contract.forbidden_reveals,
        )
        liveness = result.beat_plan.metadata.get("npc_liveness", {})
        self.assertIn("keeper", liveness.get("policies", {}))
        self.assertTrue(liveness.get("liveness_beats"))

    def test_prompt_safe_projection_does_not_leak_secret_agenda(self):
        safe = prompt_safe_active_npcs(_session().memory_state["npcs"])

        self.assertEqual(safe[0]["display_name"], "店主")
        # `name` is exposed but in-place-masked: when name_revealed=False
        # and a public label exists, the projected `name` equals
        # player_known_name. The true name never reaches this dict.
        self.assertEqual(safe[0]["name"], "店主")
        self.assertFalse(safe[0]["name_revealed"])
        self.assertNotIn("secret_agenda", safe[0].get("inner_state", {}))
        self.assertNotIn("motivation", safe[0].get("inner_state", {}))

    def test_build_ic_context_injects_npc_beat_plan(self):
        ctx = build_ic_context(
            _session(),
            player_text="我问店主失踪学生和邪教符号的事",
            turn_id=3,
        )

        self.assertIn("## NPC Beat Plan", ctx.extras_text)
        self.assertIn("```json", ctx.extras_text)
        self.assertEqual(ctx.active_npcs[0]["display_name"], "店主")
        self.assertNotIn("secret_agenda", ctx.active_npcs[0].get("inner_state", {}))
        self.assertNotIn("motivation", ctx.active_npcs[0].get("inner_state", {}))

    def test_post_turn_warms_action_board_for_next_turn(self):
        session = _session()
        warm = warm_npc_action_board_after_turn(
            session,
            player_text="我问店主失踪学生的事",
            gm_reply="店主压低声音，拒绝在大厅里谈。",
            turn_id=3,
        )

        self.assertTrue(warm.planned_card_ids)
        self.assertIn("_npc_action_board_v2", session.memory_state)
        self.assertGreater(warm.runtime_writeback["states"], 0)
        self.assertGreater(warm.runtime_writeback["relationships"], 0)
        self.assertGreater(warm.runtime_writeback["memories"], 0)

        npc = session.memory_state["npcs"][0]
        self.assertGreater(npc["runtime_state_v2"]["state_version"], 0)
        self.assertIn("pc", npc["relationships_v2"])
        self.assertTrue(npc["memories_v2"])

        next_turn = build_npc_pre_turn_runtime(
            session,
            player_text="我继续问邪教符号",
            active_npcs=session.memory_state["npcs"],
            turn_id=4,
        )
        self.assertTrue(next_turn.pre_turn.matched_card_ids)
        self.assertTrue(next_turn.pre_turn.action_board_matches)
        self.assertEqual(
            next_turn.pre_turn.action_board_matches[0]["card_id"],
            next_turn.pre_turn.matched_card_ids[0],
        )
        self.assertTrue(next_turn.pre_turn.action_board_matches[0]["matched_triggers"])
        self.assertTrue(next_turn.pre_turn.action_board_resolutions)
        self.assertEqual(
            next_turn.pre_turn.action_board_resolutions[0]["card_id"],
            next_turn.pre_turn.matched_card_ids[0],
        )
        self.assertIn(
            next_turn.pre_turn.action_board_resolutions[0]["decision"],
            {"allow", "block", "transform"},
        )
        self.assertEqual(
            next_turn.states_by_id["keeper"].state_version,
            npc["runtime_state_v2"]["state_version"],
        )

    def test_pre_turn_reads_persisted_v2_state_and_relationship(self):
        session = _session()
        npc = session.memory_state["npcs"][0]
        npc["runtime_state_v2"] = {
            "npc_id": "keeper",
            "scene_id": "tavern",
            "location_id": "tavern",
            "status": "active",
            "current_mode": "cornered",
            "mood": {"fear": 0.91, "stress": 0.82, "suspicion": 0.76},
            "goal_pressure": {"protect_secret": 0.95},
            "physical_state": {"wounded": False},
            "active_flags": {"saw_pc_symbol": True},
            "state_version": 7,
            "updated_at": "2026-04-28T00:00:00+00:00",
        }
        npc["relationships_v2"] = {
            "pc": {"trust": 0.12, "suspicion": 0.88, "affinity": -0.2},
        }

        result = build_npc_pre_turn_runtime(
            session,
            player_text="我继续问店主邪教符号",
            active_npcs=session.memory_state["npcs"],
            turn_id=8,
        )

        state = result.states_by_id["keeper"]
        relationship = result.relationships_by_npc["keeper"]["pc"]
        self.assertEqual(state.state_version, 7)
        self.assertEqual(state.current_mode, "cornered")
        self.assertAlmostEqual(state.mood.fear, 0.91)
        self.assertEqual(state.active_flags["saw_pc_symbol"], True)
        self.assertAlmostEqual(relationship.trust, 0.12)
        self.assertAlmostEqual(relationship.suspicion, 0.88)

    def test_chinese_importance_keywords_promote_runtime_tier(self):
        session = _session()
        session.memory_state["npcs"] = [
            {
                "key": "serpent_priestess",
                "name": "艾尔伊希娅",
                "summary": "蛇人，伊格的女祭司，守护伊格神庙与转化室。",
                "last_seen_scene": "tavern",
            },
            {
                "key": "detective_ray",
                "name": "雷·哈兰警探",
                "summary": "奥斯汀警察局旧识，是可靠信息来源。",
                "last_seen_scene": "tavern",
            },
        ]

        result = build_npc_pre_turn_runtime(
            session,
            player_text="我观察这两个人的反应",
            active_npcs=session.memory_state["npcs"],
            turn_id=3,
        )

        self.assertEqual(
            result.profiles_by_id["serpent_priestess"].tier.value,
            "L2_SUPPORTING",
        )
        self.assertEqual(
            result.profiles_by_id["serpent_priestess"].narrative_role,
            "antagonist",
        )
        self.assertEqual(
            result.profiles_by_id["detective_ray"].tier.value,
            "L2_SUPPORTING",
        )
        self.assertEqual(
            result.profiles_by_id["detective_ray"].narrative_role,
            "clue_holder",
        )


if __name__ == "__main__":
    unittest.main()
