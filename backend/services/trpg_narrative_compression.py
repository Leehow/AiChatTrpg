"""Rolling narrative summary for long IC sessions (chatrpg, path B).

The IC chat history grows unbounded, but each turn only sends the most recent
N messages to the LLM (via `_RECENT_HISTORY_LIMIT` in `trpg_ic_runner`).
Without compression, anything older falls out of the GM's awareness — the
GM "forgets" early plot beats. This module folds dropped messages into
`session.narrative_summary` (a rolling LLM-compressed text) which the
framework already injects into BP2 of the IC prompt.

Layered with auto-memory: structured updates (events / threads / discoveries)
go to `memory_state` buckets via `trpg_auto_memory`; this module owns the
free-form narrative running summary.

Trigger semantics (mirroring chatlab):
  - `total_msgs - last_summarized >= COMPRESSION_THRESHOLD` AND game started
  - Dropped = messages older than the live recent window (already aged out)
  - After compression, `last_summarized_msg_count` advances so subsequent
    runs only fold the newly-aged messages.

Latency: one extra small-model call. Runs synchronously in the IC turn
*after* auto-memory; only fires when threshold is met (so most turns skip).
Failures fall back to a deterministic concat-and-trim summary so memory
keeps moving even if the LLM endpoint is unreachable.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from llm import ChatMessage as LlmChatMessage
from llm import build_client
from orm.models import GameSession, Message
from services.character_creator import _resolve_model

logger = logging.getLogger("chatrpg.trpg.narrative_compression")

# How many newly-aged messages must accumulate before we run another
# compression. 6 keeps roughly 1 LLM call per ~3 turns of IC play; lower
# would be more reactive but burn tokens.
COMPRESSION_THRESHOLD = 6

# Hard cap on the rolling summary so it doesn't bloat the IC prompt over
# long sessions. Sentence-trimmed.
NARRATIVE_SUMMARY_CAP = 2400


_PROMPT = """You are a TRPG game scribe. Compress the conversation below into a concise narrative summary.

## Existing summary
{existing}

## New messages (oldest first)
{new_messages}

