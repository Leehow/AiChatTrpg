"""Post-creation enrichment for newly-generated player characters.

Runs as a fire-and-forget background task after `character_creator` saves
a fresh character. Two parallel passes:

1. **PC portrait** — render the player-character's avatar via the model
   pool's `is_avatar` model and stash the URL on `character.identity.
   portrait_url`. The character_ui schema already binds an `image`
   primitive to that path, so the sidebar picks the picture up
   automatically on next session refresh.

2. **NPC extraction** — feed the character JSON to the GM model and ask
   for any NAMED, PC-relevant NPCs (前妻 / 警局旧识 / 失踪案委托人 / …).
   Each result is appended to `memory_state.npcs[]` in the same shape
   the in-game `[CREATE_NPC]` marker produces, then sent through the
   existing `ensure_npc_assets` + `spawn_npc_portrait_task` pipeline so
   their voices and portraits queue up like any GM-emitted NPC would.

Errors are logged and swallowed: a portrait or extraction failure
must never block the player from entering the game.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from agents.trpg.llm_json import (
    call_llm_json_task,
    extract_json_object,
)
from core.database import get_session_factory
from orm.models import GameSession
from services.trpg_npc.assets import (
    _generate_avatar_url,
    _is_probable_image_model,
    _resolve_role_model,
    ensure_npc_assets,
    spawn_npc_portrait_task,
)
from services.trpg_npc.params import (
    build_rules_hint_from_parsed_v6,
    generate_missing_npc_params,
)
from services.trpg_npc.psychology import ensure_npc_psychology
from services.trpg_npc.visibility import ensure_npc_visibility_fields

logger = logging.getLogger("chatrpg.character_intake")


# Hold strong refs to in-flight tasks so the asyncio loop can't garbage-
# collect them mid-flight (a known footgun for fire-and-forget tasks).
_INFLIGHT: set[asyncio.Task] = set()


def enqueue_character_intake(session_id: str, user_id: str) -> asyncio.Task:
    """Kick off intake as a background task. Idempotent: each phase
    skips itself when the session already carries the relevant data
    (existing portrait URL, existing NPC keys), so re-enqueueing after
    a regenerate is safe.
    """
    task = asyncio.create_task(_run_intake(session_id, user_id))
    _INFLIGHT.add(task)
    task.add_done_callback(_INFLIGHT.discard)
    return task


async def _run_intake(session_id: str, user_id: str) -> None:
    try:
        await _generate_pc_portrait(session_id, user_id)
    except Exception:
        logger.warning(
            "[chatrpg] PC portrait gen failed for session %s",
            session_id, exc_info=True,
        )
    try:
        await _extract_and_seed_npcs(session_id, user_id)
    except Exception:
        logger.warning(
            "[chatrpg] NPC intake failed for session %s",
            session_id, exc_info=True,
        )


# ---------- 1. PC portrait ----------

_PC_PORTRAIT_PROMPT_PREFIX = (
    "Square TRPG player-character portrait, head-and-shoulders, clear "
    "face, setting-appropriate costume, natural cinematic lighting, no "
    "text, no watermark. Character details: "
)


async def _generate_pc_portrait(session_id: str, user_id: str) -> None:
    factory = get_session_factory()
    async with factory() as db:
        session = await db.get(GameSession, session_id)
        if session is None or session.user_id != user_id:
            return
        character = (
            session.character if isinstance(session.character, dict) else None
        )
        if not character:
            return
        identity = character.get("identity") if isinstance(character, dict) else None
        if not isinstance(identity, dict):
            identity = {}
        if str(identity.get("portrait_url") or "").strip():
            return  # already generated

        model = await _resolve_role_model(db, "avatar")
        if model is None:
            logger.info(
                "[chatrpg] PC portrait skipped: no avatar model in pool",
            )
            return
        if not _is_probable_image_model(model.model):
            logger.info(
                "[chatrpg] PC portrait skipped: %s not image-capable",
                model.model,
            )
            return
        prompt = _build_pc_portrait_prompt(character)

    try:
        url = await _generate_avatar_url(model, prompt)
    except Exception as exc:
        logger.warning("[chatrpg] PC portrait gen failed: %s", exc)
        return
    if not url:
        return

    factory = get_session_factory()
    async with factory() as db:
        session = await db.get(GameSession, session_id)
        if session is None or session.user_id != user_id:
            return
        character = session.character if isinstance(session.character, dict) else {}
        identity = character.get("identity") if isinstance(character, dict) else None
        if not isinstance(identity, dict):
            identity = {}
        identity["portrait_url"] = url
        identity["portrait_generated_at"] = (
            datetime.now(timezone.utc).isoformat()
        )
        identity["portrait_model"] = model.model
        identity["portrait_prompt"] = prompt
        character["identity"] = identity
        session.character = character
        flag_modified(session, "character")
        await db.commit()
        logger.info(
            "[chatrpg] PC portrait saved: session=%s model=%s",
            session_id, model.model,
        )


def _build_pc_portrait_prompt(character: dict[str, Any]) -> str:
    identity = character.get("identity") if isinstance(character, dict) else None
    if not isinstance(identity, dict):
        identity = {}
    origin = character.get("origin") if isinstance(character, dict) else None
    if not isinstance(origin, dict):
        origin = {}
    backstory = origin.get("backstory") if isinstance(origin, dict) else None
    if not isinstance(backstory, dict):
        backstory = {}

    desc = backstory.get("personal_description")
    if isinstance(desc, list):
        appearance = " / ".join(str(d) for d in desc[:3] if d)
    else:
        appearance = str(desc or "").strip()

    bits = {
        "name": identity.get("name"),
        "occupation": identity.get("occupation"),
        "age": identity.get("age"),
        "gender": identity.get("gender") or identity.get("sex"),
        "era": identity.get("era"),
        "appearance": appearance,
        "concept": origin.get("character_concept") if isinstance(origin, dict) else None,
    }
    body = ", ".join(
        f"{k}: {v}" for k, v in bits.items() if str(v or "").strip()
    )
    return (_PC_PORTRAIT_PROMPT_PREFIX + body)[:1800]


# ---------- 2. NPC extraction + seeding ----------

_EXTRACT_SYSTEM = """You scan a player-character JSON and return any
NAMED NPCs that should be auto-created in the campaign's NPC roster.

