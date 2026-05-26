"""NpcAgent — single entry point for all NPC operations on a session.

Wraps ``GameSession.memory_state["npcs"]`` so callers don't have to:

- Touch the list directly (and risk forgetting ``flag_modified``)
- Wire up four separate helpers (visibility, psychology, params, assets)
  in a specific order
- Reimplement key generation / dedup / lookup over and over

Intended usage::

    agent = NpcAgent(session)
    agent.add(npc_data, default_revealed=False, from_bond=True)
    agent.reveal_name("ray_harlan")
    agent.update("vern", emotional_state="拔刀的决断")
    await agent.ensure_assets(db)
    await agent.fill_missing_params(db, cfg=...)
    agent.save(db)

The agent is stateful — it holds a reference to the session and tracks
whether anything was mutated, so ``save()`` is a no-op when nothing
changed. Submodule helpers (``ensure_npc_psychology``,
``derive_interaction_drive``, etc.) remain available for code that needs
finer-grained control, but new code should prefer the agent.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from orm.models import GameSession
from services.trpg_npc.action_summary import (
    SUMMARY_MAX_CHARS,
    update_action_summary as _update_action_summary_impl,
)
from services.trpg_npc.assets import (
    NpcAssetSummary,
    ensure_npc_assets as _ensure_npc_assets_impl,
    spawn_npc_portrait_task as _spawn_npc_portrait_task_impl,
)
from services.trpg_npc.params import (
    build_rules_hint_from_parsed_v6,
    generate_missing_npc_params,
)
from services.trpg_npc.psychology import (
    append_inner_thought,
    ensure_npc_psychology,
)
from services.trpg_npc.visibility import (
    ensure_npc_visibility_fields,
    reveal_name as _reveal_name_impl,
)
from services.trpg_npc.voice_card import (
    generate_missing_voice_cards as _generate_missing_voice_cards_impl,
)


logger = logging.getLogger("chatrpg.trpg_npc.agent")


_KEY_CLEAN_RE = re.compile(r"[\s·•・/／,，、;；:：\-_—|]+")
_KEY_STRIP_RE = re.compile(r"[^a-z0-9_]")


# ---------------------------------------------------------------------------
# Helpers (module-private)
# ---------------------------------------------------------------------------


def _slug_from_name(name: str) -> str:
    base = _KEY_CLEAN_RE.sub("_", (name or "").strip().lower())
    base = _KEY_STRIP_RE.sub("", base).strip("_")
    if not base:
        digest = uuid.uuid5(uuid.NAMESPACE_DNS, name or "anon").hex[:10]
        base = f"npc_{digest}"
    return base


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key_match(npc: dict[str, Any], needle: str) -> bool:
    needle_l = needle.strip().lower()
    if not needle_l:
        return False
    if str(npc.get("key") or "").lower() == needle_l:
        return True
    if str(npc.get("name") or "").lower() == needle_l:
        return True
    if str(npc.get("player_known_name") or "").lower() == needle_l:
        return True
    return False


# ---------------------------------------------------------------------------
# NpcAgent
# ---------------------------------------------------------------------------


class NpcAgent:
    """Per-session NPC roster manager.

    Construct one per request scope; do not share across requests since
    the dirty flag and the cached list reference are tied to the session
    object the agent was constructed with.
    """

    def __init__(self, session: GameSession):
        self._session = session
        self._dirty = False
        mem = session.memory_state if isinstance(session.memory_state, dict) else {}
        if not isinstance(mem.get("npcs"), list):
            mem = dict(mem)
            mem["npcs"] = []
            session.memory_state = mem
            self._dirty = True
        self._mem = mem
        self._npcs: list[dict[str, Any]] = mem["npcs"]

    # -- Read -----------------------------------------------------------------

    @property
    def npcs(self) -> list[dict[str, Any]]:
        """Live reference — caller mutations also count as dirty if followed by save()."""
        return self._npcs

    @property
    def count(self) -> int:
        return len(self._npcs)

    def get(self, key_or_name: str) -> dict[str, Any] | None:
        for npc in self._npcs:
            if isinstance(npc, dict) and _key_match(npc, key_or_name):
                return npc
        return None

    def used_keys(self) -> set[str]:
        return {str(n.get("key") or "") for n in self._npcs if isinstance(n, dict)}

    def encountered(self) -> list[dict[str, Any]]:
        """NPCs the player has actually met IC (last_seen_scene set or actions logged)."""
        out: list[dict[str, Any]] = []
        for npc in self._npcs:
            if not isinstance(npc, dict):
                continue
            last_seen = str(npc.get("last_seen_scene") or "").strip()
            has_actions = bool(npc.get("actions"))
            if last_seen or has_actions:
                out.append(npc)
        return out

    def unique_key(self, name: str) -> str:
        used = self.used_keys()
        base = _slug_from_name(name)
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    # -- Create ---------------------------------------------------------------

    def add(
        self,
        data: dict[str, Any],
        *,
        default_revealed: bool = False,
        from_bond: bool = False,
        skip_if_exists: bool = True,
    ) -> dict[str, Any] | None:
        """Append a fresh NPC. Runs visibility + psychology normalisation.

        Returns the inserted dict, or ``None`` when ``skip_if_exists`` is
        true and the key already exists.
        """
        if not isinstance(data, dict):
            return None
        name = str(data.get("name") or "").strip()
        key = str(data.get("key") or "").strip() or (self.unique_key(name) if name else "")
        if not key:
            return None
        if skip_if_exists and self.get(key):
            return None

        npc = dict(data)
        npc["key"] = key
        npc.setdefault("name", name or key)
        npc.setdefault("created_at", _utc_iso())
        if from_bond:
            npc["from_bond"] = True

        ensure_npc_visibility_fields(npc, default_revealed=default_revealed)
        pc = self._session.character if isinstance(self._session.character, dict) else None
        ensure_npc_psychology(npc, pc=pc)

        self._npcs.append(npc)
        self._dirty = True
        return npc

    # -- Update ---------------------------------------------------------------

    def update(self, key_or_name: str, **changes: Any) -> dict[str, Any] | None:
        """Shallow update: top-level keys overwrite, dict values deep-merge.

        Re-runs visibility + psychology normalisation in case the change
        affected a field they read (gender → label, role → interest).
        """
        npc = self.get(key_or_name)
        if not npc or not changes:
            return npc
        for key, value in changes.items():
            if (
                isinstance(value, dict)
                and isinstance(npc.get(key), dict)
            ):
                _deep_merge(npc[key], value)
            else:
                npc[key] = value
        ensure_npc_visibility_fields(npc, default_revealed=npc.get("name_revealed", False))
        pc = self._session.character if isinstance(self._session.character, dict) else None
        ensure_npc_psychology(npc, pc=pc)
        self._dirty = True
        return npc

    def reveal_name(self, key_or_name: str) -> bool:
        """Mark an NPC's true name as known to the player. Idempotent."""
        npc = self.get(key_or_name)
        if not npc:
            return False
        if not _reveal_name_impl(npc):
            return False
        self._dirty = True
        return True

    def append_thought(self, key_or_name: str, thought: str) -> bool:
        """Push a new ``inner_state.thought_log`` entry (capped at 5)."""
        npc = self.get(key_or_name)
        if not npc:
            return False
        if not append_inner_thought(npc, thought):
            return False
        self._dirty = True
        return True

    def append_actions(self, key_or_name: str, actions: list[str], *, cap: int = 20) -> bool:
        """Append narrative action snippets to ``actions``. Caps oldest first.

        ``actions`` is a raw list — useful for tests, debug, and as an
        audit log. The GM-prompt-facing path is ``update_action_summary``
        instead, which keeps a single LLM-rewritten sentence rather than
        an unbounded list.
        """
        npc = self.get(key_or_name)
        if not npc:
            return False
        clean = [str(a).strip() for a in actions if str(a).strip()]
        if not clean:
            return False
        history = npc.setdefault("actions", [])
        if not isinstance(history, list):
            history = []
        history.extend(clean)
        if len(history) > cap:
            history = history[-cap:]
        npc["actions"] = history
        self._dirty = True
        return True

    async def update_action_summary(
        self,
        key_or_name: str,
        new_event: str,
        *,
        cfg: dict[str, Any],
        max_chars: int = SUMMARY_MAX_CHARS,
    ) -> bool:
        """Re-write the NPC's compressed ``action_summary`` with a new event.

        ``cfg`` must carry ``model`` / ``base_url`` / ``api_key``
        (the same shape ``routes.rulesets._resolve_default_compiler_config``
        returns). When LLM credentials are missing the helper falls
        back to a bounded plain-text append so the field stays useful.
        """
        npc = self.get(key_or_name)
        if not npc or not new_event:
            return False
        changed = await _update_action_summary_impl(
            npc,
            new_event,
            model=str(cfg.get("model") or ""),
            base_url=str(cfg.get("base_url") or ""),
            api_key=str(cfg.get("api_key") or ""),
            max_chars=max_chars,
        )
        if changed:
            self._dirty = True
        return changed

    def mark_seen(self, key_or_name: str, scene_key: str) -> bool:
        """Stamp ``last_seen_scene`` + ``last_seen_at`` on an NPC."""
        npc = self.get(key_or_name)
        if not npc:
            return False
        npc["last_seen_scene"] = scene_key
        npc["last_seen_at"] = _utc_iso()
        self._dirty = True
        return True

    # -- Delete ---------------------------------------------------------------

    def remove(self, key_or_name: str) -> bool:
        for index, npc in enumerate(self._npcs):
            if isinstance(npc, dict) and _key_match(npc, key_or_name):
                self._npcs.pop(index)
                self._dirty = True
                return True
        return False

    # -- Asset orchestration --------------------------------------------------

    async def ensure_assets(
        self,
        db: AsyncSession,
        *,
        queue_portraits: bool = True,
    ) -> NpcAssetSummary:
        """Run voice assignment + portrait queueing. Caller commits."""
        summary = await _ensure_npc_assets_impl(
            db, self._session, queue_portraits=queue_portraits,
        )
        if summary.voices_assigned or summary.portraits_queued:
            # `_ensure_npc_assets_impl` already called flag_modified; record
            # the dirtiness so a later `save()` is a no-op rather than
            # silently re-flagging.
            self._dirty = True
        return summary

    def spawn_portrait_task(self, npc_keys: Iterable[str]):
        keys = [str(k).strip() for k in npc_keys if str(k).strip()]
        if not keys:
            return None
        return _spawn_npc_portrait_task_impl(
            str(self._session.id), str(self._session.user_id), keys,
        )

    async def fill_missing_voice_cards(
        self,
        *,
        cfg: dict[str, Any],
    ) -> int:
        """Generate ``voice_card`` for every NPC that doesn't have one yet.

        ``cfg`` carries ``model`` / ``base_url`` / ``api_key`` (use
        ``routes.rulesets._resolve_default_compiler_config``). Returns
        the number of cards generated.
        """
        if not cfg.get("api_key") or not cfg.get("base_url") or not cfg.get("model"):
            return 0
        try:
            count = await _generate_missing_voice_cards_impl(
                self._npcs,
                model=cfg["model"],
                base_url=cfg["base_url"],
                api_key=cfg["api_key"],
            )
        except Exception:
            logger.warning(
                "[chatrpg.trpg_npc] fill_missing_voice_cards crashed", exc_info=True,
            )
            return 0
        if count:
            self._dirty = True
        return count

    async def fill_missing_params(
        self,
        *,
        cfg: dict[str, Any],
        rules_hint: str = "",
    ) -> int:
        """Generate mechanical params for NPCs that still lack them.

        ``cfg`` must carry ``model`` / ``base_url`` / ``api_key`` (use the
        same dict produced by ``routes.rulesets._resolve_default_compiler_config``).
        Returns number of NPCs that received fresh params.
        """
        if not cfg.get("api_key") or not cfg.get("base_url") or not cfg.get("model"):
            return 0
        target = [n for n in self._npcs if isinstance(n, dict) and not n.get("params")]
        if not target:
            return 0
        pc = self._session.character if isinstance(self._session.character, dict) else None
        try:
            filled = await generate_missing_npc_params(
                target,
                session_character=pc,
                rules_hint=rules_hint,
                model=cfg["model"],
                base_url=cfg["base_url"],
                api_key=cfg["api_key"],
            )
        except Exception:
            logger.warning(
                "[chatrpg.trpg_npc] fill_missing_params crashed", exc_info=True,
            )
            return 0
        if filled:
            self._dirty = True
        return filled

    # -- Persistence ----------------------------------------------------------

    def mark_dirty(self) -> None:
        """Manual dirty flag — useful when caller mutated an NPC dict directly."""
        self._dirty = True

    def is_dirty(self) -> bool:
        return self._dirty

    async def save(self, db: AsyncSession | None = None) -> bool:
        """Flush ``memory_state`` and optionally commit. No-op if clean.

        Returns True if a flush actually happened.
        """
        if not self._dirty:
            return False
        # The list reference was already stored on memory_state["npcs"] in
        # __init__; the assignment here is defensive in case a caller
        # replaced the reference.
        self._mem["npcs"] = self._npcs
        self._session.memory_state = self._mem
        try:
            flag_modified(self._session, "memory_state")
        except Exception:
            # Test sessions (SimpleNamespace etc.) without SQLAlchemy
            # instrumentation don't support flag_modified — the in-memory
            # assignment above is enough there.
            pass
        if db is not None:
            await db.commit()
        self._dirty = False
        return True


# ---------------------------------------------------------------------------
# Internal: deep-merge for partial updates
# ---------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if (
            isinstance(value, dict)
            and isinstance(base.get(key), dict)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = value


# Convenience helper for rules-hint construction so callers don't have to
# reach into the params submodule.
build_rules_hint_from_parsed_v6 = build_rules_hint_from_parsed_v6
