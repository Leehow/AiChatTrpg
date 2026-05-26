"""Integration test for the chatrpg framework adapter.

Uses duck-typed ORM rows to exercise the full chain:
    fake ORM session+ruleset → make_chatrpg_inputs → build_bp_guide → BpSnapshot

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_framework_chatrpg_adapter.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.trpg.framework.bp import build_bp_guide
from agents.trpg.framework.models import FeatureFlags, ModelConfig
from services.trpg_framework_adapter import (
    ChatrpgRulesetAdapter,
    make_chatrpg_inputs,
    make_chatrpg_services,
    to_module_data,
    to_ruleset_data,
    to_session_state,
)


def fake_session(**overrides) -> SimpleNamespace:
    base: dict[str, Any] = dict(
        id="sess-1",
        user_id="local",
        ruleset_id="rs-1",
        title="My Game",
        title_auto=True,
        archived=False,
        setup_state={
            "step": 2, "ruleset_id": "rs-1", "module_id": "mod-1",
            "module_title": "Bloody Highway", "completed": False,
            "character_chat": [
                {"role": "assistant", "content": "Welcome.", "created_at": "2026-04-27T10:00:00+00:00"},
                {"role": "user", "content": "I'm a journalist."},
            ],
        },
        character={},  # empty PC draft
        module_state={},
        memory_state={},
        narrative_summary="",
        last_summarized_msg_count=0,
        dice_history=[],
        narrative_style="second_person",
        difficulty_style="auto",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def fake_ruleset() -> SimpleNamespace:
    return SimpleNamespace(
        id="rs-1",
        owner_id="local",
        book_title="Call of Cthulhu",
        world_mode="worldview",
        short_name="coc",
        parsed_v6={
            "core_rules": "core rules markdown body" * 100,
            "companion": {
                "content": "investigation guide\n\ncombat guide",
            },
            "character_sheet": {
                "template_content": "template body",
                "guide_content": "chargen guide",
                "template_json": {"fields": [{"name": "STR"}, {"name": "DEX"}]},
            },
            # real v6 shape: array of family blobs with `family_id` + `json`
            "parameter_families": [
                {"family_id": "occupation",
                 "json": [{"name": "Reporter"}, {"name": "Doctor"}]},
                {"family_id": "weapon",
                 "json": [{"name": "Knife"}, {"name": "Shotgun"}, {"name": "Bare hands"}]},
            ],
            "rule_packages": [
                {"package_id": "creation", "content": "..."},
                {"package_id": "combat", "content": "..."},
            ],
            "discovery_manifest": {
                "detailed_rule_packages": [
                    {"package_id": "combat", "title": "Combat", "summary": "When fighting"},
                ],
            },
        },
    )


def fake_parsed_module() -> SimpleNamespace:
    return SimpleNamespace(
        id="mod-1",
        extracted_title="Bloody Highway",
        filename="bloody_highway.pdf",
        briefing_md="GM briefing: the road snakes through west texas.",
    )


def assert_eq(label, actual, expected):
    if actual != expected:
        print(f"FAIL: {label}")
        print(f"  expected: {expected!r}")
        print(f"  actual:   {actual!r}")
        sys.exit(1)
    print(f"OK: {label}")


def assert_true(label, cond, why=""):
    if not cond:
        print(f"FAIL: {label} {why}")
        sys.exit(1)
    print(f"OK: {label}")


# ---------------------------------------------------------------------------
# Cases


def case_to_session_state_basic():
    sess = fake_session()
    state = to_session_state(sess)
    assert_eq("id", state.id, "sess-1")
    assert_eq("user_id", state.user_id, "local")
    assert_eq("game_started", state.game_started, False)
    assert_eq("character_ready (no PC)", state.character_ready, False)
    assert_eq("characters wraps PC", state.characters,
              {"pc": {}, "npcs": []})
    assert_eq("chat_history len", len(state.chat_history), 2)
    assert_eq("first msg role normalized to gm",
              state.chat_history[0].role, "gm")


def case_to_session_state_with_pc_marks_ready():
    sess = fake_session(character={"name": "Alice", "occupation": "Journalist"})
    state = to_session_state(sess)
    assert_eq("character_ready (with PC)", state.character_ready, True)
    assert_eq(
        "characters.pc",
        state.characters["pc"],
        {"name": "Alice", "occupation": "Journalist"},
    )


def case_to_session_state_uses_explicit_chat_history():
    sess = fake_session()
    explicit = [{"role": "user", "content": "fresh"}]
    state = to_session_state(sess, chat_history=explicit)
    assert_eq("chat overridden", len(state.chat_history), 1)
    assert_eq("chat content", state.chat_history[0].content, "fresh")


def case_to_ruleset_data_carries_parsed_v6():
    rs = to_ruleset_data(fake_ruleset())
    assert_eq("book_title", rs.book_title, "Call of Cthulhu")
    assert_eq("world_mode", rs.world_mode, "worldview")
    assert_true(
        "parsed_v6 carried",
        isinstance(rs.parsed_v6.get("character_sheet"), dict),
    )
    # chatrpg has no distillates — these stay empty
    assert_eq("no resident_prompt", rs.resident_prompt, "")


def case_to_module_data_uses_briefing():
    mod = fake_parsed_module()
    md = to_module_data(mod)
    assert_true("module not None", md is not None)
    assert mod is not None
    assert md is not None
    assert_eq("title", md.title, "Bloody Highway")
    assert_true(
        "uses briefing text",
        "GM briefing" in md.markdown,
        why=md.markdown,
    )


def case_to_module_data_none_when_no_text():
    mod = SimpleNamespace(id="m1", extracted_title="x", filename="x.pdf", markdown="")
    assert_eq("None when empty", to_module_data(mod), None)


def case_chatrpg_adapter_get_stable_text():
    adapter = ChatrpgRulesetAdapter()
    sess = fake_session()
    state = to_session_state(sess)
    state.setup_state["_guide_language"] = "Chinese (simplified)"
    rs = to_ruleset_data(fake_ruleset())
    st = adapter.get_stable_text(rs, state, mode=None)
    assert_eq("no resident_prompt (chatrpg)", st.resident_prompt, "")
    # Both scene guides concatenated
    assert_true(
        "scene_guide has investigation",
        "investigation guide" in st.scene_guide,
    )
    assert_true(
        "scene_guide has combat",
        "combat guide" in st.scene_guide,
    )
    # Chargen pack = template + guide
    assert_true("chargen has template", "template body" in st.chargen_pack)
    assert_true("chargen has guide", "chargen guide" in st.chargen_pack)
    # Manifest index lives in `parameter_families` slot (we repurpose the
    # framework's slot to ship a directory rather than full bodies). The
    # GM uses this to decide which package_id / family_id to query via
    # `[SEARCH_RULES]`.
    mi = st.parameter_families
    assert_true("manifest index has SEARCH_RULES hint", "[SEARCH_RULES" in mi, mi[:80])
    assert_true("manifest lists rule_packages", "Rule Packages" in mi and "`combat`" in mi, mi[:200])
    assert_true("manifest lists parameter_families", "Parameter Families" in mi and "`weapon`" in mi, mi[:200])
    assert_true("manifest counts entries", "(2 entries)" in mi or "(3 entries)" in mi, mi[:200])
    # Manifest must NOT contain the actual content/json bodies (those are
    # paged in by [SEARCH_RULES] on demand).
    assert_true("manifest body kept out", len(mi) < 600, f"len={len(mi)}")
    # Core rules truncated
    assert_true(
        "core_rules present",
        "core rules markdown body" in st.core_rules_excerpt,
    )


def case_chatrpg_adapter_ic_prompt_is_immersive():
    adapter = ChatrpgRulesetAdapter()
    sess = fake_session(character={"name": "Alice", "occupation": "Journalist"})
    state = to_session_state(sess)
    rs = to_ruleset_data(fake_ruleset())
    st = adapter.get_stable_text(rs, state, mode="ic")
    assert_true("ic prompt present", "IMMERSION CONTRACT" in st.resident_prompt)
    assert_true(
        "ic prompt renders player questions in-world",
        "Treat the latest player message as in-character" in st.resident_prompt,
    )
    assert_true(
        "ic prompt avoids explicit roll requests",
        "do NOT ask the player to roll" in st.resident_prompt,
    )
    assert_true(
        "ic prompt teaches diegetic display tags",
        "[sign]...[/sign]" in st.resident_prompt
        and "[thought]...[/thought]" in st.resident_prompt,
    )
    assert_true(
        "ic prompt teaches backend-resolved checks",
        "[CHECK skill=" in st.resident_prompt
        and "Omit `roll`" in st.resident_prompt,
    )
    assert_true(
        "ic prompt teaches speaker and voice markers",
        "SPEAKER AND VOICE MARKERS" in st.resident_prompt
        and "[speak:happy|sad|angry|fearful|disgusted|surprised|calm]" in st.resident_prompt,
    )


def case_chatrpg_adapter_get_character_template():
    adapter = ChatrpgRulesetAdapter()
    sess = fake_session()
    state = to_session_state(sess)
    rs = to_ruleset_data(fake_ruleset())
    tpl = adapter.get_character_template(rs, state)
    assert_eq("fields count", len(tpl.fields), 2)
    assert_eq("fields[0]", tpl.fields[0], {"name": "STR"})


def case_chatrpg_adapter_guide_variable_text_ai_name():
    adapter = ChatrpgRulesetAdapter()
    sess = fake_session()
    state = to_session_state(sess)
    rs = to_ruleset_data(fake_ruleset())
    text = adapter.get_guide_variable_text(
        rs, state, message="你来定，帮我生成一个完整角色", recent_history=[],
    )
    assert_true("guide variable has culture nudge",
                "Suggested Cultural Origin" in text, why=text)
    assert_true("guide variable says dialogue-only",
                "not a final JSON-card rule" in text, why=text)
    assert_true("guide variable uses phonetic bracket display",
                "西格妮·哈尔沃丝达特[Signe Halvorsdatter]" in text, why=text)


def case_chatrpg_adapter_guide_variable_text_manual_name_suppresses():
    adapter = ChatrpgRulesetAdapter()
    sess = fake_session()
    state = to_session_state(sess)
    rs = to_ruleset_data(fake_ruleset())
    text = adapter.get_guide_variable_text(
        rs, state, message="名字是林秋，我想做记者。", recent_history=[],
    )
    assert_eq("manual name suppresses culture nudge", text, "")


def case_chatrpg_adapter_guide_variable_text_create_context():
    adapter = ChatrpgRulesetAdapter()
    sess = fake_session()
    state = to_session_state(sess)
    rs = to_ruleset_data(fake_ruleset())
    text = adapter.get_guide_variable_text(
        rs, state, message="[CREATE_CHARACTER]", recent_history=[],
    )
    assert_true("create context has uncommitted-name guidance",
                "Uncommitted Character Name" in text, why=text)


def case_end_to_end_build_bp_guide_for_chatrpg():
    sess = fake_session()
    rs = fake_ruleset()
    mod = fake_parsed_module()
    inputs = make_chatrpg_inputs(
        orm_session=sess,
        orm_ruleset=rs,
        parsed_module=mod,
        user_message="i'm a reporter",
        model=ModelConfig(provider="mock", model="m"),
        flags=FeatureFlags(enable_multimedia=False),
    )

    class StubLlm:
        async def stream_chat(self, messages, *, model):
            if False:  # pragma: no cover
                yield None
    services = make_chatrpg_services(llm=StubLlm())
    out = build_bp_guide(inputs, services)

    # Thinking lines reflect chatrpg's scene_guide concat + chargen + module
    bp1 = next(l for l in out.thinking_lines if l.startswith("[BP1 stable]"))
    assert_true(
        "BP1 mentions ruleset",
        "ruleset=Call of Cthulhu" in bp1,
        why=bp1,
    )
    assert_true(
        "BP1 mentions module",
        "module=Bloody Highway" in bp1,
        why=bp1,
    )
    # System prompt includes scene_guide + chargen + core rules
    sys_text = out.prompt_messages[0].content
    assert_true("system has scene guide section",
                "## World & GM Style Guide" in sys_text)
    assert_true("system has chargen pack",
                "## Character Template + Creation Workflow" in sys_text)
    assert_true("system has core rules excerpt",
                "## Core Rules Excerpt" in sys_text)
    # Module also wired in
    assert_true("system has module",
                "## Module Context: Bloody Highway" in sys_text)
    # Chat history replayed (1 GM + 1 user from fixture) + 1 fresh user msg = 4
    assert_eq("prompt msg count", len(out.prompt_messages), 4)


def main() -> None:
    case_to_session_state_basic()
    case_to_session_state_with_pc_marks_ready()
    case_to_session_state_uses_explicit_chat_history()
    case_to_ruleset_data_carries_parsed_v6()
    case_to_module_data_uses_briefing()
    case_to_module_data_none_when_no_text()
    case_chatrpg_adapter_get_stable_text()
    case_chatrpg_adapter_ic_prompt_is_immersive()
    case_chatrpg_adapter_get_character_template()
    case_chatrpg_adapter_guide_variable_text_ai_name()
    case_chatrpg_adapter_guide_variable_text_manual_name_suppresses()
    case_chatrpg_adapter_guide_variable_text_create_context()
    case_end_to_end_build_bp_guide_for_chatrpg()
    print("\nall chatrpg adapter tests passed")


if __name__ == "__main__":
    main()
