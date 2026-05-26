"""Prompt construction for NPC turn sync.

Builds the system prompt, NPC roster brief, PC brief, and the final user
message handed to the LLM by ``services.trpg_npc.turn_sync``. Also owns
the per-prompt NPC selection heuristic (in-scene first, capped roster).

This module is read-only: it inspects session and NPC dicts but does not
mutate them. Mutation lives in
:mod:`services.trpg_npc.turn_sync_apply`.
"""

from __future__ import annotations

import json
from typing import Any

from orm.models import GameSession
from services.trpg_npc.turn_sync_apply import _runtime_state_version


_MAX_NPCS_IN_PROMPT = 12
_MAX_TEXT_CHARS = 2400


_SYSTEM_PROMPT = """You are the post-turn NPC text observer for a TRPG session.

You see exactly what just happened in this single turn:

- The PC's input (what the player said or did)
- The GM's reply (the resulting narration / dialogue / outcomes)
- The NPC roster with each NPC's current state (mood, motivation,
  interest in the PC, recent behaviour summary)
- Each NPC's `knowledge_profile`. Treat this as the only memory that NPC may
  know: public facts plus that NPC's own private beliefs/relationships.
  Party-known facts and GM-only facts are not NPC knowledge unless they appear
  in this profile.

For every NPC who was actually affected by this turn, output only the
prompt-facing text polish and action-summary inputs that changed.
Do NOT mechanically carry over previous text. Judge what this turn would
make a careful GM update between turns.

Some roster lines include ``runtime_v2_version``. For those NPCs, a
separate deterministic runtime already owns numeric mood, relationship,
memory, and next-action state. For those NPCs, use this pass only to
polish short human-readable mood/motivation text and action_summary input;
do not try to overrule their core state.

## Rules
- Only include NPCs whose state actually shifted. NPCs not present in
  the scene, or unaffected by the events, get no entry — silence is
  fine.
- ``emotional_state``: replace if it changed. 2-6 words. Match the
  source language.
- ``motivation``: replace if their immediate want changed. One short
  sentence. If unchanged, omit the field.
- ``interest_delta``: integer between -3 and +2. Positive when the PC
  earned trust / shared something / served their goal. Negative when
  the PC threatened / hurt / contradicted / disappointed. 0 means no
  change — omit instead of writing 0. Omit for NPCs marked with
  ``runtime_v2_version`` unless the roster has no V2 state.
- ``name_revealed``: true ONLY when the player explicitly learned the
  NPC's true name in this turn. Hidden markup like ``[speak]X[/speak]``
  is not visible to the player and does NOT count as a reveal — only
  visible narration / dialogue / documents do. Otherwise omit.
- ``name_claim``: optional sub-object ``{"claimed_name", "truth_status",
  "reason"}``. Use this when an NPC's true name is still hidden but the
  visible prose introduced an alias / cover name / possibly-false name
  the player can latch onto. ``truth_status`` is ``"false"`` when the
  narration clearly shows the name is fake or contradicts the true
  name, else ``"unknown"``. If the claimed name happens to equal the
  true name, prefer ``name_revealed: true`` instead. Omit when no
  alias was offered this turn.
- ``new_action_event``: one sentence describing the most consequential
  thing this NPC did this turn (used as input to a rolling
  action_summary). Skip when the NPC was passive or off-screen.
- Use NPC ``key`` values exactly as given. Do not invent new NPCs —
  if a stranger appeared, the GM marker layer already handled it.

## Output
Return STRICT JSON only, no markdown fences::

    {"npc_updates": [{"key": "...", "emotional_state": "...",
                      "motivation": "...", "interest_delta": 1,
                      "name_revealed": false,
                      "name_claim": {"claimed_name": "Karen",
                                     "truth_status": "false",
                                     "reason": "她说叫她Karen但身份证上写着别的名字"},
                      "new_action_event": "..."}]}

Empty result is ``{"npc_updates": []}``."""


