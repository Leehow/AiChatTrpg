"""Post-turn auto-memory extractor (chatrpg, path B).

After the GM streams a reply, run one extra small-model LLM call that scans
the player message + GM narration and emits structured patches the GM may
have missed (or chose not to surface as `[UPDATE_MEMORY]` markers). Output:

  events            — 1-line summaries of what just happened (timeline)
  plot_threads      — upsert-by-title open story threads
  player_discoveries — what the player learned this turn

Stored in `memory_state.recent_events[]` (FIFO cap), `memory_state.plot_threads[]`
(upsert by title), `memory_state.player_discoveries[]` (FIFO cap). Other
chatlab features (game_counters / world_clocks / NPC sync / breakpoints) are
deferred — they need ruleset/runtime machinery chatrpg doesn't have yet.

Latency budget: this runs synchronously inside the IC SSE turn, after the GM
content has streamed. Player sees the message immediately; a brief 2–4s pause
follows before the `done` event lands. Failures are swallowed — if the
auto-memory call errors, the turn still saves cleanly.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from llm import ChatMessage as LlmChatMessage
from llm import build_client
from orm.models import GameSession
from services.character_creator import _resolve_model
from services.trpg_context.models import Visibility
from services.trpg_memory.evidence import TextSource, make_source_evidence
from services.trpg_memory.memory_models import (
    EvidenceRole,
    MemoryIdentityScope,
    MemoryKind,
    MemoryOperation,
    MemoryProposal,
    SourceEvidence,
    TruthStatus,
)
from services.trpg_npc.models import GameEvent
from services.trpg_runtime.event_sourcing import (
    event_memory_subjects,
    event_owner_id,
    is_player_visible_event,
    semantic_event_view,
)

logger = logging.getLogger("chatrpg.trpg.auto_memory")

# How much to keep around. These are soft caps — older entries get rolled
# off the front (oldest → newest queue) when the cap is exceeded.
_MAX_RECENT_EVENTS = 60
_MAX_PLOT_THREADS = 40
_MAX_PLAYER_DISCOVERIES = 60

# Rough token budget for the LLM scan. Chatlab caps GM at 3000 chars; we use
# the same so the prompt stays small and the LLM stays focused.
_MAX_GM_CHARS_FOR_PROMPT = 3000
_MAX_PLAYER_CHARS_FOR_PROMPT = 600


@dataclass
class AutoMemoryResult:
    events: list[str] = field(default_factory=list)
    plot_threads: list[dict[str, Any]] = field(default_factory=list)
    discoveries: list[str] = field(default_factory=list)
    raw_response: str = ""
    skipped_reason: str = ""

    def is_empty(self) -> bool:
        return not (self.events or self.plot_threads or self.discoveries)


_PROMPT = """You are a TRPG game-state tracker. Read the player's action and the GM narration that just happened, then extract any state changes the GM may have left implicit.

## Current Scene: {current_scene}
## Existing Plot Threads (upsert by title; do not duplicate):
{existing_threads}
## Player Action
{player_message}

## GM Narration
{gm_content}

Output ONLY valid JSON, matching this schema. Omit fields with no entries:

{{
  "events": ["one-line summary of what just happened, present tense, ≤80 chars"],
  "plot_threads": [
    {{"title": "short thread name (snake_case_lower or short phrase)", "status": "introduced" | "active" | "resolved", "summary": "one sentence of current status"}}
  ],
  "discoveries": ["what the player just learned, ≤80 chars each"]
}}

