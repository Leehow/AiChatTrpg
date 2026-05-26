"""Inspect NPC Runtime V2 background planner observations.

Run:
    cd backend && source .venv/bin/activate
    python scripts/check_npc_background_planner.py --limit 20
    python scripts/check_npc_background_planner.py --session-id <id> --json
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from core.database import get_session_factory
from orm.models import GameSession, NPCRuntimeActionCard
from services.trpg_npc.background_planner import background_planner_snapshot


async def main(
    *,
    session_id: str,
    limit: int,
    json_output: bool,
    max_runs: int,
) -> int:
    factory = get_session_factory()
    items: list[dict[str, Any]] = []
    async with factory() as db:
        stmt = select(GameSession).order_by(GameSession.updated_at.desc())
        if session_id:
            stmt = stmt.where(GameSession.id == session_id)
        if limit > 0:
            stmt = stmt.limit(limit)
        sessions = list((await db.execute(stmt)).scalars().all())

        for session in sessions:
            cards = list((
                await db.execute(
                    select(NPCRuntimeActionCard)
                    .where(NPCRuntimeActionCard.session_id == str(session.id))
                    .order_by(
                        NPCRuntimeActionCard.based_on_turn_id.desc(),
                        NPCRuntimeActionCard.card_id.asc(),
                    )
                )
            ).scalars().all())
            items.append(_session_payload(session, cards=cards, max_runs=max_runs))

    payload = _build_payload(items)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        _print_human(payload)
    return 0


def _session_payload(
    session: GameSession,
    *,
    cards: list[NPCRuntimeActionCard],
    max_runs: int,
) -> dict[str, Any]:
    snapshot = background_planner_snapshot(session)
    runs = snapshot.get("runs") if isinstance(snapshot.get("runs"), list) else []
    runs = [item for item in runs if isinstance(item, dict)]
    cap = max(0, int(max_runs or 0))
    latest = snapshot.get("latest") if isinstance(snapshot.get("latest"), dict) else {}
    latest_turn = _int(latest.get("based_on_turn_id"))
    llm_cards = [
        _card_payload(card, latest_turn=latest_turn)
        for card in cards
        if _is_llm_background_card(card)
    ]
    card_summary = _summarize_cards(llm_cards)
    run_summary = _summarize_runs(runs)
    return {
        "session_id": str(session.id),
        "latest": latest,
        "runs": runs[-cap:] if cap else [],
        "run_count": len(runs),
        "llm_action_card_count": len(llm_cards),
        "card_summary": card_summary,
        "run_summary": run_summary,
        "llm_action_cards": llm_cards[:20],
    }


def _build_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "sessions_seen": len(items),
        "sessions_with_runs": sum(1 for item in items if item.get("run_count", 0)),
        "planned_runs": 0,
        "skipped_runs": 0,
        "llm_action_cards": sum(int(item.get("llm_action_card_count") or 0) for item in items),
        "structured_triggers": 0,
        "legacy_triggers": 0,
        "default_triggered_cards": 0,
        "expired_llm_action_cards": 0,
        "future_llm_action_cards": 0,
        "secret_guard_transformed_cards": 0,
        "secret_guard_blocked_runs": 0,
        "invalid_planner_cards": 0,
    }
    for item in items:
        card_summary = item.get("card_summary") if isinstance(item.get("card_summary"), dict) else {}
        run_summary = item.get("run_summary") if isinstance(item.get("run_summary"), dict) else {}
        totals["structured_triggers"] += int(card_summary.get("structured_triggers") or 0)
        totals["legacy_triggers"] += int(card_summary.get("legacy_triggers") or 0)
        totals["default_triggered_cards"] += int(card_summary.get("default_triggered_cards") or 0)
        totals["expired_llm_action_cards"] += int(card_summary.get("expired_cards") or 0)
        totals["future_llm_action_cards"] += int(card_summary.get("future_cards") or 0)
        totals["secret_guard_transformed_cards"] += int(card_summary.get("secret_guard_transformed_cards") or 0)
        totals["secret_guard_blocked_runs"] += int(run_summary.get("secret_guard_blocked") or 0)
        totals["invalid_planner_cards"] += int(run_summary.get("invalid_planner_cards") or 0)
        for run in item.get("runs") or []:
            if run.get("status") == "planned":
                totals["planned_runs"] += 1
            elif run.get("status") == "skipped":
                totals["skipped_runs"] += 1
    return {"totals": totals, "sessions": items}


def _print_human(payload: dict[str, Any]) -> None:
    print("=== NPC Background Planner Diagnostics ===")
    for item in payload["sessions"]:
        latest = item.get("latest") if isinstance(item.get("latest"), dict) else {}
        status = str(latest.get("status") or "no_run")
        skipped = str(latest.get("skipped") or "")
        print(
            f"[{status}] {item['session_id']} "
            f"runs={item['run_count']} llm_cards={item['llm_action_card_count']} "
            f"turn={latest.get('based_on_turn_id', '')} "
            f"selected={latest.get('selected_npc_ids', [])} "
            f"planned_cards={latest.get('planned_card_ids', [])}"
        )
        card_summary = item.get("card_summary") if isinstance(item.get("card_summary"), dict) else {}
        run_summary = item.get("run_summary") if isinstance(item.get("run_summary"), dict) else {}
        if card_summary or run_summary:
            print(
                "  quality: "
                f"structured_triggers={card_summary.get('structured_triggers', 0)} "
                f"legacy_triggers={card_summary.get('legacy_triggers', 0)} "
                f"default_cards={card_summary.get('default_triggered_cards', 0)} "
                f"secret_guard_transformed={card_summary.get('secret_guard_transformed_cards', 0)} "
                f"secret_guard_blocked={run_summary.get('secret_guard_blocked', 0)} "
                f"invalid_cards={run_summary.get('invalid_planner_cards', 0)} "
                f"expired={card_summary.get('expired_cards', 0)} "
                f"future={card_summary.get('future_cards', 0)}"
            )
        if skipped:
            print(f"  skipped: {skipped}")
    print("\n=== totals ===")
    for key, value in payload["totals"].items():
        print(f"{key}: {value}")


def _is_llm_background_card(card: NPCRuntimeActionCard) -> bool:
    raw = card.card_json if isinstance(card.card_json, dict) else {}
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    return metadata.get("planner") == "llm_background"


def _card_payload(card: NPCRuntimeActionCard, *, latest_turn: int) -> dict[str, Any]:
    raw = card.card_json if isinstance(card.card_json, dict) else {}
    preferred = raw.get("preferred_action") if isinstance(raw.get("preferred_action"), dict) else {}
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    triggers = raw.get("trigger_conditions") if isinstance(raw.get("trigger_conditions"), list) else []
    trigger_summary = _trigger_summary(triggers)
    secret_guard = metadata.get("secret_guard") if isinstance(metadata.get("secret_guard"), dict) else {}
    valid_until = _int(card.valid_until_turn)
    based_on = _int(card.based_on_turn_id)
    return {
        "card_id": card.card_id,
        "scene_id": card.scene_id,
        "npc_id": card.npc_id,
        "based_on_turn_id": card.based_on_turn_id,
        "valid_until_turn": card.valid_until_turn,
        "priority": card.priority,
        "intent": preferred.get("intent") or raw.get("motivation") or "",
        "trigger_source": metadata.get("trigger_source") or "",
        "trigger_summary": trigger_summary,
        "secret_guard": secret_guard,
        "expired_at_latest_turn": bool(latest_turn and valid_until and valid_until < latest_turn),
        "future_at_latest_turn": bool(latest_turn and based_on and based_on > latest_turn),
        "trigger_conditions": triggers,
    }


def _summarize_cards(cards: list[dict[str, Any]]) -> dict[str, Any]:
    event_types: Counter[str] = Counter()
    topic_tags: Counter[str] = Counter()
    summary = {
        "structured_triggers": 0,
        "legacy_triggers": 0,
        "default_triggered_cards": 0,
        "expired_cards": 0,
        "future_cards": 0,
        "secret_guard_transformed_cards": 0,
    }
    for card in cards:
        trigger_summary = card.get("trigger_summary") if isinstance(card.get("trigger_summary"), dict) else {}
        summary["structured_triggers"] += int(trigger_summary.get("structured") or 0)
        summary["legacy_triggers"] += int(trigger_summary.get("legacy") or 0)
        if card.get("trigger_source") == "default":
            summary["default_triggered_cards"] += 1
        if card.get("expired_at_latest_turn"):
            summary["expired_cards"] += 1
        if card.get("future_at_latest_turn"):
            summary["future_cards"] += 1
        secret_guard = card.get("secret_guard") if isinstance(card.get("secret_guard"), dict) else {}
        if secret_guard.get("decision") == "transform":
            summary["secret_guard_transformed_cards"] += 1
        for event_type in trigger_summary.get("event_types") or []:
            event_types[str(event_type)] += 1
        for tag in trigger_summary.get("topic_tags") or []:
            topic_tags[str(tag)] += 1
    summary["event_types"] = dict(event_types)
    summary["topic_tags"] = dict(topic_tags)
    return summary


def _summarize_runs(runs: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "secret_guard_blocked": 0,
        "secret_guard_transformed": 0,
        "invalid_planner_cards": 0,
        "structured_triggers": 0,
        "legacy_triggers": 0,
    }
    for run in runs:
        summary["secret_guard_blocked"] += _int(run.get("secret_guard_blocked"))
        summary["secret_guard_transformed"] += _int(run.get("secret_guard_transformed"))
        summary["invalid_planner_cards"] += _int(run.get("invalid_planner_cards"))
        summary["structured_triggers"] += _int(run.get("structured_trigger_count"))
        summary["legacy_triggers"] += _int(run.get("legacy_trigger_count"))
    return summary


def _trigger_summary(triggers: list[Any]) -> dict[str, Any]:
    event_types: list[str] = []
    topic_tags: list[str] = []
    structured = 0
    legacy = 0
    for trigger in triggers:
        if isinstance(trigger, dict):
            structured += 1
            event_type = trigger.get("event_type")
            if event_type:
                event_types.append(str(event_type))
            for item in trigger.get("event_types") or []:
                event_types.append(str(item))
            for item in trigger.get("topic_tags") or []:
                topic_tags.append(str(item))
        elif isinstance(trigger, str):
            legacy += 1
    return {
        "structured": structured,
        "legacy": legacy,
        "event_types": sorted(set(event_types)),
        "topic_tags": sorted(set(topic_tags)),
    }


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--session-id", default="", help="Inspect one session id only.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum sessions to scan; 0 means all.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--max-runs", type=int, default=5, help="Recent stored runs to include per session.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    raise SystemExit(
        asyncio.run(
            main(
                session_id=args.session_id,
                limit=args.limit,
                json_output=args.json,
                max_runs=args.max_runs,
            )
        )
    )
