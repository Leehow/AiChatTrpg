"""Scene-scoped NPC runtime (chatrpg, path B).

Without this module, every IC turn renders ALL `memory_state.npcs[]` as
"Active NPCs" in the BP3 prompt block — even ones the player met three
scenes ago and is no longer interacting with. The prompt grows without
bound and pulls the GM's focus across stale characters.

This module gives chatrpg minimum-viable scene-runtime behavior, deliberately
slimmer than chatlab's `scene_runtime.py` (which couples to NPC params /
voice / bond_context / scene runtime caching that chatrpg doesn't have):

  1. Stamp `last_seen_scene` + `last_seen_at_turn` on NPCs the moment
     `[CREATE_NPC]` fires, AND on existing NPCs the GM mentions later.
     (We can't read every GM line for "is NPC mentioned" without an LLM
      call, so for now we only stamp on creation. Re-stamping on
      mention is a future addition.)

  2. Build an `IcContext` whose `active_npcs` includes only NPCs whose
     `last_seen_scene == current_scene_key`. The framework's `build_bp_ic`
     then renders ONLY those in the prompt — older scenes' NPCs drop out.

Failure modes are tolerant: if scene tagging or filtering crashes, the
caller falls back to all NPCs (chatrpg's pre-wave-4 behavior).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession

from agents.trpg.speaker_resolver import (
    is_probable_named_speaker,
    is_trackable_visible_speaker,
    iter_speaker_tags,
    resolve_speaker_label,
)
from agents.trpg.framework import IcContext
from orm.models import GameSession
from services.trpg_adventure_start import active_module_chapter_from_state
from services.trpg_npc import NpcAgent, mask_hidden_npc_names_in_text
from services.trpg_npc.runtime_adapter import (
    build_npc_pre_turn_runtime,
    prompt_safe_active_npcs,
)
from services.trpg_npc.runtime_persistence import build_npc_pre_turn_runtime_from_tables
from services.trpg_rule_consequences import recent_rule_consequences_prompt_block

logger = logging.getLogger("chatrpg.trpg.scene_runtime")


def _current_scene_key(session: GameSession) -> str:
    ms = session.module_state if isinstance(session.module_state, dict) else {}
    scene = ms.get("scene")
    if isinstance(scene, str) and scene.strip() and scene.strip() != "—":
        return scene.strip()
    # Fallback to memory_state.world_facts.current_scene if available.
    mem = session.memory_state if isinstance(session.memory_state, dict) else {}
    facts = mem.get("world_facts")
    if isinstance(facts, dict):
        cs = facts.get("current_scene")
        if isinstance(cs, str) and cs.strip():
            return cs.strip()
    return ""


def stamp_new_npcs_with_scene(
    session: GameSession,
    parsed_markers: list[dict[str, Any]],
    *,
    turn_marker: str = "",
) -> int:
    """For every `[CREATE_NPC]` marker in the just-finished turn, find the
    matching NPC entry in `memory_state.npcs[]` (by key) and stamp it with
    `last_seen_scene` (current scene) and `last_seen_at_turn` (caller-supplied
    short id, e.g. session_id_prefix). Returns the number of NPCs stamped."""
    create_keys: list[str] = []
    for m in parsed_markers or []:
        if m.get("kind") != "create_npc":
            continue
        args = m.get("args") or {}
        key = str(args.get("key") or args.get("id") or "").strip()
        if key:
            create_keys.append(key)
    if not create_keys:
        return 0

    scene_key = _current_scene_key(session)
    if not scene_key:
        return 0

    mem = (
        dict(session.memory_state)
        if isinstance(session.memory_state, dict) else {}
    )
    npcs = mem.get("npcs")
    if not isinstance(npcs, list):
        return 0

    now = datetime.now(timezone.utc).isoformat()
    stamped = 0
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        if npc.get("key") not in create_keys:
            continue
        npc["last_seen_scene"] = scene_key
        npc["last_seen_at"] = now
        if turn_marker:
            npc["last_seen_at_turn"] = turn_marker
        stamped += 1

    if stamped:
        mem["npcs"] = npcs
        session.memory_state = mem
        flag_modified(session, "memory_state")
    return stamped


_GENERIC_PUBLIC_NPC_LABELS = {
    "未知",
    "未标注",
    "陌生人",
    "男人",
    "女人",
    "男子",
    "女子",
    "老人",
    "司机",
    "医生",
    "祭司",
    "牧师",
    "神父",
    "老板",
    "店主",
}


def _remember_public_speaker_label(
    agent: NpcAgent,
    key: str,
    label: str,
    scene_key: str,
) -> bool:
    """Attach a newly used player-facing speaker label to an existing NPC."""
    npc = agent.get(key)
    clean = str(label or "").strip()
    if not npc or not clean:
        return False

    changed = False
    if scene_key:
        changed = agent.mark_seen(key, scene_key) or changed

    true_name = str(npc.get("name") or "").strip()
    public_name = str(npc.get("player_known_name") or "").strip()
    # Skip if the label is already covered by `name` or `player_known_name` —
    # speaker_resolver matches against both directly, so duplicating them in
    # `aliases` only clutters the roster without helping resolution.
    aliases = npc.get("aliases")
    if not isinstance(aliases, list):
        aliases = []
    already_known = clean == true_name or clean == public_name or clean in [
        str(item) for item in aliases
    ]
    if not already_known:
        aliases.append(clean)
        agent.update(key, aliases=aliases)
        changed = True

    current_public = str(
        npc.get("player_known_name")
        or npc.get("public_name")
        or npc.get("display_name")
        or ""
    ).strip()
    if (
        clean != current_public
        and (not current_public or current_public in _GENERIC_PUBLIC_NPC_LABELS)
        and len(clean) > len(current_public)
    ):
        agent.update(key, player_known_name=clean)
        changed = True
    return changed


async def ensure_spoken_npcs_with_scene(
    session: GameSession,
    assistant_text: str,
    *,
    turn_marker: str = "",
) -> list[str]:
    """Create lightweight NPC entries for newly named visible speakers.

    The prompt asks the GM to emit `[CREATE_NPC]` when a named NPC first
    matters, but LLMs sometimes only emit `[speak]Name[/speak]`. Without a
    roster entry, future NPC Runtime turns cannot track that visible person
    and speaker-key annotation may fuzzy-match the name to an unrelated hidden
    NPC. This tolerant post-pass turns stable spoken names into revealed,
    scene-scoped NPCs, leaving generic bystanders as pure dialogue labels.
    """
    refs = iter_speaker_tags(assistant_text)
    if not refs:
        return []

    scene_key = _current_scene_key(session)
    module_state = session.module_state if isinstance(session.module_state, dict) else {}
    scene_name = str(module_state.get("scene_name") or module_state.get("scene") or "").strip()
    module_title = str(module_state.get("title") or "").strip()
    agent = NpcAgent(session)
    created: list[str] = []
    seen_labels: set[str] = set()

    for ref in refs:
        label = str(ref.label or "").strip()
        if not label or label in seen_labels:
            continue
        seen_labels.add(label)
        if ref.key:
            _remember_public_speaker_label(agent, ref.key, label, scene_key)
            continue
        if not is_trackable_visible_speaker(label):
            continue
        matched_key = resolve_speaker_label(label, agent.npcs)
        if matched_key:
            _remember_public_speaker_label(agent, matched_key, label, scene_key)
            continue
        if agent.get(label):
            _remember_public_speaker_label(agent, label, label, scene_key)
            continue

        is_named = is_probable_named_speaker(label)
        digest_source = label if is_named else f"{scene_key or 'scene'}:{label}"
        digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:10]
        key = f"{'npc_spoken' if is_named else 'npc_seen'}_{digest}"
        if agent.get(key):
            if scene_key:
                agent.mark_seen(key, scene_key)
            continue

        summary = f"PC-known NPC first identified in dialogue as {label}."
        if scene_name:
            summary += f" First seen in scene: {scene_name}."
        # `name_revealed` is reserved for in-fiction reveal events flipped by the
        # GM via [NPC_TURN_SYNC]. Auto-creating from a [speak] tag never reveals
        # — even when the label looks like a true name, the player may not have
        # been told it; leaving this False prevents the prior bug where any
        # name-looking label was promoted to "officially known" by heuristic.
        npc = agent.add(
            {
                "key": key,
                "name": label,
                "player_known_name": label,
                "name_revealed": False,
                "gender": "unknown",
                "role": "visible speaker" if is_named else "unidentified visible NPC",
                "summary": summary,
                "description": summary,
                "source": "dialogue_speaker",
                "last_seen_scene": scene_key,
                "last_seen_at_turn": turn_marker,
                "portrait_prompt": (
                    "Square TRPG NPC portrait, head-and-shoulders character art, "
                    "clear face, no text, no watermark. "
                    f"PC-known NPC labeled {label}; module: {module_title or 'unknown'}; "
                    f"scene: {scene_name or scene_key or 'unknown'}."
                ),
            },
            default_revealed=False,
            skip_if_exists=True,
        )
        if npc is not None:
            created.append(str(npc.get("key") or key))

    if agent.is_dirty():
        await agent.save()
    return created


def compute_active_npcs(session: GameSession) -> list[dict[str, Any]]:
    """Return the subset of `memory_state.npcs[]` that belong to the current
    scene. Untagged NPCs (created before this module landed) are included as
    a fallback so we don't suddenly drop them from a live game."""
    mem = session.memory_state if isinstance(session.memory_state, dict) else {}
    npcs = mem.get("npcs")
    if not isinstance(npcs, list) or not npcs:
        return []

    scene_key = _current_scene_key(session)
    if not scene_key:
        # No scene set yet → everyone is "active" by default.
        return [n for n in npcs if isinstance(n, dict)]

    out: list[dict[str, Any]] = []
    untagged: list[dict[str, Any]] = []
    for npc in npcs:
        if not isinstance(npc, dict):
            continue
        tagged_scene = npc.get("last_seen_scene")
        if isinstance(tagged_scene, str) and tagged_scene.strip():
            if tagged_scene.strip() == scene_key:
                out.append(npc)
        else:
            untagged.append(npc)

    # If no NPCs match the current scene but we have untagged entries from
    # before this module existed, return those rather than an empty list —
    # avoids "GM forgot all the NPCs I just met" regressions on legacy
    # sessions.
    return out if out else untagged


