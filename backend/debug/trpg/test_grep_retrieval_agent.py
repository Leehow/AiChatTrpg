"""Unit smoke test for the ported grep retrieval agent.

Exercises the pure helpers (no LLM calls) so we can confirm the port is
faithful before wiring [SEARCH_RULES] into IC turns.

Run::

    cd backend && source .venv/bin/activate
    python debug/trpg/test_grep_retrieval_agent.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agents.grep_retrieval import (  # noqa: E402
    GrepRetrievalAgent,
    GrepRetrievalPromptSpec,
    build_source_map,
    build_system_prompt,
    build_user_prompt,
    format_grep_results,
    format_retrieval_context,
    grep_sources,
    infer_source_type_options,
    read_source,
)
from agents.grep_retrieval.runtime_openai import (  # noqa: E402
    apply_openai_request_defaults,
    extract_json_loose,
    make_openai_runtime,
)


def assert_true(label: str, cond: bool, why: str = "") -> None:
    if not cond:
        print(f"FAIL: {label} {why}")
        sys.exit(1)
    print(f"OK: {label}")


def assert_eq(label: str, actual, expected) -> None:
    if actual != expected:
        print(f"FAIL: {label}")
        print(f"  expected: {expected!r}")
        print(f"  actual:   {actual!r}")
        sys.exit(1)
    print(f"OK: {label}")


# Tiny ruleset-style fixture: two parameter family entries (one weapon
# in English, one occupation in English). The "user query" is in
# Chinese to confirm grep doesn't *expand* the query — that's the LLM's
# job at runtime — but it does match on the canonical English text once
# the LLM picks the right keyword. The cross-language behaviour is what
# the ReAct loop adds on top of these primitives.
_SOURCES = [
    {
        "id": "weapon.knife_small",
        "label": "weapon / Knife, Small",
        "source_type": "weapon",
        "content": (
            "Knife, Small\n"
            "Skill: Fighting (Brawl)\n"
            "Damage: 1D4 + DB\n"
            "Range: Touch\n"
            "Aliases: switchblade, folding knife, pocketknife, 折刀\n"
            "Impaling: yes"
        ),
    },
    {
        "id": "weapon.knife_medium",
        "label": "weapon / Knife, Medium",
        "source_type": "weapon",
        "content": (
            "Knife, Medium\n"
            "Skill: Fighting (Brawl)\n"
            "Damage: 1D6 + DB\n"
            "Aliases: hunting knife, kitchen knife"
        ),
    },
    {
        "id": "occupation.private_investigator",
        "label": "occupation / Private Investigator",
        "source_type": "occupation",
        "content": (
            "Private Investigator\n"
            "Credit Rating: 9-30\n"
            "Skills: Art/Craft (photography), Disguise, Law, "
            "Library Use, Psychology, Persuade, Stealth, "
            "and one of Firearms or Fighting (Brawl)."
        ),
    },
]


def case_grep_finds_alias() -> None:
    hits = grep_sources(_SOURCES, "switchblade")
    assert_eq("alias hit count", len(hits), 1)
    assert_eq("alias hit id", hits[0]["source_id"], "weapon.knife_small")
    assert_true("alias snippet contains target",
                "switchblade" in hits[0]["snippet"].lower(), hits[0]["snippet"])


def case_grep_chinese_alias() -> None:
    # The CN alias is embedded in the source body — grep finds it without
    # needing the LLM. (At runtime the LLM would issue this keyword.)
    hits = grep_sources(_SOURCES, "折刀")
    assert_eq("zh alias hit count", len(hits), 1)
    assert_eq("zh alias hit id", hits[0]["source_id"], "weapon.knife_small")


def case_grep_source_type_filter() -> None:
    all_hits = grep_sources(_SOURCES, "knife")
    weapon_hits = grep_sources(_SOURCES, "knife", source_type="weapon")
    occupation_hits = grep_sources(_SOURCES, "knife", source_type="occupation")
    assert_eq("knife matches both weapon entries", len(all_hits), 2)
    assert_eq("weapon filter still 2", len(weapon_hits), 2)
    assert_eq("occupation filter empty", len(occupation_hits), 0)


def case_grep_max_hits_caps() -> None:
    hits = grep_sources(_SOURCES, "knife", max_grep_hits=1)
    assert_eq("cap to 1 hit", len(hits), 1)


def case_grep_invalid_regex_falls_back_to_literal() -> None:
    # `(unclosed` is invalid regex — _compile_pattern should escape and
    # match literally (yielding zero hits, not a 500).
    hits = grep_sources(_SOURCES, "(unclosed")
    assert_eq("invalid regex → literal → 0 hits", len(hits), 0)


def case_format_grep_results_renders_each_hit() -> None:
    hits = grep_sources(_SOURCES, "knife")
    rendered = format_grep_results("knife", hits)
    assert_true("rendered has count", "Found 2 match" in rendered, rendered)
    assert_true("rendered has source_id", "[weapon.knife_small]" in rendered, rendered)
    assert_true("rendered has type+line", "type=weapon" in rendered, rendered)


def case_format_grep_no_matches() -> None:
    rendered = format_grep_results("dragon", [])
    assert_true("no-match prose", 'No matches for "dragon"' in rendered, rendered)


def case_read_source_truncates() -> None:
    smap = build_source_map(_SOURCES)
    raw = read_source(smap, "weapon.knife_small", max_source_chars=40)
    assert_true("truncation marker", "[truncated]" in raw, raw)
    assert_true("source label present", "Knife, Small" in raw, raw)


def case_read_source_unknown_id() -> None:
    smap = build_source_map(_SOURCES)
    out = read_source(smap, "doesnt.exist")
    assert_true("unknown id error", "Unknown source_id" in out, out)


def case_infer_source_type_options() -> None:
    opts = infer_source_type_options(_SOURCES)
    assert_true("any always present", "any" in opts, opts)
    assert_true("weapon present", "weapon" in opts, opts)
    assert_true("occupation present", "occupation" in opts, opts)


def case_system_prompt_renders_bilingual_block() -> None:
    spec = GrepRetrievalPromptSpec(
        agent_name="t",
        bilingual_search=True,
        extra_rules=("Prefer canonical names.",),
    )
    text = build_system_prompt(spec)
    assert_true("bilingual hint included",
                "Search bilingually" in text, text[:200])
    assert_true("extra rule included",
                "Prefer canonical names." in text, text[-200:])
    assert_true("output schema present", '"relevant": true' in text, text[:400])


def case_system_prompt_skips_bilingual_when_off() -> None:
    spec = GrepRetrievalPromptSpec(bilingual_search=False)
    text = build_system_prompt(spec)
    assert_true("bilingual hint absent",
                "Search bilingually" not in text, text[:200])


def case_user_prompt_includes_scope_hints() -> None:
    text = build_user_prompt(
        message="Where's the switchblade entry?",
        recent_context="player drew a folding knife",
        sources=_SOURCES,
        seed_terms="switchblade, folding knife, 折刀",
        scope_hints=("Source labels may be in English.",),
    )
    assert_true("user msg present", "switchblade entry" in text, text)
    assert_true("hint rendered", "Source labels may be in English." in text, text)
    assert_true("source count emitted", "Available sources: 3" in text, text)


def case_format_retrieval_context_filters_irrelevant() -> None:
    smap = build_source_map(_SOURCES)
    payload = {"relevant": False, "summary": "nothing", "sources": []}
    assert_eq("irrelevant → empty",
              format_retrieval_context(payload, smap), "")


def case_format_retrieval_context_renders_excerpts() -> None:
    smap = build_source_map(_SOURCES)
    payload = {
        "relevant": True,
        "summary": "found knife matches",
        "sources": [
            {
                "source_id": "weapon.knife_small",
                "label": "Knife, Small",
                "excerpt": "Damage: 1D4 + DB; Impaling.",
            },
        ],
    }
    rendered = format_retrieval_context(payload, smap, heading="## Notes")
    assert_true("heading present", rendered.startswith("## Notes"), rendered[:80])
    assert_true("summary line", "found knife matches" in rendered, rendered)
    assert_true("excerpt section", "Damage: 1D4" in rendered, rendered)


def case_extract_json_loose_handles_fences() -> None:
    fenced = '```json\n{"relevant": true, "sources": []}\n```'
    obj = extract_json_loose(fenced)
    assert_eq("fenced parses", obj, {"relevant": True, "sources": []})


def case_extract_json_loose_finds_block_in_prose() -> None:
    prose = 'Sure, here is the JSON: {"a": 1} — let me know.'
    obj = extract_json_loose(prose)
    assert_eq("prose-wrapped JSON parses", obj, {"a": 1})


def case_extract_json_loose_returns_none_on_garbage() -> None:
    assert_eq("garbage → None", extract_json_loose("nope"), None)
    assert_eq("empty → None", extract_json_loose(""), None)


def case_apply_request_defaults_strips_temp_for_gpt5() -> None:
    out = apply_openai_request_defaults({"model": "gpt-5.4", "temperature": 0.7})
    assert_true("temp removed for gpt-5", "temperature" not in out, out)


def case_apply_request_defaults_passes_through_for_gpt4() -> None:
    out = apply_openai_request_defaults({"model": "gpt-4o", "temperature": 0.4})
    assert_eq("temp kept for gpt-4o", out.get("temperature"), 0.4)


def case_grep_retrieval_agent_can_be_built() -> None:
    # Smoke-check the high-level wrapper is wired together. We don't
    # actually call .retrieve() because that hits an LLM.
    agent = GrepRetrievalAgent(
        runtime=make_openai_runtime(),
        prompt_spec=GrepRetrievalPromptSpec(
            agent_name="trpg in-play rules grep agent",
            bilingual_search=True,
        ),
    )
    formatted = agent.format_context(
        {"relevant": True, "summary": "ok", "sources": [
            {"source_id": "weapon.knife_small", "label": "Knife, Small",
             "excerpt": "1D4+DB"},
        ]},
        sources=_SOURCES,
    )
    assert_true("agent.format_context emits heading",
                "## Retrieval Notes" in formatted, formatted)


def main() -> None:
    case_grep_finds_alias()
    case_grep_chinese_alias()
    case_grep_source_type_filter()
    case_grep_max_hits_caps()
    case_grep_invalid_regex_falls_back_to_literal()
    case_format_grep_results_renders_each_hit()
    case_format_grep_no_matches()
    case_read_source_truncates()
    case_read_source_unknown_id()
    case_infer_source_type_options()
    case_system_prompt_renders_bilingual_block()
    case_system_prompt_skips_bilingual_when_off()
    case_user_prompt_includes_scope_hints()
    case_format_retrieval_context_filters_irrelevant()
    case_format_retrieval_context_renders_excerpts()
    case_extract_json_loose_handles_fences()
    case_extract_json_loose_finds_block_in_prose()
    case_extract_json_loose_returns_none_on_garbage()
    case_apply_request_defaults_strips_temp_for_gpt5()
    case_apply_request_defaults_passes_through_for_gpt4()
    case_grep_retrieval_agent_can_be_built()
    print("\nall grep retrieval agent unit tests passed")


if __name__ == "__main__":
    main()
