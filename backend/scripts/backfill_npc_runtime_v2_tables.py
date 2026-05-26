"""Backfill NPC Runtime V2 JSON snapshots into normalized runtime tables.

Run:
    cd backend && source .venv/bin/activate
    python scripts/backfill_npc_runtime_v2_tables.py --dry-run
    python scripts/backfill_npc_runtime_v2_tables.py

The read path can fall back to JSON, so this script is safe to run repeatedly:
rows are upserted by stable ids.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from core.database import get_engine, get_session_factory
from orm.models import Base, GameSession, Message
from services.trpg_npc.runtime_persistence import (
    build_npc_runtime_v2_table_payloads_from_session_snapshot,
    persist_npc_runtime_v2_table_payload,
)


async def main(*, dry_run: bool, session_id: str, limit: int, include_inferred_state: bool) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = get_session_factory()
    totals = {
        "sessions_seen": 0,
        "sessions_with_payload": 0,
        "profiles": 0,
        "states": 0,
        "relationships": 0,
        "memories": 0,
        "action_cards": 0,
        "events": 0,
    }

    async with factory() as db:
        stmt = select(GameSession).order_by(GameSession.updated_at.desc())
        if session_id:
            stmt = stmt.where(GameSession.id == session_id)
        if limit > 0:
            stmt = stmt.limit(limit)
        sessions = list((await db.execute(stmt)).scalars().all())

        for session in sessions:
            totals["sessions_seen"] += 1
            messages = list((
                await db.execute(
                    select(Message)
                    .where(Message.session_id == session.id)
                    .order_by(Message.created_at.asc())
                )
            ).scalars().all())
            payload = build_npc_runtime_v2_table_payloads_from_session_snapshot(
                session,
                messages=messages,
                include_inferred_state=include_inferred_state,
            )
            summary = payload.summary()
            if not any(summary.values()):
                continue
            totals["sessions_with_payload"] += 1
            for key, value in summary.items():
                totals[key] += value
            print(f"[{session.id}] {summary}")
            if not dry_run:
                await persist_npc_runtime_v2_table_payload(db, payload)

        if not dry_run:
            await db.commit()

    print("\n=== done ===")
    for key, value in totals.items():
        print(f"{key}: {value}")
    print(f"dry_run: {dry_run}")
    print(f"include_inferred_state: {include_inferred_state}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--session-id", default="", help="Backfill one session id only.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum sessions to scan; 0 means all.")
    parser.add_argument(
        "--include-inferred-state",
        action="store_true",
        help="Also write derived NPCState rows for NPCs without runtime_state_v2.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(
        main(
            dry_run=args.dry_run,
            session_id=args.session_id,
            limit=args.limit,
            include_inferred_state=args.include_inferred_state,
        )
    )
