"""Support and helper functions for `routes/sessions.py`.

Extracted from `sessions.py` to keep the FastAPI router file focused on
route handlers. Holds session serialization, ownership/access checks,
NPC runtime debug payload builders, and the fresh-DB SSE shim.

Public route handlers live in `routes/sessions.py` and import the helpers
from this module, so route behavior, paths, response shapes, SSE event
format, and OpenAPI compatibility are unchanged.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session_factory
from orm.models import (
    CheckLog,
    GameSession,
    NPCRuntimeActionCard,
    ParsedModule,
    Ruleset,
    TRPGMemoryItem,
    TRPGStateChange,
    TRPGTurnTrace,
    User,
)
from schemas.session import (
    CheckLogOut,
    SessionDetail,
    SessionSummary,
    TurnTraceOut,
)
from services.trpg_runtime.runtime_store import trace_row_to_dict


def _setup_state(s: GameSession) -> dict[str, Any]:
    # Older rows that pre-date the setup_state column will have None;
    # synthesise a "completed" state so they route straight into the game.
    raw = s.setup_state
    if not isinstance(raw, dict):
        return {
            "step": 0,
            "ruleset_id": s.ruleset_id,
            "module_id": None,
            "module_title": None,
            "completed": s.ruleset_id is not None,
        }
    state = dict(raw)
    if not state.get("ruleset_id") and s.ruleset_id:
        state["ruleset_id"] = s.ruleset_id
    try:
        step = int(state.get("step") or 0)
    except (TypeError, ValueError):
        step = 0
    step = max(0, min(2, step))
    if not state.get("ruleset_id"):
        step = 0
    elif step > 1 and not state.get("module_id"):
        step = 1
    state["step"] = step
    return state


def _summary(s: GameSession, ruleset_title: str, short_name: str | None) -> SessionSummary:
    return SessionSummary(
        id=s.id,
        title=s.title,
        ruleset_id=s.ruleset_id,
        ruleset_title=ruleset_title,
        ruleset_short_name=short_name,
        archived=s.archived,
        title_auto=getattr(s, "title_auto", True),
        setup_state=_setup_state(s),
        last_active_at=s.last_active_at,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _detail(s: GameSession, ruleset_title: str, short_name: str | None) -> SessionDetail:
    return SessionDetail(
        id=s.id,
        title=s.title,
        ruleset_id=s.ruleset_id,
        ruleset_title=ruleset_title,
        ruleset_short_name=short_name,
        archived=s.archived,
        title_auto=getattr(s, "title_auto", True),
        setup_state=_setup_state(s),
        last_active_at=s.last_active_at,
        created_at=s.created_at,
        updated_at=s.updated_at,
        character=s.character or {},
        module_state=s.module_state or {},
        memory_state=s.memory_state or {},
        narrative_summary=s.narrative_summary or "",
        last_summarized_msg_count=s.last_summarized_msg_count,
        dice_history=s.dice_history or [],
        narrative_style=s.narrative_style,
        difficulty_style=s.difficulty_style,
    )


def _check_log_out(log: CheckLog) -> CheckLogOut:
    return CheckLogOut(
        id=log.id,
        session_id=log.session_id,
        message_id=log.message_id,
        actor_id=log.actor_id or "",
        procedure_id=log.procedure_id or "",
        engine=log.engine or "",
        skill=log.skill or "",
        seed=log.seed or "",
        source=log.source or "",
        request=log.request_json or {},
        result=log.result_json or {},
        roll_trace=log.roll_trace_json or {},
        trace=log.trace_json or {},
        warnings=log.warnings_json or [],
        created_at=log.created_at,
    )


def _turn_trace_out(trace: TRPGTurnTrace) -> TurnTraceOut:
    return TurnTraceOut(**trace_row_to_dict(trace))


def _memory_item_debug_out(row: TRPGMemoryItem) -> dict[str, Any]:
    return {
        "memory_id": row.memory_id,
        "session_id": row.session_id,
        "campaign_id": row.campaign_id,
        "kind": row.kind,
        "text": row.text,
        "visibility": row.visibility,
        "owner_id": row.owner_id,
        "subject_ids": row.subject_ids_json or [],
        "source_turn_ids": row.source_turn_ids_json or [],
        "source_event_ids": row.source_event_ids_json or [],
        "source_quotes": row.source_quotes_json or [],
        "confirmed_state_change_ids": row.confirmed_state_change_ids_json or [],
        "identity_scope": row.identity_scope,
        "reinforcement_count": row.reinforcement_count,
        "confidence": row.confidence,
        "salience": row.salience,
        "truth_status": row.truth_status,
        "status": row.status,
        "pin_policy": row.pin_policy,
        "idempotency_key": row.idempotency_key,
        "created_at_turn": row.created_at_turn,
        "last_reinforced_turn": row.last_reinforced_turn,
        "tags": row.tags_json or [],
        "metadata": row.metadata_json or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _state_change_debug_out(row: TRPGStateChange) -> dict[str, Any]:
    return {
        "id": row.id,
        "change_id": row.change_id,
        "session_id": row.session_id,
        "campaign_id": row.campaign_id,
        "turn_id": row.turn_id,
        "change_type": row.change_type,
        "target_id": row.target_id,
        "operation": row.operation,
        "path": row.path_json or [],
        "value": row.value_json,
        "previous_value": row.previous_value_json,
        "new_value": row.new_value_json,
        "actor_id": row.actor_id,
        "visibility": row.visibility,
        "confidence": row.confidence,
        "reason": row.reason,
        "requires_rule_confirmation": row.requires_rule_confirmation,
        "rule_check_id": row.rule_check_id,
        "tags": row.tags_json or [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _count_session_rows(
    db: AsyncSession,
    model: Any,
    session_id: str,
) -> int:
    stmt = select(func.count()).select_from(model).where(model.session_id == session_id)
    return int((await db.execute(stmt)).scalar() or 0)


def _npc_runtime_action_card_payload(card: NPCRuntimeActionCard) -> dict[str, Any]:
    raw = dict(card.card_json) if isinstance(card.card_json, dict) else {}
    payload = dict(raw)
    payload.setdefault("card_id", card.card_id)
    payload.setdefault("scene_id", card.scene_id)
    payload.setdefault("npc_id", card.npc_id)
    payload.setdefault("based_on_turn_id", card.based_on_turn_id)
    payload.setdefault("valid_until_turn", card.valid_until_turn)
    payload.setdefault("priority", card.priority)
    payload.setdefault("status", card.status)
    metadata = dict(payload.get("metadata")) if isinstance(payload.get("metadata"), dict) else {}
    metadata.setdefault("planner", "llm_background")
    metadata.setdefault("source", "npc_runtime_tables")
    payload["metadata"] = metadata
    preferred = dict(payload.get("preferred_action")) if isinstance(payload.get("preferred_action"), dict) else {}
    preferred.setdefault("intent", payload.get("motivation") or "")
    preferred.setdefault("action_type", payload.get("action_type") or payload.get("type") or "")
    payload["preferred_action"] = preferred
    return payload


def _npc_runtime_action_board(cards: list[NPCRuntimeActionCard]) -> dict[str, Any]:
    scenes: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        scene_id = str(card.scene_id or "__global__")
        scenes.setdefault(scene_id, []).append(_npc_runtime_action_card_payload(card))
    return {
        "version": 2,
        "source": "npc_runtime_tables",
        "scenes": scenes,
    }


def _npc_runtime_planner_run(
    cards: list[NPCRuntimeActionCard],
    *,
    counts: dict[str, int],
) -> dict[str, Any]:
    if not cards:
        return {}
    ordered = sorted(cards, key=lambda c: (-float(c.priority or 0), c.card_id))
    selected_npc_ids = _dedupe_strings(card.npc_id for card in ordered)
    planned_card_ids = [str(card.card_id) for card in ordered]
    latest_updated = max((card.updated_at for card in ordered), default=None)
    latest_created = max((card.created_at for card in ordered), default=None)
    return {
        "mode": "llm_background_action_board",
        "source": "npc_runtime_tables",
        "status": "planned",
        "based_on_turn_id": int(ordered[0].based_on_turn_id or 0),
        "model": "runtime_table",
        "considered": counts.get("profiles", 0),
        "selected": len(selected_npc_ids),
        "selected_npc_ids": selected_npc_ids,
        "planned": len(ordered),
        "planned_card_ids": planned_card_ids,
        "persisted_action_cards": len(ordered),
        "knowledge_profile": {
            "profile_count": counts.get("profiles", 0),
            "loaded_memory_count": counts.get("memories", 0),
            "visible_memory_count": 0,
            "withheld_memory_count": counts.get("memories", 0),
            "source": "npc_runtime_tables",
        },
        "updated_at": (latest_updated or latest_created).isoformat()
        if (latest_updated or latest_created) else "",
    }


def _npc_runtime_planner_runs(
    cards: list[NPCRuntimeActionCard],
    *,
    counts: dict[str, int],
) -> list[dict[str, Any]]:
    grouped: dict[int, list[NPCRuntimeActionCard]] = {}
    for card in cards:
        grouped.setdefault(int(card.based_on_turn_id or 0), []).append(card)
    return [
        _npc_runtime_planner_run(grouped[turn], counts=counts)
        for turn in sorted(grouped)
        if grouped[turn]
    ]


def _dedupe_strings(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


async def _get_owned_session(
    db: AsyncSession, session_id: str, user: User
) -> GameSession:
    s = await db.get(GameSession, session_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "session not found")
    return s


async def _get_visible_ruleset(
    db: AsyncSession, ruleset_id: str, user: User
) -> Ruleset:
    """Mine ∪ everyone-else's-shared. Sessions are read-only consumers of
    the ruleset row, so non-owners on a shared ruleset can start a game
    with it; mutation endpoints still gate on owner_id elsewhere."""
    rs = await db.get(Ruleset, ruleset_id)
    if rs is None or not (rs.owner_id == user.id or rs.is_shared):
        raise HTTPException(404, "ruleset not found")
    return rs


async def _get_visible_module(
    db: AsyncSession, module_id: str, user: User,
) -> ParsedModule:
    module = await db.get(ParsedModule, module_id)
    if module is None or not (module.owner_id == user.id or module.is_shared):
        raise HTTPException(404, "module not found")
    return module


async def _get_ruleset_for_session(
    db: AsyncSession, session: GameSession, user: User
) -> Ruleset:
    """Resolve the ruleset for a session turn — always a fresh DB read.

    **Runtime sync invariant**: this is the single read site that backs every
    in-game turn. The async session passed in is short-lived (one per
    chat-stream request, see `_stream_with_fresh_db` below), so SQLAlchemy's
    identity map is empty on entry and `db.get()` always hits the database.

    The rule editor agent (in-place mode) mutates the bound `Ruleset.parsed_v6`
    + `Ruleset.dice_ir` columns and bumps `updated_at` on each apply (see
    `services/ruleset_drafts.apply_ops_to_draft` and the dice agent's
    `_design_dice_procedure`). Because this function never caches across
    requests, the next user message in a running session automatically picks
    up the latest rules — no explicit cache invalidation needed.

    If a future change adds session- or process-level caching, add a
    `db.refresh(rs)` here (or compare `rs.updated_at` against the cached
    `loaded_at`) to preserve this invariant.

    Design: docs/design/2026-05-01-rule-editor-agent.md §8.2
    """
    state = _setup_state(session)
    ruleset_id = session.ruleset_id or state.get("ruleset_id")
    if not ruleset_id:
        raise HTTPException(400, "choose a ruleset before creating a character")
    return await _get_visible_ruleset(db, str(ruleset_id), user)


# SSE generators outlive the handler's Depends(db_session) teardown, so they
# need their own AsyncSession — otherwise final commit/refresh hits a detached
# instance and raises InvalidRequestError.
async def _stream_with_fresh_db(
    session_id: str,
    user: User,
    runner: Callable[[AsyncSession, GameSession, Ruleset], AsyncIterator[dict]],
) -> AsyncIterator[dict]:
    factory = get_session_factory()
    async with factory() as db:
        s = await _get_owned_session(db, session_id, user)
        rs = await _get_ruleset_for_session(db, s, user)
        try:
            async for event in runner(db, s, rs):
                yield {"data": json.dumps(event, ensure_ascii=False)}
        except Exception as exc:  # pragma: no cover - defensive streaming guard
            yield {
                "data": json.dumps(
                    {
                        "type": "error",
                        "content": f"{type(exc).__name__}: {exc}",
                        "message": f"{type(exc).__name__}: {exc}",
                    },
                    ensure_ascii=False,
                )
            }
