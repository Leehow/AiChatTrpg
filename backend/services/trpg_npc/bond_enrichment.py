"""Manual enrichment for bond NPCs.

Bond NPCs (``npc.from_bond is True``) are seeded by
``services/character_intake.py`` with names, roles, and psychology; rich
prose fields (``description``, ``personality``, ``relationship_dynamic``)
and the text ``voice_card`` sub-dict are filled in on-demand here.
``relationship_dynamic`` is mirrored into ``bond_context.connection`` so
``ensure_npc_psychology`` known-facts pick it up automatically. TTS
selection (``tts_voice``, ``active_tts_voice``, provider overrides,
``tts_voice_locked``) stays under the audio router.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from agents.trpg.llm_json import call_llm_json_task, extract_json_object
from orm.models import GameSession
from services.trpg_npc.agent import NpcAgent
from services.trpg_npc.voice_card import _normalise_card

logger = logging.getLogger("chatrpg.trpg_npc.bond_enrichment")


ProfileGenerator = Callable[
    [dict[str, Any], dict[str, Any] | None],
    Awaitable[dict[str, Any] | None],
]


@dataclass
class EnrichmentResult:
    eligible: int = 0
    enriched: int = 0
    skipped: int = 0
    enriched_keys: list[str] = field(default_factory=list)
    skipped_keys: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


_PROFILE_KEYS = ("description", "personality", "relationship_dynamic")
_GENDER_PRESENT = {"male", "female", "nonbinary", "other"}


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _list_has_meaningful_entry(value: list[Any]) -> bool:
    return any(isinstance(item, str) and item.strip() for item in value)


def _has_voice_card(npc: dict[str, Any]) -> bool:
    card = npc.get("voice_card")
    if not isinstance(card, dict) or not card:
        return False
    # Reject lists that contain only blank strings; a card whose
    # sample_lines is ["", ""] is effectively empty.
    return any(
        (isinstance(v, str) and v.strip())
        or (isinstance(v, list) and _list_has_meaningful_entry(v))
        for v in card.values()
    )


def _gender_is_set(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() in _GENDER_PRESENT


def _clean(value: Any) -> str:
    return str(value or "").strip()


def is_bond_npc_unfinished(npc: dict[str, Any]) -> bool:
    """True when at least one rich profile field is missing.

    Gender alone is not a trigger -- if description, personality,
    relationship_dynamic, and voice_card are all populated the NPC is
    considered done even when ``gender == "unknown"``.
    """
    if not isinstance(npc, dict):
        return False
    if any(_is_blank(npc.get(k)) for k in _PROFILE_KEYS):
        return True
    return not _has_voice_card(npc)


def _eligible_npcs(
    npcs: list[dict[str, Any]], *, force: bool,
) -> list[dict[str, Any]]:
    return [
        npc for npc in npcs
        if isinstance(npc, dict) and npc.get("from_bond")
        and (force or is_bond_npc_unfinished(npc))
    ]


def select_eligible_bond_npcs(
    session: GameSession, *, force: bool = False,
) -> list[dict[str, Any]]:
    """Public preflight: list NPCs ``enrich_bond_npcs`` would process.

    The route uses this to early-out with a 200 when there is no work
    to do, without resolving an LLM compiler config.
    """
    mem = session.memory_state if isinstance(session.memory_state, dict) else {}
    npcs = mem.get("npcs") if isinstance(mem, dict) else None
    return _eligible_npcs(npcs, force=force) if isinstance(npcs, list) else []


def _normalise_profile(raw: dict[str, Any]) -> dict[str, Any]:
    """Trim string fields and normalise the voice card; drop empties."""
    out: dict[str, Any] = {}
    gender = _clean(raw.get("gender")).lower()
    if gender in _GENDER_PRESENT or gender == "unknown":
        out["gender"] = gender
    for key in _PROFILE_KEYS:
        text = _clean(raw.get(key))
        if text:
            out[key] = text
    raw_card = raw.get("voice_card")
    if isinstance(raw_card, dict) and raw_card:
        card = _normalise_card(raw_card)
        if card:
            out["voice_card"] = card
    return out


def _build_changes(
    npc: dict[str, Any],
    profile: dict[str, Any],
    *,
    force: bool,
) -> dict[str, Any]:
    """Conservative dict to feed ``NpcAgent.update``.

    Without force, only fills empty fields. Gender is only ever filled
    when blank/unknown -- overwriting an explicit gender from a re-run
    would be unfriendly even under force.
    """
    changes: dict[str, Any] = {}
    new_gender = profile.get("gender")
    if new_gender and new_gender != "unknown" and not _gender_is_set(npc.get("gender")):
        changes["gender"] = new_gender
    for key in _PROFILE_KEYS:
        new_value = profile.get(key)
        if not new_value:
            continue
        if force or _is_blank(npc.get(key)):
            changes[key] = new_value
    new_card = profile.get("voice_card")
    if isinstance(new_card, dict) and new_card:
        if force or not _has_voice_card(npc):
            changes["voice_card"] = new_card
    return changes


def _merge_bond_context(
    npc: dict[str, Any],
    relationship_dynamic: str,
    *,
    force: bool,
) -> bool:
    """Mirror ``relationship_dynamic`` into ``bond_context.connection``.

    ``ensure_npc_psychology`` reads ``bond_context.connection`` to add
    a known-fact about the pre-existing bond; without this mirror the
    enrichment would leave that pipeline dark. Returns True when the
    dict changed.
    """
    if not relationship_dynamic:
        return False
    bond = npc.get("bond_context")
    if not isinstance(bond, dict):
        bond = {}
    existing = _clean(bond.get("connection"))
    if existing == relationship_dynamic:
        return False
    if existing and not force:
        return False
    bond["connection"] = relationship_dynamic
    npc["bond_context"] = bond
    return True


# --- Default LLM-backed profile generator ---------------------------------

_PROFILE_PROMPT = """You design TRPG NPC profiles for bond / preexisting-relationship NPCs.

