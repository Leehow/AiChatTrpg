"""LLM-generated NPC voice cards.

A voice card describes how the NPC SOUNDS in dialogue: speaking style,
catchphrase, mannerisms, sample lines for normal vs heightened
emotional states. The GM uses it to keep each NPC's voice distinct
between turns; the TTS layer can also read it to pick a voice and
delivery cues.

Each NPC in ``memory_state.npcs[]`` may carry an ``npc.voice_card``
dict with this shape::

    {
        "speaking_style": "<one line>",
        "catchphrase": "<one line>",
        "mannerisms": "<one line>",
        "sample_lines": ["<line 1>", "<line 2>"],
    }

Generation is on-demand: the agent has a ``fill_missing_voice_cards``
method that batches all NPCs missing a card and runs one LLM call per
NPC. The cards are persisted on the NPC dict so subsequent turns reuse
them — no recomputation per request.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from agents.trpg.llm_json import (
    call_llm_json_task,
    extract_json_object,
)


logger = logging.getLogger("chatrpg.trpg_npc.voice_card")


_VOICE_CARD_PROMPT = """You design TRPG NPC voice cards for the GM to use in dialogue scenes.

A voice card captures how this character SOUNDS — not what they say in
any specific scene, but the consistent patterns the GM should reach
for whenever the NPC speaks.

## Output JSON (no markdown fences, no preamble)
{
  "speaking_style": "<one line: cadence / vocabulary / sentence shape, ~80 chars>",
  "catchphrase": "<one line: signature phrase or verbal tic, ~50 chars; may be empty>",
  "mannerisms": "<one line: small physical / vocal habits while speaking, ~80 chars>",
  "sample_lines": [
    "<one line of typical dialogue toward the PC>",
    "<one line of dialogue under tension (anger / fear / pressure)>"
  ]
}

## Rules
- Match the source language: if the NPC's name and description are in
  Chinese, output sample_lines in Chinese; if English, English; if mixed,
  whichever language the description leans toward.
- Use the NPC's role / personality / motivation / dialogue_style hints.
  If the input is sparse, infer something specific to the character —
  generic "speaks calmly" is a failure.
- sample_lines are at most TWO entries, one neutral, one strained. Make
  the second one clearly emotionally heightened (anger, fear, urgency,
  cold calculation — pick what fits).
- Don't reproduce the player character's name in the lines unless the
  NPC's relationship_dynamic clearly says they would address the PC by name.
- Output strict JSON only.
"""


async def generate_voice_card(
    npc: dict[str, Any],
    *,
    model: str,
    base_url: str,
    api_key: str,
) -> dict[str, Any] | None:
    """Generate a voice card for one NPC. Returns the card dict, or None
    on failure."""
    if not isinstance(npc, dict):
        return None

    profile = _compact_profile(npc)
    user_message = (
        "## NPC profile\n"
        + json.dumps(profile, ensure_ascii=False, indent=2)
    )
    try:
        raw = await call_llm_json_task(
            stage="npc_voice_card",
            model=model,
            base_url=base_url,
            api_key=api_key,
            system_prefix=_VOICE_CARD_PROMPT,
            user_message=user_message,
            stream=False,
        )
    except Exception:
        logger.warning(
            "[chatrpg.trpg_npc.voice_card] LLM call failed for %s",
            npc.get("key") or npc.get("name") or "?", exc_info=True,
        )
        return None

    card = _parse_voice_card_response(raw)
    if not card:
        return None
    return _normalise_card(card)


async def generate_missing_voice_cards(
    npcs: list[dict[str, Any]],
    *,
    model: str,
    base_url: str,
    api_key: str,
) -> int:
    """Fill ``npc["voice_card"]`` on every NPC that doesn't have one yet.

    Mutates NPCs in place. Returns count of cards generated. Caller is
    responsible for ``flag_modified`` + commit (the agent's
    ``save()`` handles that).
    """
    if not isinstance(npcs, list) or not npcs:
        return 0
    count = 0
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        if isinstance(npc.get("voice_card"), dict) and npc["voice_card"]:
            continue
        if not str(npc.get("name") or "").strip():
            continue
        card = await generate_voice_card(
            npc, model=model, base_url=base_url, api_key=api_key,
        )
        if card:
            npc["voice_card"] = card
            count += 1
    return count


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


_FIELDS_FOR_PROMPT = (
    "name",
    "player_known_name",
    "gender",
    "age",
    "role",
    "title",
    "description",
    "summary",
    "personality",
    "appearance",
    "motivation",
    "dialogue_style",
    "voice_hint",
    "secret_agenda",
    "relationship_dynamic",
)


def _compact_profile(npc: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in _FIELDS_FOR_PROMPT:
        value = npc.get(field)
        if isinstance(value, str) and value.strip():
            out[field] = value.strip()
    inner = npc.get("inner_state")
    if isinstance(inner, dict):
        emotion = str(inner.get("emotional_state") or "").strip()
        motivation = str(inner.get("motivation") or "").strip()
        if emotion and not out.get("emotional_state"):
            out["emotional_state"] = emotion
        if motivation and not out.get("motivation"):
            out["motivation"] = motivation
    return out


def _parse_voice_card_response(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text.strip())
    try:
        data = extract_json_object(text)
    except Exception:
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return None
    return data if isinstance(data, dict) else None


def _normalise_card(card: dict[str, Any]) -> dict[str, Any]:
    """Trim string fields, cap sample_lines, drop empty values."""
    out: dict[str, Any] = {}
    for key in ("speaking_style", "catchphrase", "mannerisms"):
        value = str(card.get(key) or "").strip()
        if value:
            out[key] = value
    sample_lines = card.get("sample_lines")
    if isinstance(sample_lines, list):
        cleaned = [str(line).strip() for line in sample_lines if str(line).strip()]
        if cleaned:
            out["sample_lines"] = cleaned[:3]
    return out
