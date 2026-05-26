"""Manual verification of NPC name masking through the IC context build path.

Exercises ``_build_ic_context_from_active`` end-to-end with a fake session that
mimics the leak observed in play: module chapter mentions three NPCs by true
name; only one is name_revealed=True. The others should be replaced by their
player_known_name in both the active_npcs JSON and the module chapter text.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.trpg_scene_runtime import _build_ic_context_from_active


def _make_session(npcs: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        id="verify-session",
        user_id="verify-user",
        memory_state={"npcs": npcs, "scenes": [], "plot_threads": [], "world_facts": {}},
        module_state={
            "scene": "scene_gas_station",
            "scene_name": "埃索加油站",
            "title": "血色公路",
            "active_module_content": {
                "unit_title": "Chapter 1: Arrival",
                "raw_content": (
                    "玩家抵达埃索加油站。加油站的老板拉斯正坐在阴影中。"
                    "司机内特·帕特森在房车下检修。"
                    "退伍军人史蒂夫·布朗坐在生锈的可乐机旁。"
                    "John Smith 是路边的另一个目击者。"
                ),
            },
        },
        characters={},
        narrative_summary="",
    )


def main() -> int:
    npcs = [
        {
            "key": "gas_station_owner",
            "name": "拉斯",
            "player_known_name": "加油站老板",
            "name_revealed": False,
            "role": "gas station owner",
        },
        {
            "key": "chatty_driver",
            "name": "内特·帕特森",
            "player_known_name": "喋喋不休的司机",
            "name_revealed": False,
            "role": "driver",
        },
        {
            "key": "silent_veteran",
            "name": "史蒂夫·布朗",
            "player_known_name": "沉默的退伍军人",
            "name_revealed": False,
            "role": "veteran",
        },
        {
            "key": "witness_john",
            "name": "John Smith",
            "player_known_name": "John Smith",
            "name_revealed": True,
            "role": "witness",
        },
    ]
    session = _make_session(npcs)

    ctx = _build_ic_context_from_active(
        session,
        active_raw=npcs,
        npc_extras="",
    )

    failures: list[str] = []

    chapter = ctx.module_chapter_text or ""
    for hidden in ("拉斯", "内特·帕特森", "史蒂夫·布朗"):
        if hidden in chapter:
            failures.append(f"module chapter still contains hidden true name: {hidden!r}")
    if "John Smith" not in chapter:
        failures.append("module chapter dropped revealed name 'John Smith'")
    for label in ("加油站老板", "喋喋不休的司机", "沉默的退伍军人"):
        if label not in chapter:
            failures.append(f"module chapter missing public label: {label!r}")

    by_key = {n.get("key"): n for n in ctx.active_npcs}
    if by_key.get("gas_station_owner", {}).get("name") != "加油站老板":
        failures.append(
            f"active_npcs[gas_station_owner].name = {by_key.get('gas_station_owner', {}).get('name')!r}, expected '加油站老板'"
        )
    if by_key.get("chatty_driver", {}).get("name") != "喋喋不休的司机":
        failures.append(
            f"active_npcs[chatty_driver].name = {by_key.get('chatty_driver', {}).get('name')!r}, expected '喋喋不休的司机'"
        )
    if by_key.get("witness_john", {}).get("name") != "John Smith":
        failures.append(
            f"active_npcs[witness_john].name = {by_key.get('witness_john', {}).get('name')!r}, expected 'John Smith'"
        )
    if by_key.get("witness_john", {}).get("name_revealed") is not True:
        failures.append("witness_john should remain name_revealed=True in projection")

    if failures:
        print("FAILED:")
        for f in failures:
            print(f"  - {f}")
        print()
        print("[masked module chapter]")
        print(chapter)
        print()
        print("[active_npcs]")
        for n in ctx.active_npcs:
            print(f"  {n.get('key')}: name={n.get('name')!r} display={n.get('display_name')!r} revealed={n.get('name_revealed')}")
        return 1

    print("OK — all assertions pass.")
    print()
    print("[masked module chapter]")
    print(chapter)
    print()
    print("[active_npcs]")
    for n in ctx.active_npcs:
        print(f"  {n.get('key')}: name={n.get('name')!r} display={n.get('display_name')!r} revealed={n.get('name_revealed')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
