"""Smoke tests for legacy NPC turn_sync after Runtime V2 downgrade."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

import services.trpg_npc.action_summary as action_summary_module
import services.trpg_npc.turn_sync as turn_sync_module
from services.trpg_npc.turn_sync import (
    collect_runtime_state_versions,
    sync_npcs_after_turn,
)


def _session(*, state_version: int = 2) -> SimpleNamespace:
    return SimpleNamespace(
        id="session_1",
        user_id="user_1",
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
                    "role": "clue holder shopkeeper",
                    "last_seen_scene": "tavern",
                    "inner_state": {
                        "emotional_state": "wary",
                        "motivation": "protect herself",
                        "secret_agenda": "hide the cult ledger",
                    },
                    "player_knowledge": {
                        "interest": 5,
                        "interest_profile": {"band": "medium"},
                    },
                    "runtime_state_v2": {
                        "npc_id": "keeper",
                        "scene_id": "tavern",
                        "state_version": state_version,
                        "mood": {"suspicion": 0.77, "stress": 0.61},
                    },
                }
            ],
        },
    )


class NPCTurnSyncDowngradeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._orig_turn_call = turn_sync_module.call_llm_json_task
        self._orig_summary_call = action_summary_module.call_llm_json_task

        async def fake_call(*, stage, **kwargs):
            if stage == "npc_turn_sync":
                return json.dumps({
                    "npc_updates": [
                        {
                            "key": "keeper",
                            "emotional_state": "guarded but listening",
                            "motivation": "wants the PC to stop asking in public",
                            "interest_delta": -3,
                            "name_revealed": True,
                            "new_action_event": "The keeper lowered her voice and warned the PC.",
                        }
                    ]
                })
            if stage == "npc_action_summary":
                return "The keeper lowered her voice after the PC pressed about the missing student."
            raise AssertionError(f"unexpected stage: {stage}")

        turn_sync_module.call_llm_json_task = fake_call
        action_summary_module.call_llm_json_task = fake_call

    async def asyncTearDown(self):
        turn_sync_module.call_llm_json_task = self._orig_turn_call
        action_summary_module.call_llm_json_task = self._orig_summary_call

    async def test_v2_npc_gets_text_polish_but_not_legacy_interest_delta(self):
        session = _session(state_version=2)

        summary = await sync_npcs_after_turn(
            None,
            session,
            player_text="I ask the keeper about the missing student.",
            gm_reply="The keeper lowers her voice.",
            cfg={"model": "test", "base_url": "http://test", "api_key": "key"},
            based_on_turn_id=4,
            npc_state_versions={"keeper": 2},
        )

        npc = session.memory_state["npcs"][0]
        self.assertEqual(summary["text_polished"], 1)
        self.assertEqual(summary["interest_skipped_v2"], 1)
        self.assertEqual(summary["interest_changed"], 0)
        self.assertEqual(summary["action_summary_updated"], 1)
        self.assertEqual(npc["player_knowledge"]["interest"], 5)
        self.assertEqual(npc["inner_state"]["emotional_state"], "guarded but listening")
        self.assertEqual(
            npc["inner_state"]["motivation"],
            "wants the PC to stop asking in public",
        )
        self.assertTrue(npc["name_revealed"])
        self.assertEqual(
            npc["action_summary"],
            "The keeper lowered her voice after the PC pressed about the missing student.",
        )
        self.assertEqual(npc["turn_sync_v2"]["mode"], "legacy_text_projection")
        self.assertEqual(npc["turn_sync_v2"]["based_on_turn_id"], 4)
        self.assertEqual(npc["turn_sync_v2"]["state_version"], 2)

    async def test_stale_v2_version_skips_legacy_writes(self):
        session = _session(state_version=3)

        summary = await sync_npcs_after_turn(
            None,
            session,
            player_text="I ask the keeper about the missing student.",
            gm_reply="The keeper lowers her voice.",
            cfg={"model": "test", "base_url": "http://test", "api_key": "key"},
            based_on_turn_id=4,
            npc_state_versions={"keeper": 2},
        )

        npc = session.memory_state["npcs"][0]
        self.assertEqual(summary["stale_skipped"], 1)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["action_summary_updated"], 0)
        self.assertEqual(npc["player_knowledge"]["interest"], 5)
        self.assertEqual(npc["inner_state"]["emotional_state"], "wary")
        self.assertFalse(npc["name_revealed"])
        self.assertNotIn("action_summary", npc)
        self.assertNotIn("turn_sync_v2", npc)

    def test_collect_runtime_state_versions(self):
        self.assertEqual(collect_runtime_state_versions(_session(state_version=8)), {"keeper": 8})


class NPCTurnSyncNameClaimTests(unittest.IsolatedAsyncioTestCase):
    """Verify that the post-pass records false / unknown name claims without
    flipping ``name_revealed``, and promotes a claim to a real reveal when
    the claimed name happens to equal the true name."""

    async def _run_with_payload(self, payload: dict) -> SimpleNamespace:
        session = _session(state_version=2)

        async def fake_call(*, stage, **kwargs):
            if stage == "npc_turn_sync":
                return json.dumps(payload)
            if stage == "npc_action_summary":
                return ""
            raise AssertionError(f"unexpected stage: {stage}")

        orig_turn = turn_sync_module.call_llm_json_task
        orig_summary = action_summary_module.call_llm_json_task
        turn_sync_module.call_llm_json_task = fake_call
        action_summary_module.call_llm_json_task = fake_call
        try:
            await sync_npcs_after_turn(
                None,
                session,
                player_text="问她叫什么名字",
                gm_reply="她抬头：「叫我Karen就行。」",
                cfg={"model": "test", "base_url": "http://test", "api_key": "key"},
                based_on_turn_id=5,
                npc_state_versions={"keeper": 2},
            )
        finally:
            turn_sync_module.call_llm_json_task = orig_turn
            action_summary_module.call_llm_json_task = orig_summary
        return session

    async def test_false_claim_records_alias_without_revealing(self):
        session = await self._run_with_payload({
            "npc_updates": [{
                "key": "keeper",
                "name_claim": {
                    "claimed_name": "Karen",
                    "truth_status": "false",
                    "reason": "她说叫她Karen但与真名Elaine Marsh矛盾",
                },
            }]
        })
        npc = session.memory_state["npcs"][0]
        self.assertFalse(npc["name_revealed"])
        self.assertEqual(npc["claimed_name"], "Karen")
        self.assertEqual(npc["name_claim_truth"], "false")
        # Alias surfaces as the public label so next turn's GM uses "Karen".
        self.assertEqual(npc["player_known_name"], "Karen")
        self.assertEqual(len(npc["name_claim_history"]), 1)
        self.assertEqual(npc["name_claim_history"][0]["claimed_name"], "Karen")

    async def test_unknown_truth_status_normalized(self):
        session = await self._run_with_payload({
            "npc_updates": [{
                "key": "keeper",
                "name_claim": {
                    "claimed_name": "Lina",
                    "truth_status": "WHATEVER",
                },
            }]
        })
        npc = session.memory_state["npcs"][0]
        self.assertEqual(npc["name_claim_truth"], "unknown")

    async def test_claim_matching_true_name_promotes_to_reveal(self):
        session = await self._run_with_payload({
            "npc_updates": [{
                "key": "keeper",
                "name_claim": {
                    "claimed_name": "Elaine Marsh",
                    "truth_status": "unknown",
                },
            }]
        })
        npc = session.memory_state["npcs"][0]
        self.assertTrue(npc["name_revealed"])
        self.assertEqual(npc["player_known_name"], "Elaine Marsh")

    async def test_empty_claimed_name_skipped(self):
        session = await self._run_with_payload({
            "npc_updates": [{
                "key": "keeper",
                "name_claim": {"claimed_name": "  ", "truth_status": "false"},
            }]
        })
        npc = session.memory_state["npcs"][0]
        self.assertFalse(npc["name_revealed"])
        self.assertNotIn("claimed_name", npc)


if __name__ == "__main__":
    unittest.main()
