"""Route-level diagnostics for the bond NPC enrichment endpoint.

Calls ``post_bond_npcs_enrich`` as a plain coroutine with stubbed
``user`` / ``db`` so the route's lazy-resolution invariant can be
verified without a live DB or LLM. The service-level diagnostics
(eligibility, conservative merge, voice card normalisation, etc.)
live in ``test_bond_npc_enrichment.py``; this file owns only the
route surface so the combined diagnostic stays under the 400-line
project ceiling per file.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def assert_true(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise AssertionError(f"{name} failed" + (f": {detail}" if detail else ""))
    print(f"OK: {name}")


def _make_stub_session(now):
    """Build a SessionDetail-compatible session-like object.

    SessionDetail's pydantic model requires non-None
    ``last_summarized_msg_count``, ``narrative_style``,
    ``difficulty_style``; a ``SimpleNamespace`` with concrete defaults
    is the smallest stub that survives ``_detail`` serialisation.
    """
    return SimpleNamespace(
        id="session_1",
        title="smoke",
        ruleset_id=None,
        archived=False,
        title_auto=True,
        setup_state=None,
        character={},
        module_state={},
        memory_state={"npcs": []},
        narrative_summary="",
        last_summarized_msg_count=0,
        dice_history=[],
        narrative_style="default",
        difficulty_style="default",
        last_active_at=now,
        created_at=now,
        updated_at=now,
        user_id="user_1",
    )


def case_route_no_eligible_skips_compiler_config() -> None:
    """Route returns 200 + zero counts without resolving the compiler
    config when there is no work to do.

    Monkey-patches ``_resolve_default_compiler_config`` to raise if it
    is ever invoked. This guards the rev1 acceptance fix: the older
    route 409-ed on a missing compiler model even when there were no
    eligible NPCs.
    """
    import routes.rulesets as rulesets_mod
    from routes import session_bond_npcs as route_mod
    from schemas.session_bond import BondNpcEnrichRequest

    now = datetime.now(timezone.utc)
    s = _make_stub_session(now)
    user = SimpleNamespace(id="user_1")

    class _FakeDb:
        async def get(self, cls, _id):
            from orm.models import GameSession
            if cls is GameSession:
                return s
            return None
        async def commit(self):
            raise AssertionError("db.commit must not run when no eligible NPCs")
        async def refresh(self, _):
            raise AssertionError("db.refresh must not run when no eligible NPCs")

    original = rulesets_mod._resolve_default_compiler_config

    async def _boom(_db):
        raise AssertionError(
            "compiler config resolver must NOT be called when eligible == 0"
        )

    rulesets_mod._resolve_default_compiler_config = _boom
    try:
        resp = asyncio.run(route_mod.post_bond_npcs_enrich(
            "session_1",
            BondNpcEnrichRequest(),
            user=user,
            db=_FakeDb(),
        ))
    finally:
        rulesets_mod._resolve_default_compiler_config = original

    assert_true("route returned 200 shape", hasattr(resp, "eligible"),
                repr(resp))
    assert_true("response eligible == 0", resp.eligible == 0, repr(resp))
    assert_true("response enriched == 0", resp.enriched == 0, repr(resp))
    assert_true("response skipped == 0", resp.skipped == 0, repr(resp))
    assert_true("response errors empty", resp.errors == [], repr(resp))


CASES = [
    case_route_no_eligible_skips_compiler_config,
]


def main() -> int:
    failures = 0
    for case in CASES:
        try:
            case()
        except AssertionError as exc:
            print(f"FAIL: {case.__name__}: {exc}")
            failures += 1
        except Exception as exc:
            print(f"ERROR: {case.__name__}: {type(exc).__name__}: {exc}")
            failures += 1
    if failures:
        print(f"\n{failures} case(s) failed.")
        return 1
    print("\nAll bond NPC enrichment route cases passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
