"""Batch-run the PC equipment enricher across all existing sessions.

The enricher (``services.trpg_equipment_enricher.enrich_pc_equipment``) was
introduced after several sessions had already been played. Their PC cards
carry only the GM-narrated equipment names (e.g. ``折刀``) without the
canonical ruleset fields (``impaling``, ``base_range``, ``aliases``,
``skill``) that the IC prompt now expects on every weapon/item entry. Without
those fields the GM has to guess — e.g. it cannot copy ``attacker_impaling``
into a contest marker because the PC card never had it.

This script walks every non-archived session, loads its ruleset, and runs
``enrich_pc_equipment(force=False)``. The enricher is idempotent — it stamps
``character.equipment_enriched_at`` and skips entries that already have a
canonical ``slug``, so this is safe to re-run.

Run::

    cd backend && source .venv/bin/activate
    python scripts/backfill_pc_equipment_enrichment.py
    python scripts/backfill_pc_equipment_enrichment.py --dry-run
    python scripts/backfill_pc_equipment_enrichment.py --session-id <id> --force
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from core.database import get_session_factory
from orm.models import GameSession, Ruleset
from services.trpg_equipment_enricher import enrich_pc_equipment


async def _process_one(
    db,
    sess: GameSession,
    *,
    dry_run: bool,
    force: bool,
) -> tuple[str, dict]:
    """Returns (status, info-dict-for-logging)."""
    if not isinstance(sess.character, dict) or not sess.character:
        return "no_pc_card", {}

    if not force and sess.character.get("equipment_enriched_at"):
        return "already_stamped", {"stamp": sess.character["equipment_enriched_at"]}

    ruleset_id = sess.ruleset_id
    if not ruleset_id:
        return "no_ruleset_id", {}

    ruleset = (
        await db.execute(select(Ruleset).where(Ruleset.id == ruleset_id))
    ).scalar_one_or_none()
    if ruleset is None:
        return "ruleset_missing", {"ruleset_id": ruleset_id}

    if dry_run:
        # Mirror enricher's bucket discovery (it lives under card.equipment.*,
        # not at the root). Don't import _iter_pc_equipment to keep the dry-
        # run resilient to internal-helper renames.
        eq = sess.character.get("equipment") or {}
        equip_keys: list[str] = []
        if isinstance(eq, dict):
            equip_keys = [k for k, v in eq.items() if isinstance(v, list) and v]
        elif isinstance(eq, list) and eq:
            equip_keys = ["items"]
        return "would_run", {"buckets": equip_keys}

    result = await enrich_pc_equipment(db, sess, ruleset, force=force)
    return "ran", {
        "enriched": result.enriched_count,
        "skipped": result.skipped_count,
        "no_match": result.no_match_count,
        "by_bucket": result.by_bucket,
        "errors": result.errors,
        "skipped_reason": result.skipped_reason,
    }


async def main(
    *,
    dry_run: bool,
    force: bool,
    session_id: str | None,
) -> None:
    factory = get_session_factory()
    counts: dict[str, int] = {}
    total_enriched = 0

    async with factory() as db:
        query = select(GameSession).where(GameSession.archived == False)  # noqa: E712
        if session_id:
            query = query.where(GameSession.id == session_id)
        rows = (await db.execute(query)).scalars().all()
        if not rows:
            print("no sessions matched")
            return

        for sess in rows:
            status, info = await _process_one(
                db, sess, dry_run=dry_run, force=force,
            )
            counts[status] = counts.get(status, 0) + 1
            label = (sess.title or "")[:30]
            print(f"  [{sess.id[:8]}] {label!r:32} → {status} {info}")
            if status == "ran":
                total_enriched += int(info.get("enriched") or 0)

    print(
        f"\n=== done. sessions={sum(counts.values())} | "
        f"breakdown={counts} | total_fields_enriched={total_enriched} | "
        f"dry_run={dry_run} | force={force} ==="
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report which sessions would be processed without calling the LLM.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run even on sessions already stamped equipment_enriched_at.",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Process only this specific session id.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(
        dry_run=args.dry_run,
        force=args.force,
        session_id=args.session_id,
    ))
