"""Check NPC Runtime V2 tables against their JSON compatibility snapshots.

Run:
    cd backend && source .venv/bin/activate
    python scripts/check_npc_runtime_v2_tables.py --limit 20
    python scripts/check_npc_runtime_v2_tables.py --session-id <id> --json
    python scripts/check_npc_runtime_v2_tables.py --strict
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from core.database import get_session_factory
from orm.models import (
    GameSession,
    NPCRuntimeActionCard,
    NPCRuntimeEvent,
    NPCRuntimeMemory,
    NPCRuntimeProfile,
    NPCRuntimeRelationship,
    NPCRuntimeState,
)
from services.trpg_npc.runtime_diagnostics import (
    NPCRuntimeSnapshotDiagnostics,
    compare_npc_runtime_v2_snapshot,
)


async def main(
    *,
    session_id: str,
    limit: int,
    json_output: bool,
    strict: bool,
    max_details: int,
) -> int:
    factory = get_session_factory()
    results: list[NPCRuntimeSnapshotDiagnostics] = []

    async with factory() as db:
        stmt = select(GameSession).order_by(GameSession.updated_at.desc())
        if session_id:
            stmt = stmt.where(GameSession.id == session_id)
        if limit > 0:
            stmt = stmt.limit(limit)
        sessions = list((await db.execute(stmt)).scalars().all())

        for session in sessions:
            rows = await _load_runtime_rows(db, str(session.id))
            results.append(compare_npc_runtime_v2_snapshot(session, **rows))

    payload = _build_payload(results)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        _print_human(results, max_details=max_details)

    if strict and payload["totals"]["mismatches"] > 0:
        return 1
    return 0


async def _load_runtime_rows(db, session_id: str) -> dict[str, list[Any]]:
    profiles = list((
        await db.execute(
            select(NPCRuntimeProfile)
            .where(NPCRuntimeProfile.session_id == session_id)
            .order_by(NPCRuntimeProfile.npc_id.asc())
        )
    ).scalars().all())
    states = list((
        await db.execute(
            select(NPCRuntimeState)
            .where(NPCRuntimeState.session_id == session_id)
            .order_by(NPCRuntimeState.npc_id.asc())
        )
    ).scalars().all())
    relationships = list((
        await db.execute(
            select(NPCRuntimeRelationship)
            .where(NPCRuntimeRelationship.session_id == session_id)
            .order_by(
                NPCRuntimeRelationship.npc_id.asc(),
                NPCRuntimeRelationship.target_id.asc(),
            )
        )
    ).scalars().all())
    memories = list((
        await db.execute(
            select(NPCRuntimeMemory)
            .where(NPCRuntimeMemory.session_id == session_id)
            .order_by(NPCRuntimeMemory.npc_id.asc(), NPCRuntimeMemory.created_at.asc())
        )
    ).scalars().all())
    action_cards = list((
        await db.execute(
            select(NPCRuntimeActionCard)
            .where(NPCRuntimeActionCard.session_id == session_id)
            .order_by(
                NPCRuntimeActionCard.scene_id.asc(),
                NPCRuntimeActionCard.based_on_turn_id.asc(),
                NPCRuntimeActionCard.card_id.asc(),
            )
        )
    ).scalars().all())
    events = list((
        await db.execute(
            select(NPCRuntimeEvent)
            .where(NPCRuntimeEvent.session_id == session_id)
            .order_by(NPCRuntimeEvent.turn_id.asc(), NPCRuntimeEvent.event_id.asc())
        )
    ).scalars().all())
    return {
        "profiles": profiles,
        "states": states,
        "relationships": relationships,
        "memories": memories,
        "action_cards": action_cards,
        "events": events,
    }


def _build_payload(results: list[NPCRuntimeSnapshotDiagnostics]) -> dict[str, Any]:
    totals = {
        "sessions_seen": len(results),
        "sessions_ok": sum(1 for result in results if result.ok),
        "mismatches": sum(len(result.mismatches) for result in results),
        "warnings": sum(len(result.warnings) for result in results),
    }
    table_counts: dict[str, int] = {}
    json_counts: dict[str, int] = {}
    for result in results:
        for key, value in result.table_counts.items():
            table_counts[key] = table_counts.get(key, 0) + int(value)
        for key, value in result.json_counts.items():
            json_counts[key] = json_counts.get(key, 0) + int(value)
    totals["table_counts"] = table_counts
    totals["json_counts"] = json_counts
    return {
        "totals": totals,
        "sessions": [result.to_dict() for result in results],
    }


def _print_human(results: list[NPCRuntimeSnapshotDiagnostics], *, max_details: int) -> None:
    payload = _build_payload(results)
    print("=== NPC Runtime V2 table diagnostics ===")
    for result in results:
        status = "OK" if result.ok else "MISMATCH"
        print(
            f"[{status}] {result.session_id} "
            f"mismatches={len(result.mismatches)} warnings={len(result.warnings)} "
            f"tables={result.table_counts} json={result.json_counts}"
        )
        details = result.mismatches + result.warnings
        for item in details[:max(0, max_details)]:
            print(f"  - {item}")
        if max_details >= 0 and len(details) > max_details:
            print(f"  ... {len(details) - max_details} more")
    print("\n=== totals ===")
    for key, value in payload["totals"].items():
        print(f"{key}: {value}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--session-id", default="", help="Check one session id only.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum sessions to scan; 0 means all.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if any mismatch is found.")
    parser.add_argument("--max-details", type=int, default=10, help="Maximum detail rows per session.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    raise SystemExit(
        asyncio.run(
            main(
                session_id=args.session_id,
                limit=args.limit,
                json_output=args.json,
                strict=args.strict,
                max_details=args.max_details,
            )
        )
    )
