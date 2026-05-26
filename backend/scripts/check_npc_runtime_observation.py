"""Inspect per-turn NPC Runtime V2 observations stored on GM messages.

Run:
    cd backend && source .venv/bin/activate
    python scripts/check_npc_runtime_observation.py --limit 20
    python scripts/check_npc_runtime_observation.py --session-id <id> --json
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
from orm.models import GameSession, Message


async def main(
    *,
    session_id: str,
    limit: int,
    max_messages: int,
    max_details: int,
    json_output: bool,
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
            msg_stmt = (
                select(Message)
                .where(Message.session_id == str(session.id), Message.role == "gm")
                .order_by(Message.created_at.desc())
            )
            if max_messages > 0:
                msg_stmt = msg_stmt.limit(max_messages)
            messages = list((await db.execute(msg_stmt)).scalars().all())
            items.append(_session_payload(session, messages=messages, max_details=max_details))

    payload = _build_payload(items)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        _print_human(payload)
    return 0


def _session_payload(
    session: GameSession,
    *,
    messages: list[Message],
    max_details: int,
) -> dict[str, Any]:
    source_counts: Counter[str] = Counter()
    resolver_decisions: Counter[str] = Counter()
    structured_event_types: Counter[str] = Counter()
    details: list[dict[str, Any]] = []
    summary = {
        "gm_messages_seen": len(messages),
        "messages_with_runtime_read": 0,
        "messages_with_action_board_hits": 0,
        "action_board_match_count": 0,
        "llm_background_match_count": 0,
        "structured_event_count": 0,
        "structured_event_error_count": 0,
    }

    for message in messages:
        meta = message.metadata_json if isinstance(message.metadata_json, dict) else {}
        runtime_read = meta.get("npc_runtime_read") if isinstance(meta.get("npc_runtime_read"), dict) else {}
        structured = meta.get("structured_events") if isinstance(meta.get("structured_events"), dict) else {}

        if runtime_read:
            summary["messages_with_runtime_read"] += 1
            source = str(runtime_read.get("source") or "unknown")
            source_counts[source] += 1
            hits = runtime_read.get("action_board_hits") if isinstance(runtime_read.get("action_board_hits"), dict) else {}
            match_count = _int(hits.get("match_count"))
            llm_match_count = _int(hits.get("llm_background_match_count"))
            summary["action_board_match_count"] += match_count
            summary["llm_background_match_count"] += llm_match_count
            if match_count or llm_match_count:
                summary["messages_with_action_board_hits"] += 1
            for item in hits.get("resolutions") or []:
                if isinstance(item, dict):
                    resolver_decisions[str(item.get("decision") or "unknown")] += 1

        events = structured.get("events") if isinstance(structured.get("events"), list) else []
        errors = structured.get("errors") if isinstance(structured.get("errors"), list) else []
        summary["structured_event_count"] += len(events)
        summary["structured_event_error_count"] += len(errors)
        for event in events:
            if isinstance(event, dict):
                structured_event_types[str(event.get("type") or "unknown")] += 1

        if len(details) < max(0, max_details):
            details.append(_message_detail(message, runtime_read=runtime_read, structured=structured))

    summary["runtime_read_sources"] = dict(source_counts)
    summary["resolver_decisions"] = dict(resolver_decisions)
    summary["structured_event_types"] = dict(structured_event_types)
    return {
        "session_id": str(session.id),
        "summary": summary,
        "recent_messages": details,
    }


def _message_detail(
    message: Message,
    *,
    runtime_read: dict[str, Any],
    structured: dict[str, Any],
) -> dict[str, Any]:
    hits = runtime_read.get("action_board_hits") if isinstance(runtime_read.get("action_board_hits"), dict) else {}
    return {
        "message_id": message.id,
        "created_at": message.created_at,
        "source": runtime_read.get("source") if runtime_read else "",
        "matched_card_ids": hits.get("matched_card_ids", []) if hits else [],
        "match_count": _int(hits.get("match_count")) if hits else 0,
        "llm_background_match_count": _int(hits.get("llm_background_match_count")) if hits else 0,
        "structured_event_types": [
            str(event.get("type") or "unknown")
            for event in structured.get("events") or []
            if isinstance(event, dict)
        ],
        "structured_event_errors": structured.get("errors", []) if isinstance(structured.get("errors"), list) else [],
    }


def _build_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "sessions_seen": len(items),
        "gm_messages_seen": 0,
        "messages_with_runtime_read": 0,
        "messages_with_action_board_hits": 0,
        "action_board_match_count": 0,
        "llm_background_match_count": 0,
        "structured_event_count": 0,
        "structured_event_error_count": 0,
        "runtime_read_sources": {},
        "resolver_decisions": {},
        "structured_event_types": {},
    }
    source_counts: Counter[str] = Counter()
    resolver_decisions: Counter[str] = Counter()
    structured_event_types: Counter[str] = Counter()
    for item in items:
        summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
        for key in (
            "gm_messages_seen",
            "messages_with_runtime_read",
            "messages_with_action_board_hits",
            "action_board_match_count",
            "llm_background_match_count",
            "structured_event_count",
            "structured_event_error_count",
        ):
            totals[key] += _int(summary.get(key))
        source_counts.update(summary.get("runtime_read_sources") or {})
        resolver_decisions.update(summary.get("resolver_decisions") or {})
        structured_event_types.update(summary.get("structured_event_types") or {})
    totals["runtime_read_sources"] = dict(source_counts)
    totals["resolver_decisions"] = dict(resolver_decisions)
    totals["structured_event_types"] = dict(structured_event_types)
    return {"totals": totals, "sessions": items}


def _print_human(payload: dict[str, Any]) -> None:
    print("=== NPC Runtime V2 Observation Diagnostics ===")
    for item in payload["sessions"]:
        summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
        print(
            f"{item['session_id']} "
            f"gm_messages={summary.get('gm_messages_seen', 0)} "
            f"runtime_reads={summary.get('messages_with_runtime_read', 0)} "
            f"sources={summary.get('runtime_read_sources', {})} "
            f"hits={summary.get('action_board_match_count', 0)} "
            f"llm_hits={summary.get('llm_background_match_count', 0)} "
            f"structured_events={summary.get('structured_event_count', 0)} "
            f"structured_errors={summary.get('structured_event_error_count', 0)}"
        )
        decisions = summary.get("resolver_decisions") or {}
        if decisions:
            print(f"  resolver_decisions: {decisions}")
        event_types = summary.get("structured_event_types") or {}
        if event_types:
            print(f"  structured_event_types: {event_types}")
    print("\n=== totals ===")
    for key, value in payload["totals"].items():
        print(f"{key}: {value}")


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--session-id", default="", help="Inspect one session id only.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum sessions to scan; 0 means all.")
    parser.add_argument("--max-messages", type=int, default=100, help="Maximum recent GM messages per session; 0 means all.")
    parser.add_argument("--max-details", type=int, default=5, help="Recent message detail rows per session.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    raise SystemExit(
        asyncio.run(
            main(
                session_id=args.session_id,
                limit=args.limit,
                max_messages=args.max_messages,
                max_details=args.max_details,
                json_output=args.json,
            )
        )
    )
