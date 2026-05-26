"""Pure / fake-generator diagnostics for bond NPC enrichment (service layer).

These checks never call the LLM or touch the database. They construct a
``SimpleNamespace`` session that mimics ``GameSession``'s read/write
shape, feed it through ``enrich_bond_npcs`` with a deterministic
``FakeGenerator``, and assert on the resulting ``memory_state.npcs``.
Route-level diagnostics for the same endpoint live in
``test_bond_npc_enrichment_route.py``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.trpg_npc.bond_enrichment import (  # noqa: E402
    enrich_bond_npcs,
    is_bond_npc_unfinished,
    select_eligible_bond_npcs,
)


def assert_true(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise AssertionError(f"{name} failed" + (f": {detail}" if detail else ""))
    print(f"OK: {name}")


# --- Test doubles ----------------------------------------------------------


def _bare_npc(key: str, *, from_bond: bool = True, **extra: Any) -> dict[str, Any]:
    base = {
        "key": key,
        "name": key.title(),
        "gender": "unknown",
        "from_bond": from_bond,
    }
    base.update(extra)
    return base


def _make_session(npcs: list[dict[str, Any]]) -> SimpleNamespace:
    return SimpleNamespace(
        id="session_1",
        character={"identity": {"name": "Vance"}},
        memory_state={"npcs": npcs},
    )


def _full_profile(key: str) -> dict[str, Any]:
    return {
        "gender": "female",
        "description": f"Profile for {key}: weathered detective bearing.",
        "personality": f"{key} is wary but loyal, slow to trust.",
        "relationship_dynamic": f"old partner of Vance; mutual debt unsettled",
        "voice_card": {
            "speaking_style": "Clipped sentences, low register.",
            "catchphrase": "We had a deal.",
            "mannerisms": "Taps the table when angry.",
            "sample_lines": ["You're late again.", "Don't lie to me, Vance."],
        },
    }


class FakeGenerator:
    """Returns a canned profile per NPC key and records every call."""

    def __init__(self, profiles: dict[str, dict[str, Any] | None]):
        self.profiles = profiles
        self.calls: list[str] = []

    async def __call__(
        self,
        npc: dict[str, Any],
        pc: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        key = str(npc.get("key") or "")
        self.calls.append(key)
        return self.profiles.get(key)


# --- Cases -----------------------------------------------------------------


def case_only_bond_npcs_are_eligible() -> None:
    s = _make_session([
        _bare_npc("ex_wife"),
        _bare_npc("waiter", from_bond=False),
        _bare_npc("captain"),
    ])
    gen = FakeGenerator({
        "ex_wife": _full_profile("ex_wife"),
        "waiter": _full_profile("waiter"),
        "captain": _full_profile("captain"),
    })
    result = asyncio.run(enrich_bond_npcs(s, None, profile_generator=gen))

    assert_true("only bond NPCs touched", set(gen.calls) == {"ex_wife", "captain"})
    assert_true("eligible count is two", result.eligible == 2, repr(result))
    assert_true("two enriched", result.enriched == 2, repr(result))
    waiter = next(n for n in s.memory_state["npcs"] if n["key"] == "waiter")
    assert_true("non-bond preserved", waiter.get("description") in (None, ""))


def case_already_enriched_skipped_without_force() -> None:
    finished = _bare_npc(
        "old_friend",
        gender="male",
        description="existing description, full sentence already here",
        personality="existing personality already filled in by intake",
        relationship_dynamic="long-time friend, knows the PC's secret",
        voice_card={"speaking_style": "warm"},
    )
    s = _make_session([finished, _bare_npc("ex_wife")])
    gen = FakeGenerator({"ex_wife": _full_profile("ex_wife")})

    result = asyncio.run(enrich_bond_npcs(s, None, profile_generator=gen))

    assert_true("finished NPC not in calls", "old_friend" not in gen.calls)
    assert_true("only unfinished NPC eligible", result.eligible == 1, repr(result))
    assert_true("predicate agrees finished is done", not is_bond_npc_unfinished(finished))


def case_conservative_merge_preserves_existing_fields() -> None:
    npc = _bare_npc(
        "ex_wife",
        gender="female",
        description="Hand-written description from the player; do not clobber.",
    )
    s = _make_session([npc])
    gen = FakeGenerator({"ex_wife": _full_profile("ex_wife")})

    asyncio.run(enrich_bond_npcs(s, None, profile_generator=gen))
    updated = s.memory_state["npcs"][0]

    kept = "Hand-written description from the player; do not clobber."
    assert_true("existing description preserved", updated["description"] == kept)
    assert_true("personality filled", bool(updated.get("personality")))
    assert_true("relationship_dynamic filled", bool(updated.get("relationship_dynamic")))
    assert_true("voice_card filled",
                isinstance(updated.get("voice_card"), dict) and bool(updated["voice_card"]))
    assert_true("gender preserved (was female)", updated["gender"] == "female")


def case_force_overwrites_existing_fields() -> None:
    npc = _bare_npc(
        "ex_wife",
        gender="female",
        description="stale description",
        personality="stale personality",
        relationship_dynamic="stale dynamic",
        voice_card={"speaking_style": "stale"},
    )
    s = _make_session([npc])
    gen = FakeGenerator({"ex_wife": _full_profile("ex_wife")})

    result = asyncio.run(
        enrich_bond_npcs(s, None, profile_generator=gen, force=True)
    )
    updated = s.memory_state["npcs"][0]

    assert_true("force counts NPC as eligible", result.eligible == 1, repr(result))
    assert_true("force enriched", result.enriched == 1, repr(result))
    assert_true("description refreshed", updated["description"] != "stale description",
                repr(updated))
    assert_true(
        "voice_card refreshed",
        updated["voice_card"].get("speaking_style") != "stale",
        repr(updated),
    )


def case_relationship_dynamic_mirrored_into_bond_context() -> None:
    npc = _bare_npc("ex_wife")
    s = _make_session([npc])
    gen = FakeGenerator({"ex_wife": _full_profile("ex_wife")})

    asyncio.run(enrich_bond_npcs(s, None, profile_generator=gen))
    updated = s.memory_state["npcs"][0]

    bond = updated.get("bond_context")
    assert_true("bond_context dict created", isinstance(bond, dict), repr(updated))
    assert_true(
        "connection equals relationship_dynamic",
        bond.get("connection") == updated["relationship_dynamic"],
        repr(updated),
    )


def case_bond_context_existing_connection_preserved_without_force() -> None:
    npc = _bare_npc(
        "ex_wife",
        bond_context={"connection": "we co-own the bar on 5th"},
    )
    s = _make_session([npc])
    gen = FakeGenerator({"ex_wife": _full_profile("ex_wife")})

    asyncio.run(enrich_bond_npcs(s, None, profile_generator=gen))
    updated = s.memory_state["npcs"][0]

    assert_true(
        "existing connection preserved",
        updated["bond_context"]["connection"] == "we co-own the bar on 5th",
        repr(updated),
    )


def case_no_tts_voice_fields_touched() -> None:
    npc = _bare_npc(
        "ex_wife",
        tts_voice="Cherry",
        active_tts_voice="Cherry",
        tts_voice_provider="minimax",
        tts_voice_locked=True,
        tts_voice_overrides={"minimax": "Cherry"},
    )
    s = _make_session([npc])
    gen = FakeGenerator({"ex_wife": _full_profile("ex_wife")})

    asyncio.run(enrich_bond_npcs(s, None, profile_generator=gen, force=True))
    updated = s.memory_state["npcs"][0]

    for field, expected in (
        ("tts_voice", "Cherry"),
        ("active_tts_voice", "Cherry"),
        ("tts_voice_provider", "minimax"),
        ("tts_voice_locked", True),
    ):
        assert_true(
            f"{field} untouched",
            updated.get(field) == expected,
            f"{field}={updated.get(field)!r}",
        )
    assert_true(
        "tts_voice_overrides untouched",
        updated.get("tts_voice_overrides") == {"minimax": "Cherry"},
        repr(updated.get("tts_voice_overrides")),
    )


def case_idempotent_after_first_run() -> None:
    s = _make_session([_bare_npc("ex_wife"), _bare_npc("captain")])
    profiles = {
        "ex_wife": _full_profile("ex_wife"),
        "captain": _full_profile("captain"),
    }
    gen1 = FakeGenerator(profiles)
    first = asyncio.run(enrich_bond_npcs(s, None, profile_generator=gen1))
    assert_true("first run enriches all", first.enriched == 2, repr(first))

    gen2 = FakeGenerator(profiles)
    second = asyncio.run(enrich_bond_npcs(s, None, profile_generator=gen2))
    assert_true("second run finds nothing eligible",
                second.eligible == 0, repr(second))
    assert_true("second run enriches zero", second.enriched == 0, repr(second))
    assert_true("second run made no generator calls",
                gen2.calls == [], f"calls={gen2.calls}")


def case_generator_failure_isolated_to_one_npc() -> None:
    s = _make_session([_bare_npc("ex_wife"), _bare_npc("captain")])
    gen = FakeGenerator({
        "ex_wife": None,
        "captain": _full_profile("captain"),
    })
    result = asyncio.run(enrich_bond_npcs(s, None, profile_generator=gen))

    assert_true("captain still enriched", result.enriched == 1, repr(result))
    assert_true("ex_wife skipped", "ex_wife" in result.skipped_keys, repr(result))


def case_blank_only_voice_card_is_treated_as_missing() -> None:
    """A voice_card with only blank strings/lists must count as missing
    (regression: earlier impl accepted any non-empty list)."""
    npc = _bare_npc(
        "ex_wife",
        description="filled",
        personality="filled",
        relationship_dynamic="filled",
        voice_card={
            "speaking_style": "",
            "catchphrase": "   ",
            "sample_lines": ["", "  "],
        },
    )
    s = _make_session([npc])
    gen = FakeGenerator({"ex_wife": _full_profile("ex_wife")})

    assert_true(
        "predicate flags blank-only voice_card as unfinished",
        is_bond_npc_unfinished(npc),
        repr(npc),
    )

    result = asyncio.run(enrich_bond_npcs(s, None, profile_generator=gen))
    assert_true("blank-only card NPC is eligible", result.eligible == 1,
                repr(result))
    assert_true("blank-only card NPC gets enriched", result.enriched == 1,
                repr(result))
    assert_true(
        "voice_card replaced with meaningful content",
        bool(s.memory_state["npcs"][0]["voice_card"].get("speaking_style", "").strip()),
        repr(s.memory_state["npcs"][0]),
    )


def case_no_eligible_makes_zero_generator_calls() -> None:
    """No work to do = zero generator calls. Route depends on this to
    early-return 200 without resolving the compiler config."""
    finished = _bare_npc(
        "old_friend",
        gender="male",
        description="filled in by intake",
        personality="settled, watchful, never bluffs",
        relationship_dynamic="long-time friend, knows the PC's secret",
        voice_card={"speaking_style": "warm"},
    )
    not_bond = _bare_npc("waiter", from_bond=False)
    s = _make_session([finished, not_bond])

    preflight = select_eligible_bond_npcs(s)
    assert_true("preflight returns empty list", preflight == [],
                f"preflight={preflight!r}")

    gen = FakeGenerator({})
    result = asyncio.run(enrich_bond_npcs(s, None, profile_generator=gen))

    assert_true("eligible is zero", result.eligible == 0, repr(result))
    assert_true("enriched is zero", result.enriched == 0, repr(result))
    assert_true("generator never called", gen.calls == [],
                f"calls={gen.calls!r}")


def case_limit_caps_processed_npcs() -> None:
    s = _make_session([
        _bare_npc("ex_wife"),
        _bare_npc("captain"),
        _bare_npc("uncle"),
    ])
    gen = FakeGenerator({
        "ex_wife": _full_profile("ex_wife"),
        "captain": _full_profile("captain"),
        "uncle": _full_profile("uncle"),
    })
    result = asyncio.run(
        enrich_bond_npcs(s, None, profile_generator=gen, limit=2)
    )

    assert_true("limit honored", result.enriched == 2, repr(result))
    assert_true("eligible still reports total", result.eligible == 3, repr(result))
    assert_true("the third NPC is skipped",
                "uncle" in result.skipped_keys, repr(result))


# --- Runner ----------------------------------------------------------------

CASES = [
    case_only_bond_npcs_are_eligible,
    case_already_enriched_skipped_without_force,
    case_conservative_merge_preserves_existing_fields,
    case_force_overwrites_existing_fields,
    case_relationship_dynamic_mirrored_into_bond_context,
    case_bond_context_existing_connection_preserved_without_force,
    case_no_tts_voice_fields_touched,
    case_idempotent_after_first_run,
    case_generator_failure_isolated_to_one_npc,
    case_blank_only_voice_card_is_treated_as_missing,
    case_no_eligible_makes_zero_generator_calls,
    case_limit_caps_processed_npcs,
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
    print("\nAll bond NPC enrichment cases passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
