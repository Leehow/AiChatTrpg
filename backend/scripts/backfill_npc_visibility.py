"""Backfill ``name_revealed`` and ``player_known_name`` on existing NPCs.

Earlier sessions saved NPCs with only a single ``name`` field — sometimes
holding the true name (PC's ex-wife), sometimes a description-only label
the GM emitted because the player had not learned the name yet
(瘦长皮卡司机). The frontend now treats those two cases differently:

- Sidebar NPC panel filters to encountered NPCs and shows
  ``player_known_name`` when ``name_revealed`` is false.
- Debug ``记忆 / NPC`` panel shows the full roster and exposes both names.

This script walks every session and ensures every NPC dict has the two
new fields populated. Heuristic for legacy rows:

- ``source == "character_intake"`` or ``from_bond == True`` →
  ``name_revealed = True`` (PC's own backstory contacts).
- Everything else → ``name_revealed = False``, ``player_known_name``
  derived from description / role.

Run:
    cd backend && source .venv/bin/activate
    python scripts/backfill_npc_visibility.py
    python scripts/backfill_npc_visibility.py --dry-run
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
from services.trpg_npc.visibility import ensure_npc_visibility_fields


def _default_revealed_for(npc: dict) -> bool:
    """Legacy heuristic.

    The new ``name_revealed`` flag did not exist when the existing rows
    were written, so the only signal we have is what was on screen.
    Whatever the ``name`` field currently holds — true name like "Vern"
    or description-style label like "瘦长皮卡司机" — is what the player
    has been looking at. Treat that as ``player_known_name`` and mark
    ``name_revealed = True`` so the sidebar keeps showing the same
    string. The going-forward code (``ensure_npc_visibility_fields``
    called with ``default_revealed=False`` from new IC creation paths)
    is what enforces the hidden-name behaviour for fresh encounter
    NPCs.

    The one exception: NPCs that were never even mentioned in IC (no
    ``last_seen_scene``) and don't come from the PC's bond network are
    GM-staged characters waiting to appear. Those default to hidden so
    they pick up a description-derived label on first paint.
    """
    if npc.get("from_bond") is True:
        return True
    source = str(npc.get("source") or "").strip().lower()
    if source in {"character_intake", "pool", "imported"}:
        return True
    if str(npc.get("last_seen_scene") or "").strip():
        return True
    return False


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

            session_changed = False
            for npc in npcs:
                if not isinstance(npc, dict):
                    continue
                changed = ensure_npc_visibility_fields(
                    npc,
                    default_revealed=_default_revealed_for(npc),
                )
                if changed:
                    npcs_touched += 1
                    session_changed = True
                    if dry_run:
                        print(
                            f"  [{sess.id}] {npc.get('key', '?'):>30} "
                            f"name_revealed={npc.get('name_revealed')} "
                            f"player_known_name={npc.get('player_known_name')!r}"
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