Look in any background / origin / backstory section for:
- significant people, key connections, family / friends / enemies
- 重要之人 / 关键羁绊 / 联系人 / 同僚 / 家人 / 委托人

For each NPC, return ONE entry. SKIP:
- The player character themselves
- Anonymous mentions ("a man", "a woman", "the killer", "某人")
- Hidden true names the player has not learned in fiction yet
- Dead historical figures unrelated to current play
- Concepts / organisations rather than people

Return JSON in this exact shape (no markdown fences, no prose):

{
  "npcs": [
    {
      "key": "<short snake_case stable id, e.g. linda_marlowe>",
      "name": "<display name as it appears in the source>",
      "gender": "male" | "female" | "unknown",
      "role": "<short public role, e.g. ex-wife in San Antonio>",
      "summary": "<one paragraph: who they are and how they relate to PC>",
      "portrait_prompt": "<one-line visual description for an image model>",
      "voice_hint": "<age, texture, cadence in 5-12 words>",

      "relationship_to_pc": "preexisting_relationship" | "plot_informed" | "stranger",
      "interest_score": <int 0-10: urgency to engage with the PC; see rubric>,
      "interest_drive_kind": "neutral" | "social" | "affinity" | "professional" | "relationship" | "goal_driven" | "mixed",
      "interest_reason": "<one line: why this drive exists>",
      "motivation": "<one line: what they want from the PC right now>",
      "emotional_state": "<2-6 words: their current mood toward the PC>",
      "secret_agenda": "<GM-only hidden goal, may be empty>",
      "interaction_goals": ["<concrete thing they want from PC>", "..."],
      "affinity_topics": ["<shared hobby/profession/origin>", "..."]
    }
  ]
}

## interest_score rubric (use the lowest band that fits)
- 0       : avoids the PC entirely.
- 1-2     : passive — answers if asked, otherwise indifferent.
- 3-4     : mild contextual curiosity (small talk, light questions).
- 5-6     : actively engages — professional duty or genuine curiosity.
- 7-8     : strongly wants something specific from the PC; seeks them out.
- 9-10    : obsessive / mission-critical; will create opportunities to interact.

## relationship_to_pc rules
- Use "preexisting_relationship" when the source clearly says they already
  know the PC: family / spouse / 前妻 / 旧友 / 旧识 / 同事 / 老搭档 / etc.
- Use "plot_informed" only when the source says they were briefed about /
  assigned to / hunting / surveilling the PC without prior personal contact.
- Otherwise "stranger".