The player character (PC) has named this NPC in their backstory (ex-spouse,
old partner, mentor, sibling, rival, debtor, ...). The NPC already has a
stable name and rough role; your job is to fill the prose and voice card
the GM will use to roleplay them.

## Output JSON (no markdown fences, no preamble)
{
  "gender": "male" | "female" | "unknown",
  "description": "<2-3 sentences: appearance, bearing, public role>",
  "personality": "<2-3 sentences: core traits and how they engage the PC>",
  "relationship_dynamic": "<one line: nature of THIS bond, ~40-60 chars>",
  "voice_card": {
    "speaking_style": "<one line>",
    "catchphrase": "<one line; may be empty>",
    "mannerisms": "<one line>",
    "sample_lines": ["<neutral line>", "<line under tension>"]
  }
}

## Rules
- Match source language: if the NPC name and role lean Chinese,
  respond in Chinese; if English, respond in English. Do not mix.
- relationship_dynamic must describe THIS pairing -- generic
  "they know each other" is a failure. Ground it in the PC card.
- description / personality are playable cues, not biography.
- Do not invent plot facts that contradict the PC card.
- Output strict JSON only.
"""

_NPC_PROMPT_FIELDS = (
    "key", "name", "player_known_name", "gender", "role", "title",
    "summary", "description", "personality", "motivation",
    "voice_hint", "relationship_dynamic", "secret_agenda",
)
_PC_PROMPT_FIELDS = ("name", "gender", "age", "occupation")
_PC_BG_FIELDS = ("backstory", "summary", "history", "bonds")


def _compact_npc(npc: dict[str, Any]) -> dict[str, Any]:
    out = {k: npc[k].strip() for k in _NPC_PROMPT_FIELDS
           if isinstance(npc.get(k), str) and npc[k].strip()}
    bond = npc.get("bond_context")
    if isinstance(bond, dict):
        out["bond_context"] = bond
    return out


def _compact_pc(pc: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(pc, dict):
        return {}
    identity = pc.get("identity") if isinstance(pc.get("identity"), dict) else pc
    background = pc.get("background") if isinstance(pc.get("background"), dict) else pc
    out: dict[str, Any] = {}
    for key in _PC_PROMPT_FIELDS:
        value = identity.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    for key in _PC_BG_FIELDS:
        value = background.get(key)
        if isinstance(value, (str, list)) and value:
            out[key] = value
    return out


def _parse_response(raw: str) -> dict[str, Any] | None:
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


def make_default_profile_generator(
    *, model: str, base_url: str, api_key: str,
) -> ProfileGenerator:
    """Wrap ``call_llm_json_task`` as a ``ProfileGenerator``.

    Factory so the route resolves compiler config once and tests can
    swap in a fake generator without touching the LLM layer.
    """
    async def _generate(
        npc: dict[str, Any],
        pc: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        user_message = (
            "## NPC profile (existing)\n"
            + json.dumps(_compact_npc(npc), ensure_ascii=False, indent=2)
            + "\n\n## Player character (context)\n"
            + json.dumps(_compact_pc(pc), ensure_ascii=False, indent=2)
        )
        try:
            raw = await call_llm_json_task(
                stage="bond_npc_enrichment",
                model=model, base_url=base_url, api_key=api_key,
                system_prefix=_PROFILE_PROMPT,
                user_message=user_message,
                stream=False,
            )
        except Exception:
            logger.warning(
                "[chatrpg.bond_enrichment] LLM call failed for %s",
                npc.get("key") or npc.get("name") or "?", exc_info=True,
            )
            return None
        return _parse_response(raw)

    return _generate


# --- Public entrypoint ----------------------------------------------------


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def enrich_bond_npcs(
    session: GameSession,
    db: AsyncSession | None,
    *,
    profile_generator: ProfileGenerator,
    force: bool = False,
    limit: int | None = None,
) -> EnrichmentResult:
    """Walk ``memory_state.npcs[]`` and fill missing bond-NPC profile fields.

    Per-NPC failures are logged into the result and never abort the batch.
    Mutations go through ``NpcAgent.update`` so visibility + psychology
    re-normalise automatically. ``db`` may be ``None`` for in-memory tests.
    """
    result = EnrichmentResult()
    agent = NpcAgent(session)
    pc = session.character if isinstance(session.character, dict) else None

    eligible = _eligible_npcs(agent.npcs, force=force)
    result.eligible = len(eligible)
    if limit is not None and limit >= 0:
        targets = eligible[:limit]
        for npc in eligible[limit:]:
            key = _clean(npc.get("key"))
            if key:
                result.skipped += 1
                result.skipped_keys.append(key)
    else:
        targets = eligible

    for npc in targets:
        key = _clean(npc.get("key"))
        if not key:
            continue
        try:
            raw_profile = await profile_generator(npc, pc)
        except Exception as exc:
            logger.warning(
                "[chatrpg.bond_enrichment] generator crashed for %s: %s",
                key, exc, exc_info=True,
            )
            result.errors.append(f"{key}: generator_failed: {type(exc).__name__}")
            result.skipped += 1
            result.skipped_keys.append(key)
            continue

        if not isinstance(raw_profile, dict) or not raw_profile:
            result.skipped += 1
            result.skipped_keys.append(key)
            continue

        profile = _normalise_profile(raw_profile)
        changes = _build_changes(npc, profile, force=force)
        bond_changed = _merge_bond_context(
            npc, profile.get("relationship_dynamic", ""), force=force,
        )

        if not changes and not bond_changed:
            result.skipped += 1
            result.skipped_keys.append(key)
            continue

        if changes:
            agent.update(key, **changes)
        else:
            agent.mark_dirty()
        npc["bond_enriched_at"] = _utc_iso()
        result.enriched += 1
        result.enriched_keys.append(key)

    if result.enriched:
        await agent.save(db)
    return result
