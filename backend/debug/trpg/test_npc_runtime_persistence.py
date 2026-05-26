"""Smoke tests for NPC Runtime V2 table payload generation."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from services.trpg_npc.models import GameEvent
from services.trpg_npc.runtime_adapter import warm_npc_action_board_after_turn
from services.trpg_npc.runtime_diagnostics import compare_npc_runtime_v2_snapshot
from services.trpg_npc.runtime_persistence import (
    apply_npc_runtime_v2_table_snapshot_to_session,
    build_npc_pre_turn_runtime_from_table_rows,
    build_npc_runtime_v2_table_payloads,
    build_npc_runtime_v2_table_payloads_from_session_snapshot,
)


def _session() -> SimpleNamespace:
    return SimpleNamespace(
        id="session_1",
        user_id="user_1",
        last_summarized_msg_count=2,
        narrative_summary="",
        module_state={
            "scene": "tavern",
            "objective": "find the missing student lead",
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
                    "last_seen_scene": "tavern",
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


class NPCRuntimePersistenceTests(unittest.TestCase):
    def test_builds_table_payloads_from_warm_result(self):
        session = _session()
        structured_event = GameEvent(
            event_id="event_keeper_reacts",
            type="ASKED_SENSITIVE_QUESTION",
            scene_id="tavern",
            turn_id=3,
            actor_id="pc",
            target_ids=["keeper"],
            content="The PC asks the keeper about the cult ledger.",
            payload={"topic": "cult ledger"},
        )
        warm = warm_npc_action_board_after_turn(
            session,
            player_text="我问店主邪教账本在哪里",
            gm_reply="店主脸色一变，压低声音。",
            turn_id=3,
            structured_events=[structured_event],
        )

        payload = build_npc_runtime_v2_table_payloads(session, warm)
        summary = payload.summary()

        self.assertEqual(summary["profiles"], 1)
        self.assertGreaterEqual(summary["states"], 1)
        self.assertGreaterEqual(summary["relationships"], 1)
        self.assertGreaterEqual(summary["memories"], 1)
        self.assertGreaterEqual(summary["action_cards"], 1)
        self.assertEqual(summary["events"], 2)

        state = payload.states[0]
        self.assertEqual(state["session_id"], "session_1")
        self.assertEqual(state["npc_id"], "keeper")
        self.assertGreater(state["state_version"], 0)

        event_types = {row["type"] for row in payload.events}
        self.assertEqual(event_types, {"PLAYER_INPUT", "ASKED_SENSITIVE_QUESTION"})
        card = payload.action_cards[0]
        self.assertEqual(card["session_id"], "session_1")
        self.assertEqual(card["scene_id"], "tavern")
        self.assertEqual(card["npc_id"], "keeper")

    def test_builds_backfill_payloads_from_session_snapshot_and_metadata(self):
        session = _session()
        session.memory_state["npcs"][0]["runtime_state_v2"] = {
            "npc_id": "keeper",
            "scene_id": "tavern",
            "state_version": 4,
            "mood": {"suspicion": 0.8},
        }
        session.memory_state["npcs"][0]["relationships_v2"] = {
            "pc": {"trust": 0.2, "suspicion": 0.9},
        }
        session.memory_state["npcs"][0]["memories_v2"] = [
            {
                "memory_id": "mem_1",
                "npc_id": "keeper",
                "memory_type": "episodic",
                "content": "The PC asked about the ledger.",
                "importance": 0.7,
                "source_event_ids": ["event_1"],
                "tags": ["asked_sensitive_question"],
            }
        ]
        message = SimpleNamespace(
            metadata_json={
                "structured_events": {
                    "events": [
                        {
                            "event_id": "event_1",
                            "type": "ASKED_SENSITIVE_QUESTION",
                            "scene_id": "tavern",
                            "turn_id": 3,
                            "actor_id": "pc",
                            "target_ids": ["keeper"],
                            "content": "The PC asked about the ledger.",
                            "payload": {},
                            "visibility": {"player_visible": True, "gm_visible": True},
                        }
                    ],
                    "errors": [],
                }
            }
        )

        payload = build_npc_runtime_v2_table_payloads_from_session_snapshot(
            session,
            messages=[message],
        )
        summary = payload.summary()

        self.assertEqual(summary["profiles"], 1)
        self.assertEqual(summary["states"], 1)
        self.assertEqual(summary["relationships"], 1)
        self.assertEqual(summary["memories"], 1)
        self.assertEqual(summary["events"], 1)
        self.assertEqual(payload.states[0]["state_version"], 4)
        self.assertEqual(payload.relationships[0]["target_id"], "pc")
        self.assertEqual(payload.memories[0]["memory_id"], "mem_1")

    def test_applies_table_snapshot_to_session_json(self):
        session = _session()
        summary = apply_npc_runtime_v2_table_snapshot_to_session(
            session,
            states=[
                {
                    "npc_id": "keeper",
                    "state_json": {
                        "npc_id": "keeper",
                        "scene_id": "tavern",
                        "state_version": 9,
                    },
                }
            ],
            relationships=[
                {
                    "npc_id": "keeper",
                    "target_id": "pc",
                    "relationship_json": {"trust": 0.11, "suspicion": 0.91},
                }
            ],
            memories=[
                {
                    "npc_id": "keeper",
                    "memory_json": {
                        "memory_id": "mem_table",
                        "npc_id": "keeper",
                        "content": "Table memory.",
                    },
                }
            ],
            action_cards=[
                {
                    "scene_id": "tavern",
                    "card_json": {
                        "card_id": "card_1",
                        "npc_id": "keeper",
                        "based_on_turn_id": 3,
                        "valid_until_turn": 5,
                    },
                }
            ],
        )

        npc = session.memory_state["npcs"][0]
        self.assertEqual(summary["states"], 1)
        self.assertEqual(summary["relationships"], 1)
        self.assertEqual(summary["memories"], 1)
        self.assertEqual(summary["action_cards"], 1)
        self.assertEqual(npc["runtime_state_v2"]["state_version"], 9)
        self.assertEqual(npc["relationships_v2"]["pc"]["trust"], 0.11)
        self.assertEqual(npc["memories_v2"][0]["memory_id"], "mem_table")
        self.assertEqual(
            session.memory_state["_npc_action_board_v2"]["scenes"]["tavern"][0]["card_id"],
            "card_1",
        )

    def test_table_snapshot_guard_rejects_older_state_version(self):
        session = _session()
        session.memory_state["npcs"][0]["runtime_state_v2"] = {
            "npc_id": "keeper",
            "scene_id": "tavern",
            "state_version": 10,
        }

        summary = apply_npc_runtime_v2_table_snapshot_to_session(
            session,
            states=[
                {
                    "npc_id": "keeper",
                    "state_json": {
                        "npc_id": "keeper",
                        "scene_id": "tavern",
                        "state_version": 9,
                    },
                }
            ],
            relationships=[],
            memories=[],
            action_cards=[],
        )

        self.assertEqual(summary["states"], 0)
        self.assertEqual(summary["rejected_writebacks"], 1)
        self.assertEqual(session.memory_state["npcs"][0]["runtime_state_v2"]["state_version"], 10)

    def test_table_snapshot_guard_uses_explicit_current_turn_for_cards(self):
        session = _session()
        session.last_summarized_msg_count = 0

        summary = apply_npc_runtime_v2_table_snapshot_to_session(
            session,
            states=[],
            relationships=[],
            memories=[],
            action_cards=[
                {
                    "scene_id": "tavern",
                    "card_json": {
                        "card_id": "card_turn_8",
                        "npc_id": "keeper",
                        "based_on_turn_id": 8,
                        "valid_until_turn": 10,
                    },
                }
            ],
            current_turn=8,
            current_scene_id="tavern",
        )

        self.assertEqual(summary["action_cards"], 1)
        self.assertNotIn("rejected_writebacks", summary)
        self.assertEqual(
            session.memory_state["_npc_action_board_v2"]["scenes"]["tavern"][0]["card_id"],
            "card_turn_8",
        )

    def test_table_rows_can_drive_pre_turn_without_json_runtime_snapshot(self):
        source_session = _session()
        warm = warm_npc_action_board_after_turn(
            source_session,
            player_text="我问店主失踪学生的事",
            gm_reply="店主压低声音，拒绝在大厅里谈。",
            turn_id=3,
        )
        payload = build_npc_runtime_v2_table_payloads(source_session, warm)

        table_only_session = _session()
        table_only_session.memory_state.pop("_npc_action_board_v2", None)
        table_only_session.memory_state["npcs"][0].pop("runtime_state_v2", None)
        table_only_session.memory_state["npcs"][0].pop("relationships_v2", None)
        table_only_session.memory_state["npcs"][0].pop("memories_v2", None)

        result = build_npc_pre_turn_runtime_from_table_rows(
            table_only_session,
            player_text="我继续问邪教符号",
            active_npcs=table_only_session.memory_state["npcs"],
            turn_id=4,
            profile_rows=payload.profiles,
            state_rows=payload.states,
            relationship_rows=payload.relationships,
            action_card_rows=payload.action_cards,
        )

        self.assertIsNotNone(result.pre_turn)
        self.assertTrue(result.pre_turn.matched_card_ids)
        self.assertEqual(
            result.states_by_id["keeper"].state_version,
            payload.states[0]["state_version"],
        )

    def test_table_profile_does_not_downgrade_active_json_importance(self):
        session = _session()
        warm = warm_npc_action_board_after_turn(
            session,
            player_text="我问店主失踪学生的事",
            gm_reply="店主压低声音，拒绝在大厅里谈。",
            turn_id=3,
        )
        payload = build_npc_runtime_v2_table_payloads(session, warm)
        payload.profiles[0]["tier"] = "L1_MINOR"
        payload.profiles[0]["profile_json"]["tier"] = "L1_MINOR"
        payload.profiles[0]["profile_json"]["narrative_role"] = "ambient"

        result = build_npc_pre_turn_runtime_from_table_rows(
            session,
            player_text="我继续问邪教符号",
            active_npcs=session.memory_state["npcs"],
            turn_id=4,
            profile_rows=payload.profiles,
            state_rows=payload.states,
            relationship_rows=payload.relationships,
            action_card_rows=payload.action_cards,
        )

        self.assertEqual(result.profiles_by_id["keeper"].tier.value, "L2_SUPPORTING")
        self.assertEqual(result.profiles_by_id["keeper"].narrative_role, "clue_holder")

    def test_table_authority_warm_result_builds_payload_without_json_prewrite(self):
        session = _session()
        warm = warm_npc_action_board_after_turn(
            session,
            player_text="我问店主邪教账本在哪里",
            gm_reply="店主脸色一变，压低声音。",
            turn_id=3,
            write_json_snapshot=False,
        )

        npc = session.memory_state["npcs"][0]
        self.assertEqual(warm.runtime_writeback["mode"], "table_authority_pending_snapshot")
        self.assertIsNotNone(warm.action_board)
        self.assertNotIn("_npc_action_board_v2", session.memory_state)
        self.assertNotIn("runtime_state_v2", npc)
        self.assertNotIn("relationships_v2", npc)
        self.assertNotIn("memories_v2", npc)

        payload = build_npc_runtime_v2_table_payloads(session, warm)
        summary = payload.summary()
        self.assertGreaterEqual(summary["states"], 1)
        self.assertGreaterEqual(summary["relationships"], 1)
        self.assertGreaterEqual(summary["memories"], 1)
        self.assertGreaterEqual(summary["action_cards"], 1)

        snapshot_summary = apply_npc_runtime_v2_table_snapshot_to_session(
            session,
            states=payload.states,
            relationships=payload.relationships,
            memories=payload.memories,
            action_cards=payload.action_cards,
        )
        self.assertEqual(snapshot_summary["states"], 1)
        self.assertGreaterEqual(snapshot_summary["relationships"], 1)
        self.assertGreaterEqual(snapshot_summary["memories"], 1)
        self.assertGreaterEqual(snapshot_summary["action_cards"], 1)
        self.assertIn("runtime_state_v2", npc)
        self.assertIn("_npc_action_board_v2", session.memory_state)

    def test_diagnostics_accepts_table_hydrated_snapshot(self):
        session = _session()
        warm = warm_npc_action_board_after_turn(
            session,
            player_text="我问店主邪教账本在哪里",
            gm_reply="店主脸色一变，压低声音。",
            turn_id=3,
            write_json_snapshot=False,
        )
        payload = build_npc_runtime_v2_table_payloads(session, warm)
        apply_npc_runtime_v2_table_snapshot_to_session(
            session,
            states=payload.states,
            relationships=payload.relationships,
            memories=payload.memories,
            action_cards=payload.action_cards,
        )

        diagnostics = compare_npc_runtime_v2_snapshot(
            session,
            profiles=payload.profiles,
            states=payload.states,
            relationships=payload.relationships,
            memories=payload.memories,
            action_cards=payload.action_cards,
            events=payload.events,
        )

        self.assertTrue(diagnostics.ok)
        self.assertEqual(diagnostics.table_counts["states"], 1)
        self.assertEqual(diagnostics.json_counts["states"], 1)

    def test_diagnostics_flags_snapshot_drift(self):
        session = _session()
        warm = warm_npc_action_board_after_turn(
            session,
            player_text="我问店主邪教账本在哪里",
            gm_reply="店主脸色一变，压低声音。",
            turn_id=3,
            write_json_snapshot=False,
        )
        payload = build_npc_runtime_v2_table_payloads(session, warm)
        apply_npc_runtime_v2_table_snapshot_to_session(
            session,
            states=payload.states,
            relationships=payload.relationships,
            memories=payload.memories,
            action_cards=payload.action_cards,
        )
        session.memory_state["npcs"][0]["runtime_state_v2"]["state_version"] += 1
        session.memory_state["_npc_action_board_v2"]["scenes"]["tavern"].append(
            {"card_id": "card_orphan", "npc_id": "keeper"}
        )

        diagnostics = compare_npc_runtime_v2_snapshot(
            session,
            profiles=payload.profiles,
            states=payload.states,
            relationships=payload.relationships,
            memories=payload.memories,
            action_cards=payload.action_cards,
            events=payload.events,
        )
        mismatch_kinds = {item["kind"] for item in diagnostics.mismatches}

        self.assertFalse(diagnostics.ok)
        self.assertIn("state_version_mismatch", mismatch_kinds)
        self.assertIn("json_action_card_missing_table_row", mismatch_kinds)


if __name__ == "__main__":
    unittest.main()
