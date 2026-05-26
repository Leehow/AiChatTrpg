from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.trpg_npc.optimization.action_board_guard import filter_action_cards_for_turn
from services.trpg_npc.optimization.event_classifier import classify_player_text_to_events
from services.trpg_npc.optimization.memory_compaction import compact_npc_memories
from services.trpg_npc.optimization.safe_projection import (
    prompt_safe_active_npcs_hardened,
    scan_prompt_safety_violations,
)
from services.trpg_npc.optimization.secret_guard import ForbiddenContentGuard, ForbiddenFact
from services.trpg_npc.optimization.writeback_guard import (
    RuntimeWritebackPolicy,
    apply_runtime_snapshot_guarded,
)


class NPCRuntimeHardeningTests(unittest.TestCase):
    def test_safe_projection_whitelists_nested_fields(self):
        active = [
            {
                "key": "keeper",
                "name": "Elaine Marsh",
                "player_known_name": "店主",
                "name_revealed": False,
                "role": "clue holder",
                "summary": "She runs the tavern and seems wary.",
                "private_card": {"true_goal": "hide the ledger"},
                "plot_constraints": {"forbidden_fact_ids": ["secret_core"]},
                "inner_state": {
                    "emotional_state": "wary",
                    "motivation": "protect herself",
                    "secret_agenda": "hide the cult ledger",
                    "gm_notes": "will betray the PCs",
                },
                "runtime_state_v2": {
                    "current_mode": "guarded",
                    "mood": {"fear": 0.8, "suspicion": 0.7, "secret_pressure": 1.0},
                    "goal_pressure": {"protect_secret": 0.9},
                },
            }
        ]

        safe = prompt_safe_active_npcs_hardened(active)

        self.assertEqual(safe[0]["display_name"], "店主")
        # `name` is now exposed but masked: when name_revealed=False and a
        # public label exists, the projected `name` equals player_known_name
        # so the GM cannot read the true name through this field.
        self.assertEqual(safe[0]["name"], "店主")
        self.assertNotEqual(safe[0]["name"], "Elaine Marsh")
        self.assertFalse(safe[0]["name_revealed"])
        self.assertNotIn("private_card", safe[0])
        self.assertNotIn("plot_constraints", safe[0])
        self.assertNotIn("motivation", safe[0].get("inner_state", {}))
        self.assertFalse(scan_prompt_safety_violations(safe))

    def test_safe_projection_does_not_fallback_to_private_summary(self):
        safe = prompt_safe_active_npcs_hardened([
            {
                "key": "keeper",
                "player_known_name": "店主",
                "summary": "GM note: Elaine is the cult leader and final villain.",
            },
            {
                "key": "witness",
                "player_known_name": "证人",
                "appearance": "脸色苍白，反复确认门口有没有人。",
                "summary": "真正目标是隐藏核心秘密。",
            },
        ])

        self.assertNotIn("summary", safe[0])
        self.assertEqual(safe[1]["summary"], "脸色苍白，反复确认门口有没有人。")

    def test_event_classifier_handles_chinese_paraphrase(self):
        active = [{"key": "keeper", "player_known_name": "店主", "role": "店主"}]
        events = classify_player_text_to_events(
            "我把那个奇怪蛇形徽记画给店主看，问她和失踪学生有没有关系",
            active,
            scene_id="tavern",
            turn_id=4,
        )

        event_types = {event["type"] for event in events}
        self.assertIn("ASKED_SENSITIVE_QUESTION", event_types)
        self.assertIn("DISPLAYED_EVIDENCE", event_types)
        self.assertEqual(events[0]["target_ids"], ["keeper"])
        topic_tags = set().union(*(set(event["payload"]["topic_tags"]) for event in events))
        self.assertIn("symbol", topic_tags)
        self.assertIn("missing_person", topic_tags)

    def test_action_board_prefers_structured_event_and_rejects_wrong_scene(self):
        events = [
            {
                "type": "ASKED_SENSITIVE_QUESTION",
                "scene_id": "tavern",
                "turn_id": 5,
                "target_ids": ["keeper"],
                "payload": {"confidence": 0.8, "topic_tags": ["cult", "symbol"]},
            }
        ]
        cards = [
            {
                "card_id": "card_ok",
                "npc_id": "keeper",
                "scene_id": "tavern",
                "priority": 0.6,
                "based_on_turn_id": 4,
                "valid_until_turn": 6,
                "trigger_conditions": [
                    {"event_type": "ASKED_SENSITIVE_QUESTION", "topic_tags": ["symbol"], "require_target": True}
                ],
            },
            {
                "card_id": "card_wrong_scene",
                "npc_id": "keeper",
                "scene_id": "street",
                "priority": 1.0,
                "based_on_turn_id": 4,
                "valid_until_turn": 6,
                "trigger_conditions": ["player_asks_sensitive_question"],
            },
        ]

        matches = filter_action_cards_for_turn(
            cards,
            events=events,
            player_text="我问邪教符号",
            current_turn=5,
            current_scene_id="tavern",
        )

        self.assertEqual([match.card_id for match in matches], ["card_ok"])

    def test_secret_guard_transforms_forbidden_text_and_blocks_high_risk(self):
        guard = ForbiddenContentGuard([
            ForbiddenFact(
                "secret_leader",
                label="Elaine is the cult leader",
                redaction_terms=("Elaine", "cult leader"),
            ),
        ])

        decision = guard.sanitize_action({
            "action_type": "SAY",
            "speech_intent": "Tell the PC that Elaine is the cult leader.",
            "emote": "She looks away.",
        })
        self.assertEqual(decision.decision, "transform")
        self.assertIn("[受保护秘密]", decision.action["speech_intent"])

        blocked = guard.sanitize_action({
            "action_type": "REVEAL_SECRET",
            "speech_intent": "Elaine is the cult leader.",
        })
        self.assertEqual(blocked.decision, "block")

    def test_writeback_guard_rejects_stale_state_and_applies_newer_state(self):
        session = SimpleNamespace(
            memory_state={"npcs": [{"key": "keeper", "runtime_state_v2": {"state_version": 5}}]}
        )

        result = apply_runtime_snapshot_guarded(
            session,
            states=[
                {
                    "npc_id": "keeper",
                    "scene_id": "tavern",
                    "based_on_turn_id": 1,
                    "state_json": {"npc_id": "keeper", "state_version": 4},
                },
                {
                    "npc_id": "keeper",
                    "scene_id": "tavern",
                    "based_on_turn_id": 5,
                    "state_json": {"npc_id": "keeper", "state_version": 6},
                },
            ],
            current_turn=5,
            current_scene_id="tavern",
            policy=RuntimeWritebackPolicy(max_background_lag_turns=2),
        )

        self.assertEqual(result.applied["states"], 1)
        self.assertEqual(len(result.rejected), 1)
        self.assertEqual(session.memory_state["npcs"][0]["runtime_state_v2"]["state_version"], 6)

    def test_writeback_guard_ignores_legacy_string_npc_entries(self):
        session = SimpleNamespace(
            memory_state={
                "npcs": [
                    "legacy prose accidentally appended to npcs",
                    {"key": "keeper", "runtime_state_v2": {"state_version": 1}},
                ]
            }
        )

        result = apply_runtime_snapshot_guarded(
            session,
            states=[{
                "npc_id": "keeper",
                "scene_id": "tavern",
                "based_on_turn_id": 2,
                "state_json": {"npc_id": "keeper", "state_version": 2},
            }],
            current_turn=2,
            current_scene_id="tavern",
            policy=RuntimeWritebackPolicy(max_background_lag_turns=2),
        )

        self.assertEqual(result.applied["states"], 1)
        self.assertEqual(len(session.memory_state["npcs"]), 1)
        self.assertEqual(session.memory_state["npcs"][0]["key"], "keeper")

    def test_memory_compaction_keeps_recent_and_important(self):
        memories = [
            {"memory_id": f"m{i}", "content": f"memory {i}", "turn_id": i, "importance": 0.1}
            for i in range(20)
        ]
        memories[0]["importance"] = 1.0

        compact = compact_npc_memories(memories, max_recent=4, max_important=4)

        kept_ids = {memory["memory_id"] for memory in compact.kept}
        self.assertIn("m0", kept_ids)
        self.assertIn("m19", kept_ids)
        self.assertLess(len(compact.kept), len(memories))
        self.assertGreater(compact.dropped_count, 0)
        self.assertIsNotNone(compact.archived_summary)


if __name__ == "__main__":
    unittest.main()