Rules:
- Events are facts that occurred IN-FICTION this turn (not OOC chatter, not GM stage directions). 1–4 entries max.
- Plot threads represent open story arcs the player is tracking. Use title to deduplicate against the existing list above; if a thread there already exists, keep its title verbatim and update status/summary. 0–4 entries max.
- Discoveries are concrete things the player learned (clues, NPC reveals, environmental facts). 0–4 entries max.
- Skip everything that is purely description / sensory flavor with no state change.
- If nothing notable happened, output `{{}}`.
- Match the language of the player and GM (Chinese if they're in Chinese; English if English)."""


def _build_existing_threads_block(memory_state: dict[str, Any]) -> str:
    threads = memory_state.get("plot_threads")
    if not isinstance(threads, list) or not threads:
        return "(none yet)"
    lines: list[str] = []
    for t in threads[-20:]:
        if not isinstance(t, dict):
            continue
        title = str(t.get("title") or t.get("key") or t.get("name") or "?")
        status = str(t.get("status") or "active")
        summary = str(t.get("summary") or t.get("body") or "")[:80]
        lines.append(f"- {title} ({status}) — {summary}")
    return "\n".join(lines) if lines else "(none yet)"


async def run_auto_memory_update(
    db: AsyncSession,
    session: GameSession,
    *,
    gm_content: str,
    player_message: str,
) -> AutoMemoryResult:
    """One small-model LLM call → memory_state patch. Errors are caught and
    surfaced via `result.skipped_reason`; never raise to the IC turn caller."""
    result = AutoMemoryResult()
    if not gm_content or not gm_content.strip():
        result.skipped_reason = "empty_gm_content"
        return result

    memory_state = (
        session.memory_state
        if isinstance(session.memory_state, dict) else {}
    )
    module_state = (
        session.module_state
        if isinstance(session.module_state, dict) else {}
    )
    current_scene = str(
        module_state.get("scene")
        or (memory_state.get("world_facts") or {}).get("current_scene")
        if isinstance(memory_state.get("world_facts"), dict)
        else module_state.get("scene") or "unknown"
    )

    prompt = _PROMPT.format(
        current_scene=current_scene or "unknown",
        existing_threads=_build_existing_threads_block(memory_state),
        player_message=(player_message or "")[:_MAX_PLAYER_CHARS_FOR_PROMPT],
        gm_content=(gm_content or "")[:_MAX_GM_CHARS_FOR_PROMPT],
    )

    try:
        provider, model_name, api_key, base_url = await _resolve_model(db)
    except Exception as exc:  # pragma: no cover - defensive
        result.skipped_reason = f"resolve_model_failed: {exc}"
        return result

    try:
        client = build_client(provider, model_name, api_key, base_url)
        chunks: list[str] = []
        async for chunk in client.stream_chat(
            [LlmChatMessage(role="user", content=prompt)],
            temperature=0.2,
        ):
            if chunk.delta:
                chunks.append(chunk.delta)
        raw = "".join(chunks).strip()
        result.raw_response = raw
    except Exception as exc:
        logger.warning("auto_memory llm call failed: %s", exc, exc_info=True)
        result.skipped_reason = f"llm_failed: {type(exc).__name__}"
        return result

    parsed = _parse_json_object(raw)
    if not isinstance(parsed, dict):
        result.skipped_reason = "non_dict_output"
        return result

    result.events = _coerce_str_list(parsed.get("events"), max_items=4, max_len=200)
    result.discoveries = _coerce_str_list(
        parsed.get("discoveries"), max_items=4, max_len=200,
    )
    result.plot_threads = _coerce_thread_list(
        parsed.get("plot_threads"), max_items=4,
    )
    return result


def apply_auto_memory(
    session: GameSession,
    result: AutoMemoryResult,
    *,
    turn_marker: str = "",
) -> dict[str, int]:
    """Persist the auto-memory result onto session.memory_state.

    `turn_marker` (optional) is stamped on each entry so debug UIs can group
    them by turn. Caller is responsible for flush/commit."""
    if result.is_empty():
        return {"events": 0, "plot_threads": 0, "discoveries": 0}

    memory_state = (
        dict(session.memory_state)
        if isinstance(session.memory_state, dict) else {}
    )

    summary = {
        "events": len(result.events),
        "plot_threads_upserted": 0,
        "plot_threads_added": 0,
        "discoveries": len(result.discoveries),
    }

    if result.events:
        recent = memory_state.get("recent_events")
        if not isinstance(recent, list):
            recent = []
        for ev in result.events:
            recent.append({"summary": ev, "turn": turn_marker})
        memory_state["recent_events"] = recent[-_MAX_RECENT_EVENTS:]

    if result.discoveries:
        disc = memory_state.get("player_discoveries")
        if not isinstance(disc, list):
            disc = []
        for d in result.discoveries:
            disc.append({"summary": d, "turn": turn_marker})
        memory_state["player_discoveries"] = disc[-_MAX_PLAYER_DISCOVERIES:]

    if result.plot_threads:
        threads = memory_state.get("plot_threads")
        if not isinstance(threads, list):
            threads = []
        # Build title→index map for upsert.
        idx_by_title: dict[str, int] = {}
        for i, t in enumerate(threads):
            if isinstance(t, dict):
                tt = _normalize_title(t.get("title") or t.get("key") or t.get("name"))
                if tt:
                    idx_by_title[tt] = i

        for incoming in result.plot_threads:
            title_norm = _normalize_title(incoming.get("title"))
            if not title_norm:
                continue
            if title_norm in idx_by_title:
                existing = threads[idx_by_title[title_norm]]
                if isinstance(existing, dict):
                    existing["status"] = incoming.get("status") or existing.get("status") or "active"
                    if incoming.get("summary"):
                        existing["summary"] = incoming["summary"]
                    if turn_marker:
                        existing["last_turn"] = turn_marker
                    summary["plot_threads_upserted"] += 1
                continue
            entry = {
                "title": incoming.get("title") or title_norm,
                "status": incoming.get("status") or "active",
                "summary": incoming.get("summary") or "",
            }
            if turn_marker:
                entry["first_turn"] = turn_marker
                entry["last_turn"] = turn_marker
            threads.append(entry)
            summary["plot_threads_added"] += 1

        memory_state["plot_threads"] = threads[-_MAX_PLOT_THREADS:]

    session.memory_state = memory_state
    flag_modified(session, "memory_state")
    return summary


def build_auto_memory_proposals(
    result: AutoMemoryResult,
    *,
    player_message: str,
    gm_content: str,
    turn_marker: str,
) -> list[MemoryProposal]:
    """Translate the legacy auto-memory result into commit-gated proposals.

    V3 keeps the legacy JSON buckets as an optional compatibility projection,
    but each proposal now carries its own evidence span and identity scope.
    """

    if result.is_empty():
        return []
    source_turn = turn_marker or "turn_unknown"
    proposals: list[MemoryProposal] = []

    for index, event in enumerate(result.events):
        evidence = _source_evidence_for_memory(
            event,
            player_message=player_message,
            gm_content=gm_content,
            turn_marker=source_turn,
        )
        proposals.append(_proposal(
            kind=MemoryKind.PLOT,
            text=event,
            source_turn=source_turn,
            source_evidence=evidence,
            salience=0.55,
            tags=("auto_memory", "event"),
            identity_scope=MemoryIdentityScope.EVENT,
            metadata={"legacy_bucket": "recent_events", "index": index},
        ))

    for index, discovery in enumerate(result.discoveries):
        evidence = _source_evidence_for_memory(
            discovery,
            player_message=player_message,
            gm_content=gm_content,
            turn_marker=source_turn,
        )
        proposals.append(_proposal(
            kind=MemoryKind.CLUE,
            text=discovery,
            source_turn=source_turn,
            source_evidence=evidence,
            salience=0.75,
            tags=("auto_memory", "discovery"),
            identity_scope=MemoryIdentityScope.DURABLE_FACT,
            metadata={"legacy_bucket": "player_discoveries", "index": index},
        ))

    for index, thread in enumerate(result.plot_threads):
        title = str(thread.get("title") or "").strip()
        status = str(thread.get("status") or "active").strip() or "active"
        summary = str(thread.get("summary") or "").strip()
        text = f"{title} ({status})"
        if summary:
            text = f"{text}: {summary}"
        if not title and not summary:
            continue
        evidence = _source_evidence_for_memory(
            text,
            player_message=player_message,
            gm_content=gm_content,
            turn_marker=source_turn,
        )
        proposals.append(_proposal(
            kind=MemoryKind.PLOT,
            text=text,
            source_turn=source_turn,
            source_evidence=evidence,
            salience=0.65,
            tags=("auto_memory", "plot_thread"),
            subject_ids=("party", _normalize_title(title) or f"plot_thread_{index}"),
            identity_scope=MemoryIdentityScope.DURABLE_FACT,
            metadata={
                "legacy_bucket": "plot_threads",
                "title": title,
                "status": status,
                "summary": summary,
                "index": index,
            },
        ))

    return proposals


def build_structured_event_auto_memory_result(
    events: list[GameEvent] | tuple[GameEvent, ...],
) -> AutoMemoryResult:
    """Build a legacy-compatible summary from player-visible events only."""

    visible = [event for event in events if is_player_visible_event(event)]
    event_texts: list[str] = []
    discovery_texts: list[str] = []
    for event in visible:
        view = semantic_event_view(event)
        if not view.content:
            continue
        if view.is_discovery:
            discovery_texts.append(view.content[:200])
        else:
            event_texts.append(view.content[:200])
    return AutoMemoryResult(events=event_texts[:4], discoveries=discovery_texts[:4])


def build_structured_event_memory_proposals(
    events: list[GameEvent] | tuple[GameEvent, ...],
    *,
    turn_marker: str,
    confirmed_state_change_ids_by_event_id: dict[str, tuple[str, ...]] | None = None,
) -> list[MemoryProposal]:
    """Translate structured events directly into commit-gated proposals.

    Hidden discovery events become GM_ONLY candidates instead of flowing
    through the legacy PARTY_KNOWN discovery bucket.
    """

    proposals: list[MemoryProposal] = []
    for index, event in enumerate(events):
        view = semantic_event_view(event)
        if not view.content:
            continue
        source_turn = turn_marker or f"turn_{getattr(event, 'turn_id', '') or 'unknown'}"
        evidence = SourceEvidence(
            text=view.content[:500],
            role=EvidenceRole.STRUCTURED_EVENT,
            source_turn_id=source_turn,
            source_event_id=event.event_id,
        )
        tags = ["structured_event", view.normalized_type]
        if view.is_discovery:
            tags.append("discovery")
        if view.is_plot:
            tags.append("plot_thread")

        event_confirmed_change_ids = tuple(
            (confirmed_state_change_ids_by_event_id or {}).get(event.event_id, ())
        )
        proposals.append(MemoryProposal(
            operation=MemoryOperation.ADD,
            kind=view.memory_kind,
            text=view.content[:500],
            visibility=view.visibility,
            owner_id=event_owner_id(view),
            subject_ids=event_memory_subjects(view),
            source_turn_ids=(source_turn,),
            source_quote=evidence.text,
            source_quotes=(evidence,),
            source_event_ids=(event.event_id,),
            confirmed_state_change_ids=event_confirmed_change_ids,
            confidence=0.9 if view.player_visible else 0.85,
            salience=0.78 if view.is_discovery else 0.62,
            truth_status=view.truth_status,
            identity_scope=MemoryIdentityScope.DURABLE_FACT,
            tags=tuple(tags),
            metadata={
                "legacy_bucket": "player_discoveries"
                if view.is_discovery and view.player_visible
                else "structured_events",
                "structured_event_type": getattr(event, "type", ""),
                "source_event_id": event.event_id,
                "player_visible": view.player_visible,
                "index": index,
            },
        ))
    return proposals


# ---------------------------------------------------------------------------
# helpers


def _parse_json_object(text: str) -> Any:
    if not text:
        return None
    # Strip markdown fences if the model wraps output in ```json ... ```
    cleaned = re.sub(r"^```[a-z]*\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except (ValueError, TypeError):
        # Fallback: locate the first balanced {...} block.
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except (ValueError, TypeError):
                return None
    return None


def _proposal(
    *,
    kind: MemoryKind,
    text: str,
    source_turn: str,
    source_evidence: SourceEvidence | None,
    salience: float,
    tags: tuple[str, ...],
    subject_ids: tuple[str, ...] = ("party",),
    identity_scope: MemoryIdentityScope = MemoryIdentityScope.DURABLE_FACT,
    metadata: dict[str, Any] | None = None,
) -> MemoryProposal:
    evidence_tuple = (source_evidence,) if source_evidence is not None else ()
    legacy_quote = source_evidence.text if source_evidence is not None else ""
    return MemoryProposal(
        operation=MemoryOperation.ADD,
        kind=kind,
        text=str(text or "").strip()[:500],
        visibility=Visibility.PARTY_KNOWN,
        owner_id=None,
        subject_ids=tuple(s for s in subject_ids if s),
        source_turn_ids=(source_turn,),
        source_quote=legacy_quote,
        source_quotes=evidence_tuple,
        confidence=0.75,
        salience=salience,
        truth_status=TruthStatus.TRUE,
        identity_scope=identity_scope,
        tags=tags,
        metadata=metadata or {},
    )


def _source_evidence_for_memory(
    memory_text: str,
    *,
    player_message: str,
    gm_content: str,
    turn_marker: str,
) -> SourceEvidence | None:
    evidence = make_source_evidence(
        memory_text=memory_text,
        turn_id=turn_marker,
        sources=(
            TextSource(text=gm_content or "", role=EvidenceRole.GM),
            TextSource(text=player_message or "", role=EvidenceRole.PLAYER),
        ),
    )
    if evidence is not None:
        return evidence
    for text, role in ((gm_content, EvidenceRole.GM), (player_message, EvidenceRole.PLAYER)):
        cleaned = str(text or "").strip()
        if cleaned:
            return SourceEvidence(text=cleaned[:220], role=role, source_turn_id=turn_marker)
    return None


def _coerce_str_list(
    value: Any, *, max_items: int, max_len: int,
) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            s = item.strip()
            if s:
                out.append(s[:max_len])
        elif isinstance(item, dict):
            text = item.get("summary") or item.get("text") or item.get("content")
            if isinstance(text, str) and text.strip():
                out.append(text.strip()[:max_len])
        if len(out) >= max_items:
            break
    return out


def _coerce_thread_list(
    value: Any, *, max_items: int,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("key") or item.get("name")
        if not isinstance(title, str) or not title.strip():
            continue
        status = item.get("status")
        if status not in ("introduced", "active", "resolved"):
            status = "active"
        summary = item.get("summary") or item.get("description") or ""
        out.append({
            "title": title.strip()[:120],
            "status": status,
            "summary": str(summary).strip()[:300],
        })
        if len(out) >= max_items:
            break
    return out


def _normalize_title(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip()).lower()