def build_ic_context(
    session: GameSession,
    *,
    player_text: str = "",
    turn_id: int | None = None,
) -> IcContext:
    """Construct the `IcContext` chatrpg passes to the framework.

    Besides scene-filtered active NPCs, this now runs the foreground NPC
    Runtime V2 adapter and injects its SceneBeatPlan through `extras_text`.
    """
    try:
        active_raw = compute_active_npcs(session)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("active_npc computation failed: %s", exc, exc_info=True)
        active_raw = []

    npc_extras = ""
    try:
        npc_runtime = build_npc_pre_turn_runtime(
            session,
            player_text=player_text,
            active_npcs=active_raw,
            turn_id=turn_id,
        )
        npc_extras = npc_runtime.to_prompt_block()
        if npc_runtime.error:
            logger.warning("npc runtime pre_turn failed: %s", npc_runtime.error)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("npc runtime pre_turn crashed: %s", exc, exc_info=True)

    return _build_ic_context_from_active(
        session,
        active_raw=active_raw,
        npc_extras=npc_extras,
    )


async def build_ic_context_table_first(
    db: AsyncSession,
    session: GameSession,
    *,
    player_text: str = "",
    turn_id: int | None = None,
) -> tuple[IcContext, dict[str, Any]]:
    """Construct IcContext with Runtime V2 tables as the first read source.

    The public NPC prompt still uses the JSON roster because it carries UI and
    visibility fields. The NPC beat plan, however, is computed directly from
    Runtime V2 tables when table rows exist, falling back to JSON-derived
    runtime data if table pre-turn is unavailable.
    """

    try:
        active_raw = compute_active_npcs(session)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("active_npc computation failed: %s", exc, exc_info=True)
        active_raw = []

    meta: dict[str, Any] = {"source": "tables"}
    npc_extras = ""
    try:
        npc_runtime = await build_npc_pre_turn_runtime_from_tables(
            db,
            session,
            player_text=player_text,
            active_npcs=active_raw,
            turn_id=turn_id,
        )
        if npc_runtime.pre_turn:
            npc_extras = npc_runtime.to_prompt_block()
            meta.update({
                "profile_count": len(npc_runtime.profiles_by_id),
                "state_count": len(npc_runtime.states_by_id),
                "relationship_count": sum(
                    len(rels) for rels in npc_runtime.relationships_by_npc.values()
                ),
                "matched_card_count": len(npc_runtime.pre_turn.matched_card_ids),
                "hot_npc_count": len(npc_runtime.pre_turn.hot_npc_ids),
            })
            action_board_hits = _npc_action_board_hit_summary(npc_runtime)
            if action_board_hits:
                meta["action_board_hits"] = action_board_hits
        if npc_runtime.error:
            meta["error"] = npc_runtime.error
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("npc runtime table pre_turn crashed: %s", exc, exc_info=True)
        meta["error"] = f"{type(exc).__name__}: {exc}"

    if not npc_extras:
        meta["source"] = "json_fallback"
        try:
            npc_runtime = build_npc_pre_turn_runtime(
                session,
                player_text=player_text,
                active_npcs=active_raw,
                turn_id=turn_id,
            )
            npc_extras = npc_runtime.to_prompt_block()
            if npc_runtime.pre_turn:
                meta.update({
                    "matched_card_count": len(npc_runtime.pre_turn.matched_card_ids),
                    "hot_npc_count": len(npc_runtime.pre_turn.hot_npc_ids),
                })
                action_board_hits = _npc_action_board_hit_summary(npc_runtime)
                if action_board_hits:
                    meta["action_board_hits"] = action_board_hits
            if npc_runtime.error:
                meta["fallback_error"] = npc_runtime.error
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("npc runtime fallback pre_turn crashed: %s", exc, exc_info=True)
            meta["fallback_error"] = f"{type(exc).__name__}: {exc}"

    return _build_ic_context_from_active(
        session,
        active_raw=active_raw,
        npc_extras=npc_extras,
    ), meta