If no qualifying NPCs are found, return {"npcs": []}. Output ONLY the
JSON object.
"""


async def _extract_and_seed_npcs(session_id: str, user_id: str) -> None:
    # Phase 1: read character + resolve compiler API config (short DB scope).
    factory = get_session_factory()
    async with factory() as db:
        session = await db.get(GameSession, session_id)
        if session is None or session.user_id != user_id:
            return
        character = (
            session.character if isinstance(session.character, dict) else None
        )
        if not character:
            return
        # Imported lazily — services/character_intake should have no static
        # dependency on the routes layer.
        from routes.rulesets import _resolve_default_compiler_config
        cfg = await _resolve_default_compiler_config(db)
    if not cfg.get("api_key") or not cfg.get("base_url"):
        return

    user_msg = (
        "Character JSON:\n\n```json\n"
        + json.dumps(character, ensure_ascii=False, indent=2)
        + "\n```"
    )
    try:
        raw = await call_llm_json_task(
            stage="character_intake_npcs",
            model=cfg["model"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            system_prefix=_EXTRACT_SYSTEM,
            user_message=user_msg,
            stream=False,
        )
    except Exception as exc:
        logger.warning("[chatrpg] NPC extract LLM call failed: %s", exc)
        return

    try:
        parsed = extract_json_object(raw)
    except Exception as exc:
        logger.warning("[chatrpg] NPC extract JSON parse failed: %s", exc)
        return
    npcs = parsed.get("npcs") if isinstance(parsed, dict) else None
    if not isinstance(npcs, list) or not npcs:
        return

    # Phase 2: persist + queue portraits.
    factory = get_session_factory()
    async with factory() as db:
        session = await db.get(GameSession, session_id)
        if session is None or session.user_id != user_id:
            return
        new_keys = _append_npcs_to_memory(session, npcs)
        if not new_keys:
            return
        # Generate mechanical params (HP / core stats / 1-2 role traits) for
        # the freshly-added NPCs so the GM has numbers to roll against on
        # turn one. Same LLM config as the NPC extractor — see chatlab's
        # phase_postprocess npc_enrichment for the original of this idea.
        await _seed_npc_params(session, new_keys, cfg, db)
        flag_modified(session, "memory_state")
        # Voices + portrait queue — same path GM-emitted NPCs go through.
        await ensure_npc_assets(db, session)
        await db.commit()
    spawn_npc_portrait_task(session_id, user_id, new_keys)
    logger.info(
        "[chatrpg] character intake added %d NPC(s) to session %s: %s",
        len(new_keys), session_id, new_keys,
    )


async def _seed_npc_params(
    session: GameSession,
    new_keys: list[str],
    cfg: dict[str, Any],
    db: Any,
) -> None:
    """Generate params for NPCs that were just appended to ``memory_state``.

    Pulls the ruleset for combat/contest excerpts so the prompt sees the
    same dice grammar the GM will eventually roll against. Failures are
    logged but never raised — the NPCs still exist, they just get no
    numbers and the next pass can retry."""
    if not new_keys:
        return
    npcs = (session.memory_state or {}).get("npcs") or []
    target = [n for n in npcs if isinstance(n, dict) and n.get("key") in set(new_keys)]
    if not target:
        return

    rules_hint = ""
    if session.ruleset_id:
        try:
            from orm.models import Ruleset
            ruleset = await db.get(Ruleset, session.ruleset_id)
            if ruleset is not None:
                rules_hint = build_rules_hint_from_parsed_v6(
                    ruleset.parsed_v6 if isinstance(ruleset.parsed_v6, dict) else None
                )
        except Exception:
            logger.warning(
                "[chatrpg] could not load ruleset for NPC param-gen rules hint",
                exc_info=True,
            )

    try:
        await generate_missing_npc_params(
            target,
            session_character=(
                session.character if isinstance(session.character, dict) else None
            ),
            rules_hint=rules_hint,
            model=cfg["model"],
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
        )
    except Exception:
        logger.warning(
            "[chatrpg] NPC param generation pass crashed",
            exc_info=True,
        )


_VALID_RELATIONSHIPS = {"preexisting_relationship", "plot_informed", "stranger"}
_VALID_DRIVE_KINDS = {"neutral", "social", "affinity", "professional", "relationship", "goal_driven", "mixed"}


def _seed_npc_from_llm(npc: dict[str, Any], entry: dict[str, Any]) -> None:
    """Lift LLM-supplied psychology fields onto the NPC dict so the
    ``ensure_npc_psychology`` normaliser keeps them instead of falling
    back to regex heuristics. Conservative: only sets fields the model
    actually populated.
    """
    relationship = str(entry.get("relationship_to_pc") or "").strip().lower()
    if relationship in _VALID_RELATIONSHIPS:
        npc["llm_relationship_hint"] = relationship
        if relationship == "preexisting_relationship":
            npc["from_bond"] = True

    motivation = str(entry.get("motivation") or "").strip()
    if motivation:
        npc["motivation"] = motivation

    emotional_state = str(entry.get("emotional_state") or "").strip()
    if emotional_state:
        npc["emotional_state"] = emotional_state

    secret_agenda = str(entry.get("secret_agenda") or "").strip()
    if secret_agenda:
        npc["secret_agenda"] = secret_agenda

    interaction_goals = entry.get("interaction_goals")
    if isinstance(interaction_goals, list) and interaction_goals:
        npc["interaction_goals"] = [str(g).strip() for g in interaction_goals if str(g).strip()]

    affinity_topics = entry.get("affinity_topics")
    if isinstance(affinity_topics, list) and affinity_topics:
        npc["affinity_topics"] = [str(g).strip() for g in affinity_topics if str(g).strip()]

    interest_score = entry.get("interest_score")
    if isinstance(interest_score, (int, float)):
        npc["player_interest"] = max(0, min(10, int(interest_score)))

    drive_kind = str(entry.get("interest_drive_kind") or "").strip().lower()
    interest_reason = str(entry.get("interest_reason") or "").strip()
    if drive_kind in _VALID_DRIVE_KINDS or interest_reason:
        # Pre-seed the interest_drive subdict so ensure_npc_player_knowledge
        # picks it up via _normalize_interest_drive instead of regenerating
        # via regex. Score is filled in later from player_interest.
        existing_drive = npc.get("interest_drive") if isinstance(npc.get("interest_drive"), dict) else {}
        if drive_kind in _VALID_DRIVE_KINDS:
            existing_drive["kind"] = drive_kind
        if interest_reason:
            existing_drive["reason"] = interest_reason
        if drive_kind in {"goal_driven", "mixed"}:
            existing_drive.setdefault("decays_on_goal_satisfied", True)
        npc["interest_drive"] = existing_drive


_KEY_CLEAN_RE = re.compile(r"[\s·•・/／,，、;；:：\-_—|]+")
_KEY_STRIP_RE = re.compile(r"[^a-z0-9_]")


def _slug_from_name(name: str) -> str:
    base = _KEY_CLEAN_RE.sub("_", name.strip().lower())
    base = _KEY_STRIP_RE.sub("", base).strip("_")
    if not base:
        # CJK / non-ASCII names slug to nothing, so fall back to a stable
        # hash of the original so re-runs hit the same key.
        digest = uuid.uuid5(uuid.NAMESPACE_DNS, name).hex[:10]
        base = f"npc_{digest}"
    return base


def _append_npcs_to_memory(
    session: GameSession,
    npcs: list[Any],
) -> list[str]:
    mem = (
        dict(session.memory_state)
        if isinstance(session.memory_state, dict)
        else {}
    )
    existing = mem.get("npcs")
    if not isinstance(existing, list):
        existing = []
    existing_keys = {
        str(n.get("key") or "")
        for n in existing
        if isinstance(n, dict)
    }
    added: list[str] = []
    now = datetime.now(timezone.utc).isoformat()
    for entry in npcs:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        key = str(entry.get("key") or "").strip()
        if not key and name:
            key = _slug_from_name(name)
        if not key:
            continue
        if key in existing_keys:
            continue
        npc_payload = {
            "key": key,
            "name": name or key,
            "gender": entry.get("gender") or "unknown",
            "role": entry.get("role") or "",
            "summary": entry.get("summary") or "",
            "portrait_prompt": entry.get("portrait_prompt") or "",
            "voice_hint": entry.get("voice_hint") or "",
            "created_at": now,
            "source": "character_intake",
            # PC's own backstory NPCs — the player obviously knows their
            # ex-wife / cop friend / etc. by name, so default to revealed.
            # The GM can later mark them hidden if the campaign demands it.
            "from_bond": True,
        }
        # Pre-seed psychology fields from the LLM extraction. These take
        # priority over the regex heuristic in `ensure_npc_psychology`
        # because the LLM has just read the entire character JSON and has
        # better context than keyword pattern matching.
        _seed_npc_from_llm(npc_payload, entry)
        ensure_npc_visibility_fields(npc_payload, default_revealed=True)
        ensure_npc_psychology(
            npc_payload,
            pc=session.character if isinstance(session.character, dict) else None,
        )
        existing.append(npc_payload)
        existing_keys.add(key)
        added.append(key)
    if added:
        mem["npcs"] = existing
        session.memory_state = mem
    return added