## Requirements
1. Merge the existing summary with the new messages and emit the FULL updated summary (not just a delta).
2. KEEP: critical scene descriptions, important player actions, dice-check outcomes and consequences, NPC reveals, plot beats, scene transitions, location moves.
3. DROP: OOC chatter, rule debates, system prompts, redundant scene re-descriptions.
4. Write in third person, past tense.
5. Organize chronologically.
6. If the existing summary is empty, simply summarize the new messages.
7. Output the summary text ONLY, no prefix, no meta commentary, no markdown headers.
8. Match the language used in the messages (Chinese narration → Chinese summary)."""


@dataclass
class CompressionResult:
    """Outcome of one compression cycle."""
    ran: bool = False
    skipped_reason: str = ""
    dropped_count: int = 0
    new_summary_chars: int = 0
    previous_summary_chars: int = 0
    new_last_summarized: int = 0


# ---------------------------------------------------------------------------
# decision


async def _count_messages(db: AsyncSession, session_id: str) -> int:
    return (await db.execute(
        select(func.count(Message.id)).where(Message.session_id == session_id)
    )).scalar() or 0


def _should_compress(
    total: int, last_summarized: int, game_started: bool, recent_keep: int,
) -> tuple[bool, str]:
    if not game_started:
        return False, "not_in_game"
    if total <= recent_keep:
        return False, "history_below_recent_window"
    if total - last_summarized < COMPRESSION_THRESHOLD:
        return False, "below_threshold"
    return True, ""


# ---------------------------------------------------------------------------
# load dropped messages (those outside the live recent window since last summarized)


async def _load_dropped_messages(
    db: AsyncSession,
    session_id: str,
    *,
    last_summarized: int,
    total: int,
    recent_keep: int,
) -> list[dict[str, Any]]:
    """Pull messages with chronological index in [last_summarized, total - recent_keep).

    Anything before `last_summarized` is already folded into the existing
    narrative_summary; anything from `total - recent_keep` onward is still in
    the live prompt window."""
    upto = total - recent_keep
    if upto <= last_summarized:
        return []
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
        .offset(last_summarized)
        .limit(upto - last_summarized)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    out: list[dict[str, Any]] = []
    for m in rows:
        # Skip system placeholders and dice rows from compression — they're
        # mechanical artifacts, not narrative beats.
        if m.role not in ("user", "gm"):
            continue
        content = (m.content or "").strip()
        if not content:
            continue
        out.append({
            "role": "user" if m.role == "user" else "assistant",
            "content": content,
        })
    return out


# ---------------------------------------------------------------------------
# format + LLM call


def _format_messages_for_compression(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for m in messages:
        role = m.get("role")
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        tag = "玩家" if role == "user" else "GM"
        lines.append(f"{tag}: {content}")
    return "\n\n".join(lines)


def _trim_at_sentence(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "").strip())
    if len(text) <= max_chars:
        return text
    for sep in ("。", "；", "\n", ".", "！", "？"):
        idx = text.rfind(sep, 0, max_chars)
        if idx > max_chars // 3:
            return text[:idx + 1].strip()
    return text[:max_chars].strip()


def _fallback_summary(
    existing_summary: str, dropped_messages: list[dict[str, Any]],
) -> str:
    """Deterministic concat-and-trim used when the LLM call fails."""
    new_text = _format_messages_for_compression(dropped_messages)
    if not new_text.strip():
        return existing_summary
    new_lines = [line for line in new_text.splitlines() if line.strip()]
    excerpt = "\n".join(new_lines[-12:])
    merged = f"{existing_summary.strip()}\n{excerpt}".strip()
    return _trim_at_sentence(merged, NARRATIVE_SUMMARY_CAP)


async def _call_llm(
    db: AsyncSession,
    *,
    existing_summary: str,
    dropped_messages: list[dict[str, Any]],
) -> str:
    new_text = _format_messages_for_compression(dropped_messages)
    prompt = _PROMPT.format(
        existing=existing_summary or "(空)",
        new_messages=new_text,
    )
    provider, model_name, api_key, base_url = await _resolve_model(db)
    client = build_client(provider, model_name, api_key, base_url)
    chunks: list[str] = []
    async for chunk in client.stream_chat(
        [LlmChatMessage(role="user", content=prompt)],
        temperature=0.2,
    ):
        if chunk.delta:
            chunks.append(chunk.delta)
    raw = "".join(chunks).strip()
    return _trim_at_sentence(raw, NARRATIVE_SUMMARY_CAP)


# ---------------------------------------------------------------------------
# public


async def maybe_compress_narrative(
    db: AsyncSession,
    session: GameSession,
    *,
    recent_keep: int,
) -> CompressionResult:
    """Compress aged-out messages into `session.narrative_summary` if the
    threshold is met. No-op otherwise. Caller persists; this function
    mutates the ORM row but does not commit."""
    setup = (
        session.setup_state
        if isinstance(session.setup_state, dict) else {}
    )
    game_started = bool(setup.get("game_started") or setup.get("completed"))

    total = await _count_messages(db, session.id)
    last_summarized = int(session.last_summarized_msg_count or 0)

    should_run, reason = _should_compress(
        total, last_summarized, game_started, recent_keep,
    )
    if not should_run:
        return CompressionResult(skipped_reason=reason)

    dropped = await _load_dropped_messages(
        db, session.id,
        last_summarized=last_summarized,
        total=total,
        recent_keep=recent_keep,
    )
    if not dropped:
        # All folded already; just bump the marker so we don't re-check on
        # every following turn until threshold accumulates again.
        session.last_summarized_msg_count = max(0, total - recent_keep)
        return CompressionResult(skipped_reason="no_dropped_messages")

    existing = str(session.narrative_summary or "")

    try:
        new_summary = await _call_llm(
            db,
            existing_summary=existing,
            dropped_messages=dropped,
        )
        if not new_summary:
            new_summary = _fallback_summary(existing, dropped)
    except Exception as exc:
        logger.warning("[narrative-compression] LLM failed: %s", exc, exc_info=True)
        new_summary = _fallback_summary(existing, dropped)

    session.narrative_summary = new_summary
    session.last_summarized_msg_count = total - recent_keep

    return CompressionResult(
        ran=True,
        dropped_count=len(dropped),
        new_summary_chars=len(new_summary),
        previous_summary_chars=len(existing),
        new_last_summarized=session.last_summarized_msg_count,
    )
