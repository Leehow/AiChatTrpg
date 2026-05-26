"""Setup-phase chat persistence and snapshot helpers for character creation.

Setup-phase chat lives in the `messages` table (rows tagged with
`metadata.phase = "guide"`) so the entire session timeline shares one
storage layout — same as chatlab. Earlier chatrpg versions stashed chat
inside `setup_state.character_chat`; that data is migrated lazily on first
read (see `_migrate_chat_if_needed`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from llm import ChatMessage
from orm.models import GameSession, Message

# Legacy key — kept for the lazy migration path. New code never writes here.
CHAT_KEY = "character_chat"
READY_KEY = "character_ready"
CARD_KEY = "character_card_preview"
POOL_KEY = "character_pool_id"

_GUIDE_PHASE = "guide"


@dataclass
class CharacterContext:
    context: str
    ruleset_title: str
    core_chars: int
    scene_chars: int
    creation_chars: int
    scene_guide_chars: int
    module_count: int
    module_title: str
    module_text: str = ""
    scene_guide: str = ""


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Chat persistence — messages table (canonical) with one-shot migration from
# the legacy setup_state.character_chat blob.
# ---------------------------------------------------------------------------


async def _load_chat_history(
    db: AsyncSession, session_id: str,
) -> list[dict[str, Any]]:
    """Load setup-phase chat as legacy-shaped dicts. Reads guide-tagged rows
    from the messages table, ordered by created_at."""
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    rows = (await db.execute(stmt)).scalars().all()
    out: list[dict[str, Any]] = []
    for m in rows:
        meta = m.metadata_json or {}
        if meta.get("phase") and meta["phase"] != _GUIDE_PHASE:
            # IC / break messages don't belong in the setup chat view.
            continue
        thinking = meta.get("thinking_steps") or []
        clean_meta = {
            k: v for k, v in meta.items()
            if k not in ("phase", "thinking_steps")
        }
        # Normalize role: messages.role uses "gm" for the GM; legacy chat
        # used "assistant". Keep "assistant" in the dict shape because the
        # frontend expects it.
        role = "assistant" if m.role == "gm" else m.role
        out.append({
            "id": m.id,
            "role": role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else "",
            "thinking_steps": list(thinking),
            "metadata": clean_meta,
        })
    return out


async def _save_chat_message(
    db: AsyncSession,
    session_id: str,
    role: str,
    content: str,
    *,
    thinking_steps: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    """Append one chat row. role can be 'user' / 'assistant' / 'gm'.
    Returns the inserted message id, or None if the row was rejected
    (empty content / unknown role)."""
    if not content:
        return None
    db_role = "gm" if role == "assistant" else role
    if db_role not in ("user", "gm", "system", "dice"):
        # Defensive: messages table only allows the four canonical roles.
        return None
    meta: dict[str, Any] = dict(metadata or {})
    meta["phase"] = _GUIDE_PHASE
    if thinking_steps:
        meta["thinking_steps"] = list(thinking_steps)
    msg_id = str(uuid.uuid4())
    msg = Message(
        id=msg_id,
        session_id=session_id,
        role=db_role,
        content=content,
        metadata_json=meta or None,
    )
    db.add(msg)
    return msg_id


def _build_bp_snapshot(
    session: GameSession,
    *,
    chat_until_message_id: str | None,
) -> dict[str, Any]:
    """Capture BP2 + BP3 (non-chat) state for embedding into a GM message's
    metadata. BP1 is intentionally omitted — it's stable ruleset-level data
    we read live. BP3.chat is reconstructed by the frontend from the
    messages table using `chat_until_message_id` as the cutoff."""
    setup = session.setup_state if isinstance(session.setup_state, dict) else {}
    mem = session.memory_state if isinstance(session.memory_state, dict) else {}
    pc = session.character if isinstance(session.character, dict) and session.character else None
    draft = setup.get(CARD_KEY) if isinstance(setup.get(CARD_KEY), dict) else None
    return {
        "chat_until_message_id": chat_until_message_id,
        "memory_state": dict(mem),
        "narrative_summary": session.narrative_summary or "",
        "pc": pc,
        "draft_card": draft,
        "ready": bool(setup.get(READY_KEY) or False),
        "dice_history": list(session.dice_history or []),
        "module_state": session.module_state if isinstance(session.module_state, dict) else {},
    }


async def _migrate_chat_if_needed(
    db: AsyncSession, session: GameSession,
) -> None:
    """One-shot: copy `setup_state.character_chat` rows into messages table.

    Idempotent — only runs when the legacy blob has entries. Commits its own
    changes so the messages table is authoritative immediately after this
    returns; callers don't need to coordinate with the outer transaction."""
    setup = session.setup_state if isinstance(session.setup_state, dict) else {}
    legacy_chat = setup.get(CHAT_KEY)
    if not isinstance(legacy_chat, list) or not legacy_chat:
        return
    existing = await _count_messages(db, session.id)
    new_setup = dict(setup)
    new_setup.pop(CHAT_KEY, None)
    if existing == 0:
        for item in legacy_chat:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "")
            content = str(item.get("content") or "")
            if not content:
                continue
            await _save_chat_message(
                db, session.id, role, content,
                thinking_steps=item.get("thinking_steps") or None,
                metadata=item.get("metadata") or None,
            )
    session.setup_state = new_setup
    await db.commit()
    await db.refresh(session)


async def _count_messages(db: AsyncSession, session_id: str) -> int:
    from sqlalchemy import func
    return (await db.execute(
        select(func.count(Message.id)).where(Message.session_id == session_id)
    )).scalar() or 0


def character_snapshot(
    session: GameSession,
    chat: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the snapshot returned by character-draft API responses.

    `chat` should be passed in by callers that have already loaded the
    messages list (the canonical path). When omitted we fall back to the
    legacy setup_state blob — useful for migration test paths only."""
    state = session.setup_state if isinstance(session.setup_state, dict) else {}
    card = state.get(CARD_KEY) or session.character or None
    if chat is None:
        chat = _normalize_chat(state.get(CHAT_KEY))
    return {
        "messages": chat,
        "character": card,
        "ready": bool(state.get(READY_KEY) or card),
        "pool_id": state.get(POOL_KEY),
    }


def _copy_setup_state(session: GameSession) -> dict[str, Any]:
    return dict(session.setup_state or {}) if isinstance(session.setup_state, dict) else {}


def _normalize_chat(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw[-40:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        message: dict[str, Any] = {
            "role": role,
            "content": content,
            "created_at": str(item.get("created_at") or ""),
        }
        thinking = item.get("thinking_steps")
        if isinstance(thinking, list):
            message["thinking_steps"] = [
                str(step) for step in thinking if str(step or "").strip()
            ]
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            message["metadata"] = metadata
        out.append(message)
    return out


def _draft_message(
    role: str,
    content: str,
    *,
    metadata: dict[str, Any] | None = None,
    thinking_steps: list[str] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": role,
        "content": content,
        "created_at": utc_iso(),
    }
    if metadata:
        message["metadata"] = metadata
    if thinking_steps:
        message["thinking_steps"] = list(thinking_steps)
    return message


def _chat_messages(chat: list[dict[str, Any]]) -> list[ChatMessage]:
    return [
        ChatMessage(role=m["role"], content=m["content"])
        for m in chat
        if m.get("role") in {"user", "assistant"} and m.get("content")
    ]


def _format_transcript(chat: list[dict[str, Any]]) -> str:
    lines = []
    for msg in chat[-24:]:
        label = "Player" if msg["role"] == "user" else "Guide"
        lines.append(f"[{label}] {msg['content']}")
    return "\n\n".join(lines)
