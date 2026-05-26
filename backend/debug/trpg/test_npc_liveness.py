from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from services.trpg_npc.liveness import (  # noqa: E402
    LatencyBudget,
    apply_hot_patches_preview,
    build_liveness_pre_turn_bundle,
    liveness_card_from_npc,
    preview_mode,
    retrieve_salient_memories,
)
from services.trpg_npc.liveness.expression_mask import ExpressionMaskEngine  # noqa: E402


class LivenessTests(unittest.TestCase):
    def test_hot_patch_affects_preview_state_without_mutating_original(self):
        state = {"npc_id": "keeper", "mood": {"fear": 0.2, "stress": 0.1}, "goal_pressure": {}}
        effective = apply_hot_patches_preview({"keeper": state}, [{
            "npc_id": "keeper",
            "mood_delta": {"fear": 0.5, "stress": 0.4},
            "goal_pressure_delta": {"protect_secret": 0.6},
        }])

        self.assertAlmostEqual(state["mood"]["fear"], 0.2)
        self.assertAlmostEqual(effective["keeper"]["mood"]["fear"], 0.7)
        self.assertAlmostEqual(effective["keeper"]["goal_pressure"]["protect_secret"], 0.6)

    def test_same_fear_different_persona_has_different_expression(self):
        state = {"npc_id": "n", "mood": {"fear": 0.8, "stress": 0.7}}
        liveness = liveness_card_from_npc({"key": "n", "summary": "witness"})
        engine = ExpressionMaskEngine()

        panic = engine.compile(
            profile={"npc_id": "n", "persona": {"impulse_control": 0.2, "deception_skill": 0.1}},
            state=state,
            relationship={},
            liveness=liveness,
        )
        controlled = engine.compile(
            profile={"npc_id": "n", "persona": {"impulse_control": 0.8, "deception_skill": 0.8}},
            state=state,
            relationship={},
            liveness=liveness,
        )

        self.assertEqual(panic.mask_id, "visible_panic")
        self.assertEqual(controlled.mask_id, "controlled_evasion")

    def test_memory_salience_retrieves_relevant_memory(self):
        npc = {"key": "keeper", "memories_v2": [
            {"memory_id": "old_help", "content": "玩家之前保护过店主。", "importance": 0.8, "tags": ["help"]},
            {"memory_id": "noise", "content": "天气很好。", "importance": 0.1, "tags": []},
        ]}
        memories = retrieve_salient_memories(npc, player_text="我说我会保护你", recent_events=[], limit=2)

        self.assertTrue(memories)
        self.assertEqual(memories[0].memory_id, "old_help")
        self.assertIn("语气会软化", memories[0].influence)

    def test_preview_mode_shifts_to_guarding_secret(self):
        mode = preview_mode(
            profile={"npc_id": "keeper"},
            state={
                "current_mode": "normal",
                "mood": {"suspicion": 0.8},
                "goal_pressure": {"protect_secret": 0.9},
            },
            relationship={"trust": 0.2},
            recent_events=[{"type": "ASKED_SENSITIVE_QUESTION"}],
        )
        self.assertEqual(mode, "guarding_secret")

    def test_liveness_bundle_adds_policy_and_beats(self):
        active = [{
            "key": "keeper",
            "player_known_name": "店主",
            "summary": "店主知道失踪学生的线索。",
            "memories_v2": [{"memory_id": "m1", "content": "玩家展示过蛇形徽记。", "importance": 0.7, "tags": ["symbol"]}],
        }]
        profile = SimpleNamespace(npc_id="keeper", narrative_role="clue_holder", persona={"deception_skill": 0.6})
        state = SimpleNamespace(npc_id="keeper", current_mode="normal", mood={"fear": 0.2, "suspicion": 0.4, "stress": 0.3}, goal_pressure={})
        effective, bundle = build_liveness_pre_turn_bundle(
            active_npcs=active,
            profiles_by_id={"keeper": profile},
            states_by_id={"keeper": state},
            relationships_by_npc={"keeper": {"pc": {"trust": 0.3}}},
            hot_patches=[{"npc_id": "keeper", "mood_delta": {"stress": 0.5}, "goal_pressure_delta": {"protect_secret": 0.8}}],
            player_text="我问店主这个蛇形徽记和失踪学生有什么关系",
            recent_events=[{"type": "ASKED_SENSITIVE_QUESTION", "payload": {"topic_tags": ["symbol"]}}],
            budget=LatencyBudget(max_foreground_npcs=1, max_liveness_beats=1),
        )

        self.assertIn("keeper", bundle.policies_by_npc)
        self.assertTrue(bundle.liveness_beats)
        self.assertEqual(getattr(effective["keeper"], "current_mode"), "guarding_secret")
        self.assertIn("move_private", bundle.policies_by_npc["keeper"].preferred_tactics)
        prompt_memory = bundle.to_prompt_metadata()["salient_memories"]["keeper"][0]
        self.assertNotIn("content", prompt_memory)
        self.assertIn("influence", prompt_memory)


if __name__ == "__main__":
    unittest.main()
