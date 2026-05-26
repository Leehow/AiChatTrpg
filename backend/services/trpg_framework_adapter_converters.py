"""ORM → framework dataclass converters for the chatrpg adapter.

Pure-data translation between chatrpg's `GameSession` / `Ruleset` /
`ParsedModule` rows and the portable TRPG framework dataclasses. Includes the
defensive base64 scrubber that strips inline data URIs out of any PC / NPC
payload before it reaches the LLM prompt.

Split out of `trpg_framework_adapter.py` purely for file-size hygiene; this
module is private to the adapter, but `to_session_state`, `to_ruleset_data`,
and `to_module_data` are re-exported from `trpg_framework_adapter` for
external consumers (debug scripts, IC runner, character creator).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agents.trpg.framework.models import (
    Message,
    ModuleData,
    RulesetData,
    SessionState,
)


# Stable-context blocks (core_rules / scene_guide / character sheet / guide /
# module) ship full text — no truncation. parameter_families is NOT injected
# into BP1 (it's reference catalogue data, looked up on demand at IC time).


_PROMPT_BASE64_THRESHOLD = 4096
_PROMPT_BASE64_PREFIX = "data:image/"


def _scrub_base64_for_prompt(node: Any, _path: str = "") -> Any:
    """Return a deep copy of `node` with any `data:image/...;base64,...` or
    suspiciously-large portrait/avatar string replaced with the empty string.

    Why: BP3 dumps PC + NPCs as JSON into the LLM prompt. If a portrait was
    persisted as an inline data URI (legacy import path or upstream bug) it
    can blow past the model's context window — a single 340K-char portrait
    consumes ~85K tokens before the GM sees a single word. This scrub is the
    last-line defense; the canonical fix is to store URLs not data URIs in
    `services/trpg_npc_assets`."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            if isinstance(v, str) and (
                v.startswith(_PROMPT_BASE64_PREFIX)
                or (
                    len(v) > _PROMPT_BASE64_THRESHOLD
                    and any(tag in (k or "").lower() for tag in ("portrait", "avatar", "image"))
                )
            ):
                out[k] = ""
                continue
            out[k] = _scrub_base64_for_prompt(v, _path=f"{_path}.{k}")
        return out
    if isinstance(node, list):
        return [_scrub_base64_for_prompt(v, _path=f"{_path}[{i}]") for i, v in enumerate(node)]
    return node


def to_session_state(
    orm_session: Any,
    chat_history: list[dict[str, Any]] | None = None,
) -> SessionState:
    """Read a chatrpg GameSession into the framework's flat SessionState.

    `chat_history` defaults to the messages stashed in setup_state.character_chat
    if not supplied — once chatrpg migrates chat to the messages table this can
    be replaced with the unified timeline.

    Inline base64 data URIs are scrubbed from PC + memory_state (npcs.*) before
    they reach the framework — see `_scrub_base64_for_prompt`."""
    setup = (
        orm_session.setup_state if isinstance(orm_session.setup_state, dict) else {}
    )
    if chat_history is None:
        chat_history = list(setup.get("character_chat") or [])
    pc_raw = orm_session.character if isinstance(orm_session.character, dict) else None
    pc = _scrub_base64_for_prompt(pc_raw) if pc_raw else None
    memory_raw = (
        orm_session.memory_state if isinstance(orm_session.memory_state, dict) else {}
    )
    memory_state = _scrub_base64_for_prompt(dict(memory_raw))
    return SessionState(
        id=str(orm_session.id),
        user_id=str(orm_session.user_id),
        # chatrpg single-user / setup-only: game_started flag isn't tracked
        # explicitly. Treat any session whose setup is completed as "ready
        # to run IC" for now (defaults to False so guide mode applies).
        game_started=bool(setup.get("completed") and pc),
        in_break=False,
        character_ready=bool(pc),
        characters={"pc": pc or {}, "npcs": []},
        module_state=dict(orm_session.module_state) if isinstance(orm_session.module_state, dict) else {},
        memory_state=memory_state,
        setup_state=dict(setup),
        chat_history=_convert_history(chat_history),
        dice_history=list(orm_session.dice_history or []),
        dice_pool={},
        narrative_summary=str(orm_session.narrative_summary or ""),
        last_summarized_msg_count=int(orm_session.last_summarized_msg_count or 0),
        adventure_start_msg_count=0,
        player_notes=[],
        # chatrpg has no distillates; framework's adapter slices parsed_v6 directly.
        resident_prompt="",
        scene_guide="",
        character_creation_pack="",
        character_build_rules="",
        character_template=None,
    )


def to_ruleset_data(orm_ruleset: Any) -> RulesetData:
    raw = orm_ruleset.parsed_v6 if isinstance(orm_ruleset.parsed_v6, dict) else {}
    return RulesetData(
        id=str(orm_ruleset.id),
        book_title=str(orm_ruleset.book_title or ""),
        world_mode=str(orm_ruleset.world_mode or ""),
        parsed_v6=raw,
        resident_prompt="",
        scene_guide="",
        character_creation_pack="",
    )


def to_module_data(parsed_module: Any | None) -> ModuleData | None:
    """Build a ModuleData from a chatrpg ParsedModule row (or None).

    Chargen-time: ships the KP briefing (`briefing_md`) instead of the full
    module markdown — players shouldn't see plot details before play starts.
    The briefing is the GM-facing summary produced by the module semantic
    parser. Returns None if no briefing has been produced yet (parsing in
    progress / failed) so the chargen prompt simply omits module context."""
    if parsed_module is None:
        return None
    title = str(getattr(parsed_module, "extracted_title", None)
                or getattr(parsed_module, "filename", "")
                or "")
    briefing = str(getattr(parsed_module, "briefing_md", "") or "")
    if not briefing:
        return None
    return ModuleData(
        id=str(getattr(parsed_module, "id", "")),
        title=title,
        markdown=briefing,
    )


def _convert_history(history: list[dict[str, Any]]) -> list[Message]:
    out: list[Message] = []
    for m in history:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        # Normalize: chatrpg's character_chat stores assistant role for GM.
        if role == "assistant":
            role = "gm"
        if role not in ("user", "gm", "system", "dice"):
            continue
        content = str(m.get("content") or "")
        if not content:
            continue
        out.append(Message(
            role=role,  # type: ignore[arg-type]
            content=content,
            phase="guide",  # all chatrpg setup_state chat is guide-phase
            created_at=_parse_ts(m.get("created_at")),
            metadata=m.get("metadata") or {},
        ))
    return out


def _parse_ts(ts: Any) -> datetime:
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str) and ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)
