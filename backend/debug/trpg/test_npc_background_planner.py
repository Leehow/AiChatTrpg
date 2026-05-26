"""Smoke tests for Phase 7 background NPC planner helpers."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from services.trpg_npc.background_planner import (
    append_background_planner_observation,
    background_planner_snapshot,
    build_background_planner_prompt,
    build_cards_from_planner_response,
    build_cards_from_planner_response_detailed,
    compact_background_planner_summary,
    select_background_planner_npc_ids,
)
from services.trpg_context.models import ActorScope, ContextProfile, Visibility
from services.trpg_memory.memory_models import MemoryItem, MemoryKind, TruthStatus
from services.trpg_memory.memory_store import InMemoryMemoryStore
from services.trpg_npc.knowledge_profile import NPCKnowledgeProfileBuilder
from services.trpg_npc.models import ActionType, NPCProfile, NPCTier, PlotConstraints


def _profiles() -> dict[str, NPCProfile]:
    return {
        "bystander": NPCProfile(
            npc_id="bystander",
            name="Bystander",
            tier=NPCTier.MINOR,
        ),
        "keeper": NPCProfile(
            npc_id="keeper",
            name="Elaine Marsh",
            tier=NPCTier.SUPPORTING,
            narrative_role="gatekeeper",
            knowledge_fact_ids=["fact_safe_clue"],
            plot_constraints=PlotConstraints(
                forbidden_fact_ids=["fact_forbidden"],
                core_secret_ids=["secret_core"],
            ),
        ),
        "villain": NPCProfile(
            npc_id="villain",
            name="The Preacher",
            tier=NPCTier.MAJOR,
            narrative_role="antagonist",
        ),
    }


class NPCBackgroundPlannerTests(unittest.TestCase):
    def test_selects_major_then_supporting_active_npcs(self):
        selected = select_background_planner_npc_ids(
            _profiles(),
            active_npcs=[
                {"key": "keeper"},
                {"key": "bystander"},
                {"key": "villain"},
            ],
            max_npcs=2,
        )

        self.assertEqual(selected, ["villain", "keeper"])

    def test_builds_cards_from_strict_json_response(self):
        raw = json.dumps({
            "cards": [
                {
                    "npc_id": "keeper",
                    "intent": "deflect_about_ledger",
                    "action_type": "DECEIVE",
                    "priority": 0.72,
                    "trigger_conditions": [
                        "player_asks_sensitive_question",
                        "not_allowed_trigger",
                    ],
                    "motivation": "Protect the ledger without making the PC suspicious.",
                    "speech_intent": "Offer a partial truth and ask what the PC already knows.",
                    "emote": "She glances toward the kitchen door.",
                    "gm_notes": "Use if the PC presses about the ledger.",
                    "target_ids": ["pc"],
                    "known_fact_ids": ["fact_safe_clue", "fact_unknown"],
                    "valid_for_turns": 2,
                },
                {
                    "npc_id": "unknown",
                    "intent": "ignored",
                    "action_type": "ATTACK",
                },
            ]
        })

        cards = build_cards_from_planner_response(
            raw,
            profiles_by_id=_profiles(),
            based_on_turn_id=5,
        )

        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card.npc_id, "keeper")
        self.assertEqual(card.based_on_turn_id, 5)
        self.assertEqual(card.valid_until_turn, 7)
        self.assertEqual(card.preferred_action.action_type, ActionType.DECEIVE)
        self.assertEqual(card.trigger_conditions, ["player_asks_sensitive_question"])
        self.assertEqual(card.known_fact_ids, ["fact_safe_clue"])
        self.assertIn("fact_forbidden", card.forbidden_fact_ids)
        self.assertIn("secret_core", card.forbidden_fact_ids)
        self.assertEqual(card.metadata["planner"], "llm_background")

    def test_detailed_card_build_reports_rejected_and_trigger_counts(self):
        raw = json.dumps({
            "cards": [
                {
                    "npc_id": "keeper",
                    "intent": "react_to_symbol",
                    "action_type": "SAY",
                    "trigger_conditions": [
                        {"event_type": "ASKED_SENSITIVE_QUESTION", "topic_tags": ["symbol"]},
                    ],
                    "speech_intent": "Ask where the PC found the sigil.",
                },
                {"npc_id": "unknown", "intent": "ignored"},
                {"npc_id": "keeper", "intent": "duplicate"},
                "bad card",
            ]
        })

        result = build_cards_from_planner_response_detailed(
            raw,
            profiles_by_id=_profiles(),
            based_on_turn_id=5,
        )
        diagnostics = result.diagnostics.to_dict()

        self.assertEqual(len(result.cards), 1)
        self.assertEqual(diagnostics["raw_card_count"], 4)
        self.assertEqual(diagnostics["accepted_card_count"], 1)
        self.assertEqual(diagnostics["unknown_npc_count"], 1)
        self.assertEqual(diagnostics["duplicate_npc_count"], 1)
        self.assertEqual(diagnostics["invalid_card_count"], 1)
        self.assertEqual(diagnostics["structured_trigger_count"], 1)
        self.assertEqual(diagnostics["legacy_trigger_count"], 0)

    def test_secret_guard_transforms_planner_card_text(self):
        profile = NPCProfile(
            npc_id="keeper",
            name="Elaine Marsh",
            tier=NPCTier.SUPPORTING,
            private_card={"secret_agenda": "Elaine is the cult leader"},
            plot_constraints=PlotConstraints(forbidden_fact_ids=["secret_leader"]),
        )
        raw = json.dumps({
            "cards": [
                {
                    "npc_id": "keeper",
                    "intent": "answer_about_leader",
                    "action_type": "SAY",
                    "priority": 0.7,
                    "trigger_conditions": ["player_asks_sensitive_question"],
                    "motivation": "Elaine is the cult leader, so she hides it.",
                    "speech_intent": "Tell the PC that Elaine is the cult leader.",
                    "emote": "She looks away.",
                    "gm_notes": "This card names Elaine is the cult leader.",
                }
            ]
        })

        cards = build_cards_from_planner_response(
            raw,
            profiles_by_id={"keeper": profile},
            based_on_turn_id=3,
        )

        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card.metadata["secret_guard"]["decision"], "transform")
        self.assertIn("[受保护秘密]", card.preferred_action.player_facing["speech_intent"])

    def test_background_prompt_uses_npc_knowledge_profile_only(self):
        store = InMemoryMemoryStore([
            MemoryItem(
                memory_id="m_public",
                campaign_id="session_1",
                kind=MemoryKind.FACT,
                text="The door is red.",
                visibility=Visibility.PUBLIC,
                owner_id=None,
                subject_ids=("door",),
                source_turn_ids=("t1",),
            ),
            MemoryItem(
                memory_id="m_party",
                campaign_id="session_1",
                kind=MemoryKind.CLUE,
                text="The party found the hidden knife.",
                visibility=Visibility.PARTY_KNOWN,
                owner_id=None,
                subject_ids=("knife",),
                source_turn_ids=("t1",),
            ),
            MemoryItem(
                memory_id="m_belief",
                campaign_id="session_1",
                kind=MemoryKind.BELIEF,
                text="Elaine suspects the party is lying.",
                visibility=Visibility.NPC_PRIVATE,
                owner_id="keeper",
                subject_ids=("party",),
                source_turn_ids=("t1",),
                truth_status=TruthStatus.BELIEF,
            ),
            MemoryItem(
                memory_id="m_secret",
                campaign_id="session_1",
                kind=MemoryKind.SECRET,
                text="The butler is the killer.",
                visibility=Visibility.GM_ONLY,
                owner_id=None,
                subject_ids=("butler",),
                source_turn_ids=("module",),
            ),
        ])
        knowledge = NPCKnowledgeProfileBuilder(store).build(
            actor=ActorScope(
                profile=ContextProfile.NPC,
                campaign_id="session_1",
                session_id="session_1",
                npc_id="keeper",
            )
        )

        prompt = build_background_planner_prompt(
            profiles_by_id={"keeper": _profiles()["keeper"]},
            states_by_id={},
            relationships_by_npc={},
            knowledge_profiles_by_npc_id={"keeper": knowledge.prompt_payload()},
            scene_id="tavern",
            turn_id=7,
            player_text="I listen at the door.",
            gm_reply="The room falls quiet.",
        )

        self.assertIn("The door is red.", prompt)
        self.assertIn("Elaine suspects the party is lying.", prompt)
        self.assertNotIn("hidden knife", prompt)
        self.assertNotIn("butler is the killer", prompt)
        self.assertNotIn("private_card", prompt)

    def test_memory_leak_checker_blocks_planner_card(self):
        profile = NPCProfile(
            npc_id="keeper",
            name="Elaine Marsh",
            tier=NPCTier.SUPPORTING,
        )
        secret = MemoryItem(
            memory_id="m_secret",
            campaign_id="session_1",
            kind=MemoryKind.SECRET,
            text="The butler is the killer.",
            visibility=Visibility.GM_ONLY,
            owner_id=None,
            subject_ids=("butler",),
            source_turn_ids=("module",),
        )
        raw = json.dumps({
            "cards": [
                {
                    "npc_id": "keeper",
                    "intent": "answer_about_butler",
                    "action_type": "SAY",
                    "trigger_conditions": ["player_asks_sensitive_question"],
                    "speech_intent": "Tell the PC that the butler is the killer.",
                }
            ]
        })

        result = build_cards_from_planner_response_detailed(
            raw,
            profiles_by_id={"keeper": profile},
            based_on_turn_id=5,
            forbidden_memories_by_npc_id={"keeper": (secret,)},
        )
        diagnostics = result.diagnostics.to_dict()

        self.assertEqual(result.cards, [])
        self.assertEqual(diagnostics["knowledge_leak_blocked"], 1)
        self.assertGreaterEqual(diagnostics["knowledge_leak_warning_count"], 1)

    def test_builds_structured_trigger_cards_from_planner_response(self):
        raw = json.dumps({
            "cards": [
                {
                    "npc_id": "keeper",
                    "intent": "react_to_symbol",
                    "action_type": "SAY",
                    "priority": 0.7,
                    "trigger_conditions": [
                        {
                            "event_type": "ASKED_SENSITIVE_QUESTION",
                            "topic_tags": ["symbol", "not_allowed"],
                            "require_target": True,
                            "min_confidence": 0.65,
                        }
                    ],
                    "speech_intent": "Ask where the PC found the sigil.",
                    "target_ids": ["pc"],
                }
            ]
        })

        cards = build_cards_from_planner_response(
            raw,
            profiles_by_id=_profiles(),
            based_on_turn_id=5,
        )

        self.assertEqual(len(cards), 1)
        trigger = cards[0].trigger_conditions[0]
        self.assertIsInstance(trigger, dict)
        self.assertEqual(trigger["event_type"], "ASKED_SENSITIVE_QUESTION")
        self.assertEqual(trigger["topic_tags"], ["symbol"])
        self.assertTrue(trigger["require_target"])
        self.assertEqual(trigger["min_confidence"], 0.65)

    def test_compacts_and_stores_planner_observation(self):
        session = SimpleNamespace(id="session_1", memory_state={"npcs": []})
        summary = {
            "mode": "llm_background_action_board",
            "status": "planned",
            "based_on_turn_id": 8,
            "model": "test-model",
            "considered": 3,
            "selected": 2,
            "selected_npc_ids": ["villain", "keeper"],
            "planned": 2,
            "planned_card_ids": ["card_a", "card_b"],
            "persisted_action_cards": 2,
            "structured_trigger_count": 3,
            "legacy_trigger_count": 1,
            "secret_guard_transformed": 1,
            "secret_guard_blocked": 0,
            "invalid_planner_cards": 2,
            "planner_card_build": {
                "raw_card_count": 4,
                "accepted_card_count": 2,
            },
            "json_snapshot": {"action_cards": 2},
            "api_key": "must_not_be_stored",
        }

        compact = compact_background_planner_summary(summary)
        stored = append_background_planner_observation(session, summary)
        snapshot = background_planner_snapshot(session)

        self.assertEqual(compact["status"], "planned")
        self.assertEqual(compact["structured_trigger_count"], 3)
        self.assertEqual(compact["invalid_planner_cards"], 2)
        self.assertEqual(compact["planner_card_build"]["raw_card_count"], 4)
        self.assertNotIn("api_key", compact)
        self.assertEqual(stored["planned_card_ids"], ["card_a", "card_b"])
        self.assertEqual(snapshot["latest"]["based_on_turn_id"], 8)
        self.assertEqual(len(snapshot["runs"]), 1)

    def test_observation_history_is_capped(self):
        session = SimpleNamespace(id="session_1", memory_state={})
        for turn in range(4):
            append_background_planner_observation(
                session,
                {
                    "status": "skipped",
                    "based_on_turn_id": turn,
                    "skipped": "empty_cards",
                },
                max_runs=2,
            )
        snapshot = background_planner_snapshot(session)

        self.assertEqual([run["based_on_turn_id"] for run in snapshot["runs"]], [2, 3])


if __name__ == "__main__":
    unittest.main()