def _npc_action_board_hit_summary(npc_runtime: Any) -> dict[str, Any]:
    pre_turn = getattr(npc_runtime, "pre_turn", None)
    if pre_turn is None:
        return {}
    matches = [
        dict(item)
        for item in getattr(pre_turn, "action_board_matches", []) or []
        if isinstance(item, dict)
    ]
    resolutions = [
        dict(item)
        for item in getattr(pre_turn, "action_board_resolutions", []) or []
        if isinstance(item, dict)
    ]
    if not matches and not resolutions:
        return {}
    llm_matches = [
        item for item in matches
        if str(item.get("planner") or "") == "llm_background"
    ]
    return {
        "matched_card_ids": list(getattr(pre_turn, "matched_card_ids", []) or []),
        "hot_npc_ids": list(getattr(pre_turn, "hot_npc_ids", []) or []),
        "match_count": len(matches),
        "llm_background_match_count": len(llm_matches),
        "matches": matches[:8],
        "resolutions": resolutions[:8],
    }


def _build_ic_context_from_active(
    session: GameSession,
    *,
    active_raw: list[dict[str, Any]],
    npc_extras: str,
) -> IcContext:
    active = prompt_safe_active_npcs(active_raw)

    ms = session.module_state if isinstance(session.module_state, dict) else {}
    scene_key = str(ms.get("scene") or "").strip()
    if scene_key == "—":
        scene_key = ""

    # Pass a minimal `time_context` string so the GM is anchored. The HUD
    # already shows D{day} {clock}; the IC prompt's BP3 renders this verbatim.
    day = ms.get("day_count")
    clock = str(ms.get("in_game_time") or "").strip()
    parts: list[str] = []
    if day:
        parts.append(f"Day {day}")
    if clock:
        parts.append(clock)
    period = str(ms.get("in_game_period") or "").strip()
    if period:
        parts.append(period)
    time_context = " · ".join(parts) if parts else ""

    module_chapter_name, module_chapter_text = active_module_chapter_from_state(ms)

    # Module raw markdown is the highest-bandwidth NPC-name leak channel: it
    # ships verbatim into BP2 and is full of stat blocks that name characters
    # the player may not have met yet. Replace every hidden NPC's true name
    # with their player_known_name before the chapter reaches the GM.
    if module_chapter_text:
        all_npcs = list(session.memory_state.get("npcs") or []) if isinstance(
            session.memory_state, dict
        ) else []
        module_chapter_text, masked_keys = mask_hidden_npc_names_in_text(
            module_chapter_text, all_npcs
        )
        if masked_keys:
            logger.debug(
                "[chatrpg] module chapter masked %d hidden NPC names: %s",
                len(masked_keys), masked_keys,
            )

    extras_parts = [part for part in (npc_extras, recent_rule_consequences_prompt_block(session)) if part]

    return IcContext(
        active_npcs=active,
        scene_key=scene_key,
        time_context=time_context,
        module_chapter_name=module_chapter_name,
        module_chapter_text=module_chapter_text,
        extras_text="\n\n".join(extras_parts),
    )