def _split_in_scene(
    npcs: list[dict[str, Any]],
    session: GameSession,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    current_scene = ""
    if isinstance(session.memory_state, dict):
        current_scene = str(session.memory_state.get("current_scene") or "").strip()
    if not current_scene:
        # Fall back to module_state.scene when memory has no current_scene yet.
        if isinstance(session.module_state, dict):
            current_scene = str(session.module_state.get("scene") or "").strip()
    in_scene: list[dict[str, Any]] = []
    off_scene: list[dict[str, Any]] = []
    for npc in npcs:
        last = str(npc.get("last_seen_scene") or "").strip()
        if current_scene and last == current_scene:
            in_scene.append(npc)
        else:
            off_scene.append(npc)
    return in_scene, off_scene


def _build_user_message(
    player_text: str,
    gm_reply: str,
    npcs: list[dict[str, Any]],
    session: GameSession,
    *,
    knowledge_profiles_by_npc_id: dict[str, Any] | None = None,
) -> str:
    pc = session.character if isinstance(session.character, dict) else {}
    pc_summary = _pc_brief(pc)
    knowledge_profiles_by_npc_id = knowledge_profiles_by_npc_id or {}
    npc_block = "\n".join(
        _npc_brief(
            n,
            knowledge_profile=knowledge_profiles_by_npc_id.get(str(n.get("key") or "")),
        )
        for n in npcs
    )
    return (
        "## PC\n"
        + (pc_summary or "(unspecified)")
        + "\n\n## NPC roster (current state)\n"
        + (npc_block or "(none)")
        + "\n\n## Player input this turn\n"
        + (player_text or "")[:_MAX_TEXT_CHARS]
        + "\n\n## GM reply this turn\n"
        + (gm_reply or "")[:_MAX_TEXT_CHARS]
    )


def _pc_brief(pc: dict[str, Any]) -> str:
    if not isinstance(pc, dict):
        return ""
    identity = pc.get("identity") if isinstance(pc.get("identity"), dict) else {}
    name = (
        str(identity.get("name") or pc.get("name") or "").strip()
        or "PC"
    )
    role = str(identity.get("occupation") or pc.get("occupation") or "").strip()
    parts = [name]
    if role:
        parts.append(role)
    return " — ".join(parts)


def _npc_brief(
    npc: dict[str, Any],
    *,
    knowledge_profile: Any = None,
) -> str:
    key = str(npc.get("key") or "")
    name = str(npc.get("name") or "")
    role = str(npc.get("role") or "")
    inner = npc.get("inner_state") or {}
    emotion = str(inner.get("emotional_state") or "")
    motivation = str(inner.get("motivation") or "")
    kn = npc.get("player_knowledge") or {}
    interest = kn.get("interest")
    summary = str(npc.get("action_summary") or npc.get("summary") or "")[:160]
    bits = [
        f"key={key}",
        f"name={name}",
    ]
    if role:
        bits.append(f"role={role}")
    if emotion:
        bits.append(f"mood={emotion}")
    if motivation:
        bits.append(f"motivation={motivation[:80]}")
    if isinstance(interest, int):
        bits.append(f"interest={interest}")
    if summary:
        bits.append(f"recent={summary}")
    runtime_state = npc.get("runtime_state_v2")
    if isinstance(runtime_state, dict):
        bits.append(f"runtime_v2_version={_runtime_state_version(npc)}")
    if isinstance(knowledge_profile, dict) and knowledge_profile:
        bits.append(
            "knowledge_profile="
            + json.dumps(knowledge_profile, ensure_ascii=False, separators=(",", ":"))[:900]
        )
    return "- " + "; ".join(bits)


def _current_scene_id(session: GameSession) -> str:
    if isinstance(session.memory_state, dict):
        current = str(session.memory_state.get("current_scene") or "").strip()
        if current:
            return current
    if isinstance(session.module_state, dict):
        return str(session.module_state.get("scene") or "").strip()
    return ""
