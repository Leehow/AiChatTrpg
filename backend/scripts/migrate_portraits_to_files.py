"""One-shot DB sweep: convert legacy ``data:image/...;base64,...`` portrait
fields into on-disk files served at ``/api/media/files/...``.

Earlier portrait-generation paths inlined the full base64 payload into
``session.character.identity.portrait_url`` and
``session.memory_state.npcs[].portrait_url``. A single 340K-char data URI
is ~85K tokens — feeding even one of those through BP3 blows the LLM
context window.

This migration walks every GameSession row, finds any string that looks
like an image data URI (or an oversize raw base64 stashed in a
portrait/avatar/image-named field), saves the binary under
``backend/data/media/`` via :func:`services.media_storage.store_image_reference`,
and replaces the field value with the resulting ``/api/media/files/<hash>.<ext>``
URL.

Run:
    cd backend && source .venv/bin/activate
    python scripts/migrate_portraits_to_files.py
    python scripts/migrate_portraits_to_files.py --dry-run
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
from services.media_storage import store_image_reference


_DATA_URI_PREFIX = "data:image/"
_LARGE_TEXT_THRESHOLD = 4096
_PORTRAIT_FIELD_HINTS = ("portrait", "avatar", "image")


def _looks_like_inline_image(key: str, value: object) -> bool:
    if not isinstance(value, str):
        return False
    if value.startswith(_DATA_URI_PREFIX):
        return True
    name = (key or "").lower()
    if (
        len(value) > _LARGE_TEXT_THRESHOLD
        and any(token in name for token in _PORTRAIT_FIELD_HINTS)
    ):
        # Bare base64 stored under a portrait_*/avatar_*/image_* field.
        return True
    return False


async def _convert_node(
    node: object,
    *,
    path: str,
    dry_run: bool,
    counters: dict[str, int],
) -> object:
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if _looks_like_inline_image(key, value):
                counters["seen"] += 1
                if dry_run:
                    print(
                        f"  [dry-run] {path}.{key} would migrate "
                        f"({len(value)} chars)"
                    )
                    continue
                try:
                    payload = (
                        value
                        if value.startswith(_DATA_URI_PREFIX)
                        else f"data:image/png;base64,{value}"
                    )
                    new_url = await store_image_reference(payload)
                except Exception as exc:
                    counters["failed"] += 1
                    print(f"  ! failed {path}.{key}: {exc}")
                    continue
                if not new_url:
                    counters["failed"] += 1
                    continue
                node[key] = new_url
                counters["migrated"] += 1
                print(
                    f"  migrated {path}.{key}: "
                    f"{len(value)} chars -> {new_url}"
                )
                continue
            node[key] = await _convert_node(
                value,
                path=f"{path}.{key}",
                dry_run=dry_run,
                counters=counters,
            )
    elif isinstance(node, list):
        for index, item in enumerate(node):
            node[index] = await _convert_node(
                item,
                path=f"{path}[{index}]",
                dry_run=dry_run,
                counters=counters,
            )
    return node


async def main(*, dry_run: bool) -> None:
    factory = get_session_factory()
    counters = {"seen": 0, "migrated": 0, "failed": 0}
    sessions_touched = 0

    async with factory() as db:
        rows = (await db.execute(select(GameSession))).scalars().all()
        for sess in rows:
            local_before = counters["migrated"]
            local_seen = counters["seen"]

            if isinstance(sess.character, dict):
                await _convert_node(
                    sess.character,
                    path=f"[{sess.id}].character",
                    dry_run=dry_run,
                    counters=counters,
                )
                if counters["migrated"] > local_before:
                    flag_modified(sess, "character")

            mid_before = counters["migrated"]
            if isinstance(sess.memory_state, dict):
                await _convert_node(
                    sess.memory_state,
                    path=f"[{sess.id}].memory_state",
                    dry_run=dry_run,
                    counters=counters,
                )
                if counters["migrated"] > mid_before:
                    flag_modified(sess, "memory_state")

            setup_before = counters["migrated"]
            if isinstance(sess.setup_state, dict):
                await _convert_node(
                    sess.setup_state,
                    path=f"[{sess.id}].setup_state",
                    dry_run=dry_run,
                    counters=counters,
                )
                if counters["migrated"] > setup_before:
                    flag_modified(sess, "setup_state")

            if counters["migrated"] > local_before or counters["seen"] > local_seen:
                sessions_touched += 1

        if not dry_run:
            await db.commit()

    print(
        "\n=== done. "
        f"sessions={sessions_touched} | "
        f"seen={counters['seen']} | "
        f"migrated={counters['migrated']} | "
        f"failed={counters['failed']} | "
        f"dry_run={dry_run} ==="
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Walk the rows but skip writing files / committing DB changes.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(dry_run=args.dry_run))
