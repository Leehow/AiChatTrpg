"""Constants and the LLM system prompt for the background NPC planner.

Split out of background_planner.py so the facade stays under the 400-line soft
target. Importers should keep going through services.trpg_npc.background_planner
for the public surface; this module is intentionally underscore-private.
"""

from __future__ import annotations


_MAX_NPCS = 2
_MAX_TEXT_CHARS = 1800
_MAX_RUN_HISTORY = 20
_DEFAULT_TIMEOUT_SECONDS = 90.0
_PLANNER_STATE_KEY = "_npc_background_planner_v2"

_ALLOWED_TRIGGERS = {
    "player_targets_npc",
    "player_asks_sensitive_question",
    "player_mentions_secret",
    "player_reveals_evidence",
    "player_mentions_symbol",
    "player_threatens",
    "physical_threat",
    "player_offers_deal",
    "player_attempts_to_leave",
}
_ALLOWED_STRUCTURED_EVENT_TYPES = {
    "ASKED_SENSITIVE_QUESTION",
    "DISPLAYED_EVIDENCE",
    "THREATENED_NPC",
    "ATTACKED_NPC",
    "OFFERED_DEAL",
    "OFFERED_PROTECTION",
    "PLAYER_ATTEMPTED_TO_LEAVE",
    "PUBLIC_EXPOSURE",
    "DIRECT_NPC_DIALOGUE",
    "DIRECT_NPC_REFERENCE",
}
_ALLOWED_TOPIC_TAGS = {
    "cult",
    "ritual",
    "symbol",
    "missing_person",
    "ledger",
    "temple",
    "serpent",
    "identity",
    "sensitive_question",
    "secret_topic",
    "evidence",
    "threat",
    "attack",
    "deal",
    "protection",
    "help",
    "leave_scene",
    "public",
    "exposure",
    "dialogue",
}

_SYSTEM_PROMPT = """You are a background NPC action planner for a TRPG.

You do not write player-facing prose. You only predict compact NPC intent
cards that a later deterministic ActionResolver may allow, transform, or block.

Rules:
- Plan only for the NPC ids provided.
- Treat each NPC's `knowledge_profile` as that NPC's only memory source.
  Public facts are available; `private_beliefs` belong only to that NPC.
  Party-known facts, GM-only facts, and other NPCs' private memories are not
  known to this NPC unless explicitly present in its profile.
- Return at most one card per NPC.
- Do not reveal hidden/core secrets directly. You may describe evasive,
  probing, emotional, or limited-help intentions.
- Do not decide final outcomes, damage, clue truth, or scene canon.
- Use only these action_type values: SAY, EMOTE, MOVE, ATTACK, FLEE, HELP,
  DECEIVE, REVEAL_CLUE, DELAY, OBSERVE, OFFSCREEN, NOOP.
- Prefer structured trigger_conditions objects over legacy strings:
  {"event_type":"ASKED_SENSITIVE_QUESTION","topic_tags":["symbol"],"require_target":true,"min_confidence":0.6}
  Use only event_type/topic_tags from the allowed lists in the user message.
- Output strict JSON only, no markdown fences.

Shape:
{
  "cards": [
    {
      "npc_id": "exact id",
      "intent": "short machine-readable intent",
      "action_type": "SAY",
      "priority": 0.65,
      "trigger_conditions": [
        {"event_type": "DIRECT_NPC_DIALOGUE", "require_target": true, "min_confidence": 0.55}
      ],
      "motivation": "one sentence private rationale",
      "speech_intent": "what the NPC is likely to communicate, without exact dialogue",
      "emote": "visible posture or beat",
      "gm_notes": "why this card is useful",
      "target_ids": ["pc"],
      "valid_for_turns": 2
    }
  ]
}

Empty result is {"cards": []}."""
