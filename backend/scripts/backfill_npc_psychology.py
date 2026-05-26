"""Backfill ``inner_state`` and ``player_knowledge`` on existing NPCs.

These dicts didn't exist when older sessions were saved. The new
``ensure_npc_psychology`` helper populates them from the NPC's existing
description / role / from_bond fields, deriving an interest score and a
behaviour band per ChatLab's INTEREST_RUBRIC.

Run:
    cd backend && source .venv/bin/activate
    python scripts/backfill_npc_psychology.py
    python scripts/backfill_npc_psychology.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from core.database import get_session_factory
from orm.models import GameSession
from services.trpg_npc.psychology import ensure_npc_psychology


async def main(*, dry_run: bool) -> None:
    factory = get_session_factory()
    sessions_touched = 0
    npcs_touched = 0

    async with factory() as db:
        rows = (await db.execute(select(GameSession))).scalars().all()
        for sess in rows:
            mem = sess.memory_state if isinstance(sess.memory_state, dict) else None
            if not isinstance(mem, dict):
                continue
            npcs = mem.get("npcs")
            if not isinstance(npcs, list) or not npcs:
                continue

            pc = sess.character if isinstance(sess.character, dict) else None
            session_changed = False
            for npc in npcs:
                if not isinstance(npc, dict):
                    continue
                if ensure_npc_psychology(npc, pc=pc):
                    npcs_touched += 1
                    session_changed = True
                    if dry_run:
                        kn = npc.get("player_knowledge") or {}
                        inner = npc.get("inner_state") or {}
                        print(
                            f"  [{sess.id}] {npc.get('key', '?'):>30} "
                            f"interest={kn.get('interest')} "
                            f"drive={(kn.get('interest_drive') or {}).get('kind')!r} "
                            f"motivation={inner.get('motivation', '')[:40]!r}"
                        )

            if session_changed:
                sessions_touched += 1
                if not dry_run:
                    flag_modified(sess, "memory_state")

        if not dry_run:
            await db.commit()

    print(
        f"\n=== done. sessions_touched={sessions_touched} | "
        f"npcs_touched={npcs_touched} | dry_run={dry_run} ==="
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Walk all NPCs and report which fields would change without committing.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(dry_run=args.dry_run))
