"""Runtime checks for chatrpg TRPG marker extensions.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_chatrpg_runtime_markers.py
"""

from __future__ import annotations

import asyncio
import random
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Patch flag_modified so SimpleNamespace fakes (no SQLAlchemy state) work.
# The real ORM session uses it to mark JSON columns dirty; in unit tests we
# only care about post-apply field values, not flush behavior.
import sqlalchemy.orm.attributes as _sa_attrs  # noqa: E402

_sa_attrs.flag_modified = lambda *a, **kw: None  # type: ignore[assignment]
import services.trpg_ic_markers as _ic_markers_mod  # noqa: E402

_ic_markers_mod.flag_modified = lambda *a, **kw: None  # type: ignore[assignment]
import services.trpg_npc.agent as _npc_agent_mod  # noqa: E402

_npc_agent_mod.flag_modified = lambda *a, **kw: None  # type: ignore[assignment]

from agents.trpg.check_actor_adapter import ActorLookupContext  # noqa: E402
from agents.trpg.check_engine_registry import registered_engine_names  # noqa: E402
from agents.trpg.check_ir.compile_direct import _normalize_ir_for_runtime, _samples_match  # noqa: E402
from agents.trpg.check_ir.core import DiceIRValidationError, run_resolution_ir  # noqa: E402
from agents.trpg.check_ir.packs.coc7 import coc7_sanity_roll_ir  # noqa: E402
from agents.trpg.check_inline import replace_checks_in_text  # noqa: E402
from agents.trpg.check_resolver import CheckArgs, CheckResult  # noqa: E402
from agents.trpg.check_runtime import (  # noqa: E402
    CheckExecution,
    RollTrace,
    execute_check_runtime,
    render_pending_check,
)
from agents.trpg.check_spec_registry import build_runtime_check_spec  # noqa: E402
from agents.trpg.contest_inline import replace_contests_in_text  # noqa: E402
from agents.trpg.dice_roller import DiceRoller  # noqa: E402
from agents.trpg.speaker_resolver import (  # noqa: E402
    annotate_speak_tags,
    is_probable_named_speaker,
    is_trackable_visible_speaker,
    resolve_speaker_label,
)
from services.trpg_scene_runtime import ensure_spoken_npcs_with_scene  # noqa: E402
from services.trpg_pending_checks import (  # noqa: E402
    PendingCheck,
    find_pending_checks,
    resolve_pending_execution,
    summarize_for_dice_message,
)
from services.trpg_check_logs import record_check_execution  # noqa: E402
from services.trpg_rule_consequences import recent_rule_consequences_prompt_block  # noqa: E402
from services.trpg_ic_markers import (  # noqa: E402
    apply_chatrpg_markers,
    parse_chatrpg_markers,
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


class FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)


def case_check_marker_auto_rolls() -> None:
    random.seed(7)
    # `auto=true` → resolved inline (combat / Initiative path).
    rendered = replace_checks_in_text(
        '[CHECK skill="侦查" value=75 difficulty=hard reason="查看门缝" auto=true]',
        {"engine": "coc_7e_d100"},
    )
    assert_true("check marker hidden", "[CHECK" not in rendered, rendered)
    assert_true("check renders dice block", "[dice]" in rendered, rendered)
    assert_true("check keeps skill label", "侦查" in rendered, rendered)


def case_check_marker_default_pending() -> None:
    # No `auto` attr → emits [pending_check] placeholder for the frontend
    # button. The placeholder must carry id + engine + skill + value +
    # difficulty + reason so the resolve endpoint can rebuild CheckArgs
    # without re-parsing the GM message.
    rendered = replace_checks_in_text(
        '[CHECK skill="侦查" value=75 difficulty=hard reason="查看门缝"]',
        {"engine": "coc_7e_d100"},
    )
    assert_true("no [dice] yet", "[dice]" not in rendered, rendered)
    assert_true("emits pending_check", "[pending_check " in rendered, rendered)
    assert_true("carries engine", "engine=coc_7e_d100" in rendered, rendered)
    assert_true("carries skill", "skill=侦查" in rendered, rendered)
    assert_true("carries value", "value=75" in rendered, rendered)
    assert_true("carries difficulty", "difficulty=hard" in rendered, rendered)


def case_mandatory_sanity_check_auto_rolls() -> None:
    rendered = replace_checks_in_text(
        '[CHECK actor="pc" skill="SAN" value=45 reason="目睹无法解释的尸体"]',
        {"engine": "coc_7e_d100"},
    )
    assert_true("mandatory san check does not pend", "[pending_check " not in rendered, rendered)
    assert_true("mandatory san check renders dice", "[dice]" in rendered, rendered)
    assert_true("mandatory san check keeps label", "理智" in rendered, rendered)

    optional = replace_checks_in_text(
        '[CHECK actor="pc" skill="SAN" value=45 optional=true '
        'success_san_loss=0 failure_san_loss="1D6" reason="如果选择阅读黑皮书"]',
        {"engine": "coc_7e_d100"},
    )
    assert_true("optional san check can still pend", "[pending_check " in optional, optional)
    assert_true("optional san check no dice yet", "[dice]" not in optional, optional)
    assert_true("optional san check keeps loss terms", "failure_san_loss=1D6" in optional, optional)
    pending = find_pending_checks(optional)[0]
    assert_eq("optional san loss parsed", pending.extras["failure_san_loss"], "1D6")
    assert_eq("optional san success parsed", pending.extras["success_san_loss"], 0)


def case_pending_extras_roundtrip_generic_values() -> None:
    rendered = replace_checks_in_text(
        '[CHECK skill="Stealth" value=5 optional=true advantage=true '
        'wound_modifier=-2 custom_note="需要 保留" reason="dnd style pending"]',
        {"engine": "d20_vs_dc"},
    )
    assert_true("generic extras pending", "[pending_check " in rendered, rendered)
    pending = find_pending_checks(rendered)[0]
    assert_true("generic bool extra", pending.extras["advantage"] is True, repr(pending.extras))
    assert_eq("generic int extra", pending.extras["wound_modifier"], -2)
    assert_eq("generic simple string extra", pending.extras["custom_note"], "需要 保留")


def case_pending_extras_roundtrip_json64() -> None:
    pending_text = render_pending_check(
        CheckArgs(
            skill="Custom",
            value=1,
            extras={
                "params": {"a": 1, "b": [2, 3]},
                "long_text": 'quote " and [bracket] survive',
                "_internal": "secret",
                "engine": "do_not_override",
            },
        ),
        {"engine": "generic_resolution_v1"},
    )
    pending = find_pending_checks(pending_text)[0]
    assert_eq("json64 dict extra", pending.extras["params"], {"a": 1, "b": [2, 3]})
    assert_eq("str64 string extra", pending.extras["long_text"], 'quote " and [bracket] survive')
    assert_true("private extra skipped", "_internal" not in pending.extras, repr(pending.extras))
    assert_true("reserved extra skipped", "engine" not in pending.extras, repr(pending.extras))


def _minimal_sanity_runtime_spec() -> dict:
    sanity_ir = {
        "schema_version": "resolution_ir_v1_1",
        "id": "coc7.sanity_roll",
        "input_contract": {
            "required": ["roll", "value"],
            "optional": {
                "success_san_loss": {"type": "number|string", "default": 0},
                "failure_san_loss": {"type": "number|string", "default": 0},
                "failure_san_loss_roll": {"type": "number[]|null", "default": None},
            },
        },
        "steps": [
            {"id": "roll_main", "op": "read_rolls", "group": "main", "expr": "1d100"},
            {"id": "dice_sum", "op": "sum_values", "from": "main", "write": "natural_roll"},
            {"id": "skill", "op": "formula", "expr": "args.value", "write": "skill"},
            {
                "id": "success_flag",
                "op": "conditional_value",
                "cases": [{"when": {"var": "natural_roll", "lte": "skill"}, "value": 1}],
                "default": 0,
                "write": "success_flag",
            },
            {
                "id": "failure_san_loss_value",
                "op": "resolve_dice_value",
                "source": "args.failure_san_loss",
                "roll_source_arg": "failure_san_loss_roll",
                "write": "failure_san_loss_value",
            },
            {
                "id": "san_loss",
                "op": "conditional_value",
                "cases": [{"when": {"var": "success_flag", "eq": 1}, "value": "args.success_san_loss"}],
                "default": "vars.failure_san_loss_value",
                "write": "san_loss",
            },
        ],
        "result_axes": [
            {
                "id": "tier",
                "kind": "tier",
                "outcomes": [
                    {"tier": "success", "when": {"var": "success_flag", "eq": 1}, "passed": True},
                    {"tier": "failure", "default": True, "passed": False},
                ],
            },
            {"id": "san_loss", "kind": "resource_delta", "from": "san_loss"},
        ],
        "primary_axis": "tier",
        "labels": {"success": "成功", "failure": "失败"},
    }
    return {
        "engine": "coc_7e_d100",
        "_runtime_default_procedure_id": "coc.skill_check",
        "_runtime_check_specs": {
            "coc.skill_check": {"engine": "coc_7e_d100"},
            "coc7.sanity_roll": {"engine": "generic_resolution_v1", "ir": sanity_ir},
        },
    }


def case_sanity_check_infers_procedure_and_renders_loss() -> None:
    execution = execute_check_runtime(
        CheckArgs(
            skill="SAN",
            value=45,
            roll=97,
            reason="目睹无法解释的尸体",
            extras={"failure_san_loss": 3, "success_san_loss": 0},
        ),
        _minimal_sanity_runtime_spec(),
        auto_roll=False,
        source="debug_sanity",
    )
    trace = execution.trace.to_metadata()
    assert_eq("sanity inferred procedure", trace["procedure_id"], "coc7.sanity_roll")
    assert_eq("sanity side effect", execution.result.side_effects["san_loss"], 3)
    assert_true("sanity rendered loss", "SAN 损失: 3" in execution.rendered, execution.rendered)


def case_coc_sanity_pack_runs_as_generic_ir() -> None:
    ir = coc7_sanity_roll_ir()
    assert_eq("sanity pack id", ir["id"], "coc7.sanity_roll")
    assert_eq("sanity pack family", ir["primary_family"], "percentile_roll_under")
    assert_true("sanity pack aliases", "SAN" in ir["routing"]["aliases"], repr(ir.get("routing")))
    assert_true("sanity pack tags", "sanity" in ir["routing"]["semantic_tags"], repr(ir.get("routing")))
    assert_true(
        "sanity pack generic resource step",
        any(step.get("op") == "resolve_dice_value" for step in ir["steps"]),
        repr(ir["steps"]),
    )
    out = run_resolution_ir(
        ir,
        {
            "roll": 97,
            "value": 45,
            "success_san_loss": 0,
            "failure_san_loss": 3,
        },
    )
    assert_eq("sanity pack tier", out["primary_tier"], "fumble")
    assert_eq("sanity pack side effect", out["side_effects"]["san_loss"], 3)


def case_sanity_check_rolls_loss_dice_with_client_roll() -> None:
    execution = execute_check_runtime(
        CheckArgs(
            skill="理智",
            value=45,
            roll=97,
            reason="目睹无法解释的尸体",
            extras={
                "failure_san_loss": "1D4",
                "success_san_loss": 0,
                "roll_seed": "san-loss-seed",
            },
        ),
        _minimal_sanity_runtime_spec(),
        auto_roll=False,
        source="debug_sanity_client_roll",
    )
    trace = execution.trace.to_metadata()
    loss = execution.result.side_effects["san_loss"]
    assert_true("sanity loss rolled numeric", isinstance(loss, int), repr(execution.result.side_effects))
    assert_true("sanity loss trace source", "failure_san_loss_roll" in trace["roll_sources"], repr(trace))
    assert_true("sanity loss expression", trace["roll_expressions"]["failure_san_loss_roll"] == "1D4", repr(trace))
    assert_true("sanity loss rendered numeric", f"SAN 损失: {loss}" in execution.rendered, execution.rendered)


def case_sanity_check_falls_back_when_ruleset_lacks_sanity_proc() -> None:
    execution = execute_check_runtime(
        CheckArgs(
            skill="理智",
            value=45,
            roll=97,
            reason="当前规则集未编译 sanity_roll",
            extras={"failure_san_loss": 2, "success_san_loss": 0},
        ),
        {
            "engine": "generic_resolution_v1",
            "_runtime_ruleset_name": "Call of Cthulhu",
            "_runtime_default_procedure_id": "percentile_skill_or_characteristic_roll",
            "_runtime_check_specs": {
                "coc.skill_check": {"engine": "coc_7e_d100"},
                "temporary_insanity_int_roll": {"engine": "coc_7e_d100"},
            },
        },
        auto_roll=False,
        source="debug_sanity_fallback",
    )
    trace = execution.trace.to_metadata()
    assert_eq("sanity fallback procedure", trace["procedure_id"], "coc7.sanity_roll")
    assert_eq("sanity fallback requested", trace["requested_procedure_id"], "coc7.sanity_roll")
    assert_eq("sanity fallback loss", execution.result.side_effects["san_loss"], 2)
    assert_true("sanity fallback not insanity int roll", "temporary_insanity" not in trace["procedure_id"], repr(trace))


def case_compiled_catalog_alias_routes_generic_procedure() -> None:
    execution = execute_check_runtime(
        CheckArgs(
            skill="Quality",
            value=1,
            pool="6d4",
            reason="Triangle style quality check",
            extras={"roll_seed": "catalog-route-seed"},
        ),
        {
            "engine": "coc_7e_d100",
            "_runtime_check_specs": {
                "triangle.standard_quality": {
                    "engine": "pool_count_n",
                    "per_die_target": 3,
                },
            },
            "_runtime_procedure_index": {
                "triangle.standard_quality": {
                    "aliases": ["Quality"],
                    "semantic_tags": ["quality_check"],
                },
            },
        },
        auto_roll=True,
        source="debug_catalog_route",
    )
    trace = execution.trace.to_metadata()
    assert_eq("catalog route procedure", trace["procedure_id"], "triangle.standard_quality")
    assert_eq("catalog route engine", trace["engine"], "pool_count_n")


def case_check_marker_pending_keeps_procedure_id() -> None:
    rendered = replace_checks_in_text(
        '[CHECK procedure_id="triangle.standard_quality" skill="Quality" '
        'value=1 pool="6d4" reason="time loop roll"]',
        {
            "engine": "coc_7e_d100",
            "_runtime_check_specs": {
                "triangle.standard_quality": {"engine": "pool_count_n"},
            },
        },
    )
    assert_true("procedure route picks spec engine", "engine=pool_count_n" in rendered, rendered)
    assert_true("pending carries roll seed", "roll_seed=pending:" in rendered, rendered)
    assert_true(
        "procedure id preserved",
        "procedure_id=triangle.standard_quality" in rendered,
        rendered,
    )


def case_check_runtime_trace_for_procedure() -> None:
    random.seed(13)
    execution = execute_check_runtime(
        CheckArgs(
            skill="Quality",
            value=1,
            pool="6d4",
            reason="time loop roll",
        ),
        {
            "engine": "coc_7e_d100",
            "_runtime_check_specs": {
                "triangle.standard_quality": {
                    "engine": "pool_count_n",
                    "per_die_target": 3,
                },
            },
        },
        procedure_id="triangle.standard_quality",
        auto_roll=True,
        source="debug_runtime",
    )
    trace = execution.trace.to_metadata()
    assert_true("runtime trace renders dice", "[dice]" in execution.rendered, execution.rendered)
    assert_eq("runtime trace engine", trace["engine"], "pool_count_n")
    assert_eq("runtime trace procedure", trace["procedure_id"], "triangle.standard_quality")
    assert_eq("runtime trace expression", trace["roll_expression"], "6d4")
    assert_true("runtime trace roll total", isinstance(trace["roll_total"], int), repr(trace))
    assert_true("runtime trace has roll details", "roll" in trace["roll_trace"], repr(trace))


def case_pending_resolve_writes_trace_metadata() -> None:
    random.seed(17)
    pending = PendingCheck(
        id="abc123",
        engine="pool_count_n",
        procedure_id="triangle.standard_quality",
        skill="Quality",
        value=1,
        difficulty="regular",
        target=None,
        pool="6d4",
        bonus=0,
        penalty=0,
        reason="time loop roll",
        raw_match="[pending_check id=abc123]",
    )
    execution = resolve_pending_execution(
        pending,
        {
            "engine": "coc_7e_d100",
            "_runtime_check_specs": {
                "triangle.standard_quality": {
                    "engine": "pool_count_n",
                    "per_die_target": 3,
                },
            },
        },
    )
    meta = summarize_for_dice_message(pending, execution)
    trace = meta["trace"]
    assert_eq("pending trace source", trace["source"], "pending_check_resolve")
    assert_eq("pending trace engine", trace["engine"], "pool_count_n")
    assert_eq("pending trace procedure", trace["procedure_id"], "triangle.standard_quality")
    assert_eq("pending metadata engine", meta["engine"], "pool_count_n")
    assert_true("pending metadata result numeric", isinstance(meta["result"], int), repr(meta))
    assert_eq("pending metadata seed", meta["seed"], "pending:abc123")
    assert_true("pending metadata roll trace", "roll" in meta["roll_trace"], repr(meta))
    assert_eq("pending metadata request", meta["request"]["procedure_id"], "triangle.standard_quality")
    assert_true("pending metadata result detail", "tier" in meta["result_detail"], repr(meta))


def case_pending_resolve_uses_client_roll() -> None:
    pending = PendingCheck(
        id="clientroll",
        engine="coc_7e_d100",
        procedure_id="",
        skill="聆听",
        value=70,
        difficulty="hard",
        target=None,
        pool="",
        bonus=0,
        penalty=0,
        reason="listen through the door",
        raw_match="[pending_check id=clientroll]",
    )
    execution = resolve_pending_execution(
        pending,
        {"engine": "coc_7e_d100"},
        auto_roll=82,
    )
    trace = execution.trace.to_metadata()
    meta = summarize_for_dice_message(pending, execution)
    assert_eq("pending client roll total", trace["roll_total"], 82)
    assert_eq("pending client roll metadata", meta["result"], 82)
    assert_eq("pending client roll expression", trace["roll_expression"], "1d100")
    assert_eq("pending client roll not auto", trace["auto_rolled"], False)
    assert_eq("pending client roll tier", meta["result_detail"]["tier"], "failure")


def case_dice_roller_seeded_trace() -> None:
    first = DiceRoller(seed="kh-seed").roll("2d20kh1+5")
    second = DiceRoller(seed="kh-seed").roll("2d20kh1+5")
    assert_eq("dice roller seeded total", first.total, second.total)
    assert_eq("dice roller normalized expr", first.expression, "2d20kh1+5")
    assert_eq("dice roller modifier", first.modifier, 5)
    assert_true(
        "dice roller drops one die",
        sum(1 for roll in first.rolls if not roll.get("kept")) == 1,
        repr(first.to_metadata()),
    )
    pool = DiceRoller(seed="pool-seed").roll("6d4")
    assert_eq("dice roller pool count", len(pool.rolls), 6)
    assert_true("dice roller d100 range", 1 <= DiceRoller(seed="d100-seed").roll("d100").total <= 100)


def case_coc_bonus_penalty_trace() -> None:
    first = execute_check_runtime(
        CheckArgs(
            skill="侦查",
            value=75,
            bonus=1,
            extras={"roll_seed": "coc-bonus-seed"},
        ),
        {"engine": "coc_7e_d100"},
        auto_roll=True,
        source="debug_coc_bonus",
    )
    second = execute_check_runtime(
        CheckArgs(
            skill="侦查",
            value=75,
            bonus=1,
            extras={"roll_seed": "coc-bonus-seed"},
        ),
        {"engine": "coc_7e_d100"},
        auto_roll=True,
        source="debug_coc_bonus",
    )
    trace = first.trace.to_metadata()
    assert_eq("coc bonus seeded repeatable", trace["roll"], second.trace.to_metadata()["roll"])
    assert_eq("coc bonus seed recorded", trace["roll_seed"], "coc-bonus-seed")
    assert_eq("coc bonus trace method", trace["roll_trace"]["roll"]["method"], "coc_bonus_penalty")
    assert_true(
        "coc bonus no stale warning",
        not any("not resimulated" in warning for warning in trace["warnings"]),
        repr(trace),
    )


def case_actor_adapter_pc_pending_value() -> None:
    ctx = ActorLookupContext(
        pc={
            "skills": [
                {"name": "侦查", "value": 75},
            ],
        },
    )
    rendered = replace_checks_in_text(
        '[CHECK actor="pc" skill="侦查" difficulty=hard reason="查看门缝"]',
        {"engine": "coc_7e_d100"},
        actor_context=ctx,
    )
    assert_true("actor adapter emits pending", "[pending_check " in rendered, rendered)
    assert_true("actor adapter fills pc value", "value=75" in rendered, rendered)
    assert_true("actor adapter keeps actor", "actor=pc" in rendered, rendered)


def case_actor_adapter_npc_resolve_value() -> None:
    pending = PendingCheck(
        id="npc123",
        engine="coc_7e_d100",
        procedure_id="",
        skill="潜行",
        value=None,
        difficulty="regular",
        target=None,
        pool="",
        bonus=0,
        penalty=0,
        reason="guard slips away",
        raw_match="[pending_check id=npc123]",
        actor="guard_chen",
    )
    execution = resolve_pending_execution(
        pending,
        {"engine": "coc_7e_d100"},
        actor_context=ActorLookupContext(
            npcs=[
                {
                    "key": "guard_chen",
                    "name": "守卫陈",
                    "params": {"潜行": {"value": 42}},
                }
            ],
        ),
    )
    trace = execution.trace.to_metadata()
    assert_eq("actor adapter npc value", execution.args.value, 42)
    assert_eq(
        "actor adapter trace source",
        trace["result_axes"]["_actor_lookup"]["source"],
        "npc:guard_chen",
    )


def case_actor_adapter_missing_value_warns() -> None:
    pending = PendingCheck(
        id="miss123",
        engine="coc_7e_d100",
        procedure_id="",
        skill="侦查",
        value=None,
        difficulty="regular",
        target=None,
        pool="",
        bonus=0,
        penalty=0,
        reason="unknown actor",
        raw_match="[pending_check id=miss123]",
        actor="ghost",
    )
    execution = resolve_pending_execution(
        pending,
        {"engine": "coc_7e_d100"},
        actor_context=ActorLookupContext(pc={}, npcs=[]),
    )
    trace = execution.trace.to_metadata()
    assert_true(
        "actor adapter missing warns",
        any("actor lookup failed" in warning for warning in trace["warnings"]),
        repr(trace),
    )


def case_check_engine_registry_has_builtins() -> None:
    names = set(registered_engine_names())
    for engine in {
        "coc_7e_d100",
        "brp_d100",
        "d20_vs_dc",
        "pbta_2d6",
        "pool_count_n",
        "generic_resolution_v1",
        "custom_llm",
    }:
        assert_true(f"engine registered {engine}", engine in names, repr(names))


def case_resolution_ir_v1_is_rejected() -> None:
    try:
        run_resolution_ir({"schema_version": "resolution_ir_v1"}, {})
    except DiceIRValidationError as exc:
        assert_true("resolution v1 rejected", "resolution_ir_v1" in str(exc), str(exc))
        return
    assert_true("resolution v1 rejected", False, "resolution_ir_v1 unexpectedly accepted")


def case_generic_ir_auto_rolls_non_roll_sources() -> None:
    ir = {
        "schema_version": "resolution_ir_v1_1",
        "id": "test.beat_count",
        "input_contract": {
            "required": ["action_roll", "challenge_roll", "value"],
            "optional": {},
        },
        "steps": [
            {
                "id": "action",
                "op": "read_rolls",
                "group": "action",
                "expr": "1d6",
                "source_arg": "action_roll",
            },
            {"id": "action_die", "op": "sum_values", "from": "action", "write": "action_die"},
            {"id": "score", "op": "formula", "expr": "action_die + args.value", "write": "score"},
            {
                "id": "challenge",
                "op": "read_rolls",
                "group": "challenge",
                "expr": "2d10",
                "source_arg": "challenge_roll",
            },
            {
                "id": "beats",
                "op": "beat_count",
                "score": "vars.score",
                "challenges": "challenge",
                "write": "beats",
            },
        ],
        "result_axes": [
            {
                "id": "task",
                "kind": "tier",
                "outcomes": [
                    {"tier": "strong_hit", "when": {"var": "beats", "eq": 2}, "passed": True},
                    {"tier": "weak_hit", "when": {"var": "beats", "eq": 1}, "passed": True},
                    {"tier": "miss", "default": True, "passed": False},
                ],
            }
        ],
        "primary_axis": "task",
        "labels": {"strong_hit": "强命中", "weak_hit": "弱命中", "miss": "失手"},
    }
    args = CheckArgs(
        skill="Move",
        value=2,
        extras={"roll_seed": "beat-count-seed"},
    )
    first = execute_check_runtime(
        args,
        {"engine": "generic_resolution_v1", "ir": ir},
        auto_roll=True,
        source="debug_generic_ir",
    )
    second = execute_check_runtime(
        args,
        {"engine": "generic_resolution_v1", "ir": ir},
        auto_roll=True,
        source="debug_generic_ir",
    )
    trace = first.trace.to_metadata()
    assert_eq("generic non-roll action expr", trace["roll_expressions"]["action_roll"], "1d6")
    assert_eq("generic non-roll challenge expr", trace["roll_expressions"]["challenge_roll"], "2d10")
    assert_true("generic non-roll action source", "action_roll" in trace["roll_sources"], repr(trace))
    assert_true("generic non-roll challenge source", "challenge_roll" in trace["roll_sources"], repr(trace))
    assert_eq("generic seeded repeatable", trace["roll_sources"], second.trace.to_metadata()["roll_sources"])
    assert_true(
        "generic ir trace embedded",
        "_ir" in first.trace.to_metadata()["result_axes"],
        repr(first.trace.to_metadata()),
    )


def case_generic_ir_auto_rolls_variable_count() -> None:
    ir = {
        "schema_version": "resolution_ir_v1_1",
        "id": "test.variable_pool",
        "input_contract": {"required": ["roll", "value"], "optional": {}},
        "steps": [
            {
                "id": "pool",
                "op": "read_rolls",
                "group": "pool",
                "expr": "Nd6",
                "count_from": "args.value",
            },
            {
                "id": "successes",
                "op": "tally",
                "from": "pool",
                "where": {"gte": 5},
                "write": "successes",
            },
        ],
        "result_axes": [
            {
                "id": "task",
                "kind": "pass_fail",
                "pass_when": {"var": "successes", "gte": 1},
                "success_tier": "success",
                "failure_tier": "failure",
            }
        ],
        "primary_axis": "task",
        "labels": {"success": "成功", "failure": "失败"},
    }
    execution = execute_check_runtime(
        CheckArgs(
            skill="Pool",
            value=3,
            extras={"roll_seed": "variable-pool-seed"},
        ),
        {"engine": "generic_resolution_v1", "ir": ir},
        auto_roll=True,
        source="debug_generic_ir",
    )
    trace = execution.trace.to_metadata()
    assert_eq("generic variable expr display", trace["roll_expression"], "3d6")
    assert_eq("generic variable roll count", len(str(trace["roll"]).split(",")), 3)
    assert_true("generic variable rendered", "[dice]" in execution.rendered, execution.rendered)


def case_generic_ir_coc_skill_uses_numeric_value_alias() -> None:
    ir = {
        "schema_version": "resolution_ir_v1_1",
        "id": "test.coc_skill_alias",
        "input_contract": {
            "required": ["roll", "skill_or_characteristic"],
            "optional": {"target_value": {"type": "number", "default": 0}},
        },
        "steps": [
            {"id": "roll", "op": "read_rolls", "group": "main", "expr": "1d100"},
            {"id": "die", "op": "sum_values", "from": "main", "write": "die_value"},
            {
                "id": "base_value",
                "op": "formula",
                "expr": "max(args.skill_or_characteristic, args.target_value)",
                "write": "base_value",
            },
        ],
        "result_axes": [
            {
                "id": "skill_roll_result",
                "kind": "pass_fail",
                "pass_when": {"var": "die_value", "lte": "base_value"},
                "success_tier": "regular_success",
                "failure_tier": "failure",
            }
        ],
        "primary_axis": "skill_roll_result",
        "labels": {"regular_success": "常规成功", "failure": "失败"},
    }
    pending = PendingCheck(
        id="cocskill",
        engine="generic_resolution_v1",
        procedure_id="coc.skill_check",
        skill="心理学",
        value=60,
        difficulty="regular",
        target=None,
        pool="",
        bonus=0,
        penalty=0,
        reason="CoC IR alias regression",
        raw_match="[pending_check id=cocskill]",
    )
    execution = resolve_pending_execution(
        pending,
        {"engine": "generic_resolution_v1", "ir": ir},
        auto_roll=14,
    )
    runtime_args = execution.result.result_axes["_ir"]["runtime_args"]
    assert_eq("generic coc skill alias numeric", runtime_args["skill_or_characteristic"], 60)
    assert_eq("generic coc skill target alias", runtime_args["target_value"], 60)
    assert_true("generic coc skill resolves", execution.result.passed, execution.rendered)
    assert_true("generic coc skill has no warnings", not execution.result.warnings, repr(execution.result))


def case_generic_ir_sanity_direct_aliases() -> None:
    sanity_ir = {
        "schema_version": "resolution_ir_v1_1",
        "id": "sanity_roll",
        "name": "Direct-compiled sanity roll",
        "primary_family": "sum_vs_target",
        "input_contract": {
            "required": [
                "roll",
                "current_sanity",
                "san_loss_success",
                "san_loss_failure",
            ],
            "optional": {"san_loss_failure_max": {"type": "number", "default": 0}},
        },
        "steps": [
            {"id": "roll", "op": "read_rolls", "group": "main", "expr": "1d100"},
            {"id": "die", "op": "sum_values", "from": "main", "write": "die_value"},
            {
                "id": "effective_failure_max",
                "op": "formula",
                "expr": "max(args.san_loss_failure, args.san_loss_failure_max)",
                "write": "effective_failure_max",
            },
            {
                "id": "success_loss_delta",
                "op": "formula",
                "expr": "0 - args.san_loss_success",
                "write": "success_loss_delta",
            },
            {
                "id": "failure_loss_delta",
                "op": "formula",
                "expr": "0 - args.san_loss_failure",
                "write": "failure_loss_delta",
            },
            {
                "id": "fumble_loss_delta",
                "op": "formula",
                "expr": "0 - effective_failure_max",
                "write": "fumble_loss_delta",
            },
            {
                "id": "san_loss_delta",
                "op": "conditional_value",
                "write": "sanity_delta",
                "cases": [
                    {
                        "when": {
                            "any": [
                                {"var": "die_value", "eq": 100},
                                {
                                    "all": [
                                        {"var": "die_value", "gte": 96},
                                        {"var": "args.current_sanity", "lt": 50},
                                    ]
                                },
                            ]
                        },
                        "value": "fumble_loss_delta",
                    },
                    {
                        "when": {"var": "die_value", "lte": "args.current_sanity"},
                        "value": "success_loss_delta",
                    },
                ],
                "default": "failure_loss_delta",
            },
        ],
        "result_axes": [
            {
                "id": "san_result",
                "kind": "tier",
                "outcomes": [
                    {
                        "tier": "fumble",
                        "when": {
                            "any": [
                                {"var": "die_value", "eq": 100},
                                {
                                    "all": [
                                        {"var": "die_value", "gte": 96},
                                        {"var": "args.current_sanity", "lt": 50},
                                    ]
                                },
                            ]
                        },
                        "passed": False,
                    },
                    {
                        "tier": "success",
                        "when": {"var": "die_value", "lte": "args.current_sanity"},
                        "passed": True,
                    },
                    {"tier": "failure", "default": True, "passed": False},
                ],
            },
            {"id": "sanity_delta", "kind": "resource_delta", "from": "sanity_delta"},
        ],
        "primary_axis": "san_result",
        "labels": {"success": "成功", "failure": "失败", "fumble": "大失败"},
    }
    execution = execute_check_runtime(
        CheckArgs(
            skill="SAN",
            value=45,
            roll=97,
            extras={
                "success_san_loss": 0,
                "failure_san_loss": 2,
                "max_failure_san_loss": 6,
            },
        ),
        {"engine": "generic_resolution_v1", "ir": sanity_ir},
        source="debug_direct_sanity_alias",
    )
    runtime_args = execution.result.result_axes["_ir"]["runtime_args"]
    assert_eq("direct sanity current alias", runtime_args["current_sanity"], 45)
    assert_eq("direct sanity failure alias", runtime_args["san_loss_failure"], 2)
    assert_eq("direct sanity max alias", runtime_args["san_loss_failure_max"], 6)
    assert_eq("direct sanity tier", execution.result.tier, "fumble")
    assert_eq("direct sanity delta", execution.result.side_effects["sanity_delta"], -6)
    assert_true("direct sanity rendered delta", "SAN 变化: -6" in execution.rendered, execution.rendered)
    sample_out = run_resolution_ir(
        sanity_ir,
        {
            "roll": {"main": [97]},
            "current_sanity": 45,
            "san_loss_success": 0,
            "san_loss_failure": 2,
            "san_loss_failure_max": 6,
        },
    )
    assert_eq("direct sanity nested roll sample", sample_out["side_effects"]["sanity_delta"], -6)


def case_direct_compiler_validation_matches_flag_axes() -> None:
    errors = _samples_match(
        {
            "primary_tier": "failure",
            "passed": False,
            "side_effects": {},
            "axes": {
                "temporary_insanity_check": {
                    "kind": "flags",
                    "value": ["temporary_insanity_check_required"],
                }
            },
        },
        {
            "primary_tier": "failure",
            "passed": False,
            "side_effects": {
                "temporary_insanity_check": ["temporary_insanity_check_required"],
            },
        },
    )
    assert_eq("direct compiler flag axis validation", errors, [])


def case_direct_compiler_normalizes_resource_max_inputs() -> None:
    ir = {
        "input_contract": {
            "required": ["roll", "value", "max_failure_san_loss", "stress_loss_max"],
            "optional": {},
        }
    }
    _normalize_ir_for_runtime(ir)
    contract = ir["input_contract"]
    assert_eq("direct max loss removed required", contract["required"], ["roll", "value"])
    assert_eq(
        "direct max failure optional default",
        contract["optional"]["max_failure_san_loss"]["default"],
        0,
    )
    assert_eq(
        "direct loss max optional default",
        contract["optional"]["stress_loss_max"]["default"],
        0,
    )


def case_rule_consequence_sanity_loss_updates_state_without_int() -> None:
    db = FakeDb()
    sess = SimpleNamespace(
        id="sess-san-small",
        character={
            "resources": {"sanity": {"current": 45, "max": 99}},
            "attributes": {"INT": {"value": 80}},
        },
        module_state={"day_count": 1},
        memory_state={},
        dice_history=[],
    )
    spec = _minimal_sanity_runtime_spec()
    execution = execute_check_runtime(
        CheckArgs(
            skill="SAN",
            value=45,
            roll=80,
            extras={
                "actor": "pc",
                "success_san_loss": 0,
                "failure_san_loss": 2,
                "roll_seed": "san-small-seed",
            },
        ),
        spec,
        source="debug_sanity_consequence",
    )
    log = record_check_execution(
        db,
        sess,  # type: ignore[arg-type]
        execution,
        source="inline_check",
        runtime_spec=spec,
    )
    assert_eq("small san state write", sess.character["resources"]["sanity"]["current"], 43)
    events = log.result_json["rule_consequences"]
    assert_eq("small san one event", len(events), 1)
    assert_true("small san no temp insanity", "temporary_insanity_check_required" not in events[0]["flags"], repr(events))
    assert_eq("small san history mirrors consequence", len(sess.dice_history[0]["rule_consequences"]), 1)


def case_rule_consequence_sanity_loss_five_auto_int_success() -> None:
    db = FakeDb()
    sess = SimpleNamespace(
        id="sess-san-big",
        character={
            "resources": {"sanity": {"current": 45, "max": 99}},
            "attributes": {"INT": {"value": 99}},
        },
        module_state={"day_count": 1},
        memory_state={},
        dice_history=[],
    )
    spec = _minimal_sanity_runtime_spec()
    execution = execute_check_runtime(
        CheckArgs(
            skill="SAN",
            value=45,
            roll=97,
            extras={
                "actor": "pc",
                "success_san_loss": 0,
                "failure_san_loss": 6,
                "roll_seed": "san-five-seed",
            },
        ),
        spec,
        source="debug_sanity_consequence",
    )
    log = record_check_execution(
        db,
        sess,  # type: ignore[arg-type]
        execution,
        source="inline_check",
        runtime_spec=spec,
    )
    assert_eq("big san state write", sess.character["resources"]["sanity"]["current"], 39)
    events = log.result_json["rule_consequences"]
    flags = events[0]["flags"]
    assert_true("big san temp check flag", "temporary_insanity_check_required" in flags, repr(events))
    assert_true("big san int resolved", events[0]["followup_checks"][0]["status"] == "resolved", repr(events))
    assert_true("big san temporary insanity", "temporary_insanity" in flags, repr(events))
    assert_eq("big san followup log recorded", len(sess.dice_history), 2)


def case_rule_consequence_sanity_daily_indefinite() -> None:
    db = FakeDb()
    sess = SimpleNamespace(
        id="sess-san-daily",
        character={"resources": {"sanity": {"current": 20, "max": 99}}, "INT": 80},
        module_state={"day_count": 3},
        memory_state={},
        dice_history=[],
    )
    spec = _minimal_sanity_runtime_spec()
    for idx, loss in enumerate((3, 2), start=1):
        execution = execute_check_runtime(
            CheckArgs(
                skill="SAN",
                value=sess.character["resources"]["sanity"]["current"],
                roll=80,
                extras={
                    "actor": "pc",
                    "success_san_loss": 0,
                    "failure_san_loss": loss,
                    "roll_seed": f"san-daily-{idx}",
                },
            ),
            spec,
            source="debug_sanity_daily",
        )
        record_check_execution(
            db,
            sess,  # type: ignore[arg-type]
            execution,
            source="inline_check",
            runtime_spec=spec,
        )
    last_event = sess.dice_history[-1]["rule_consequences"][0]
    assert_eq("daily san final value", sess.character["resources"]["sanity"]["current"], 15)
    assert_true("daily indefinite flag", "indefinite_insanity" in last_event["flags"], repr(last_event))
    assert_eq("daily counter lost", last_event["daily_counter"]["lost_today"], 5)


def case_rule_consequence_catalog_triangle_resource_trigger() -> None:
    db = FakeDb()
    sess = SimpleNamespace(
        id="sess-triangle",
        character={"resources": {"chaos": {"current": 4, "max": 10}}},
        module_state={},
        memory_state={},
        dice_history=[],
    )
    spec = {
        "engine": "custom_llm",
        "_runtime_procedure_id": "triangle.chaos_check",
        "consequences": [
            {
                "id": "chaos_spike",
                "when": {"axis": "chaos_delta", "lte": -3},
                "event_type": "chaos_consequence",
                "system_id": "triangle",
                "resource_delta": {
                    "resource": "chaos",
                    "axis": "chaos_delta",
                    "path_candidates": ["resources.chaos.current"],
                    "clamp_min": 0,
                },
            }
        ],
    }
    execution = CheckExecution(
        args=CheckArgs(skill="Chaos", value=4, extras={"actor": "pc"}),
        spec=spec,
        result=CheckResult(
            tier="failure",
            tier_label="失败",
            passed=False,
            engine="custom_llm",
            roll_display="4",
            side_effects={"chaos_delta": -3},
        ),
        rendered="[dice]\nChaos\n[/dice]",
        trace=RollTrace(
            source="debug_triangle_consequence",
            procedure_id="triangle.chaos_check",
            engine="custom_llm",
            skill="Chaos",
            value=4,
            roll_total=4,
            side_effects={"chaos_delta": -3},
        ),
    )
    log = record_check_execution(
        db,
        sess,  # type: ignore[arg-type]
        execution,
        source="inline_check",
        runtime_spec=spec,
    )
    event = log.result_json["rule_consequences"][0]
    assert_eq("triangle chaos write", sess.character["resources"]["chaos"]["current"], 1)
    assert_eq("triangle event type", event["type"], "chaos_consequence")
    assert_true("triangle prompt block", "Recent Rule Consequences" in recent_rule_consequences_prompt_block(sess))


def case_house_rule_overlay_applies_spec_and_request() -> None:
    ruleset = SimpleNamespace(
        book_title="House d20",
        check_spec={},
        dice_ir={
            "package": {
                "compiled": {
                    "default_procedure_id": "d20.lockpick",
                    "check_specs": [
                        {
                            "procedure_id": "d20.lockpick",
                            "check_spec": {
                                "engine": "d20_vs_dc",
                                "default_dc": 10,
                            },
                        }
                    ],
                },
            },
            "house_rules": [
                {
                    "id": "table.d20.lockpick_training",
                    "procedure_id": "d20.lockpick",
                    "patches": [
                        {"stage": "spec", "op": "set", "path": "default_dc", "value": 15},
                        {"stage": "request", "op": "add", "path": "value", "value": 2},
                        {
                            "stage": "request",
                            "op": "set",
                            "path": "params.allowLuckSpend",
                            "value": True,
                        },
                    ],
                }
            ],
        },
        parsed_v6={},
    )
    spec = build_runtime_check_spec(ruleset)
    assert_eq("house rule spec dc", spec["default_dc"], 15)
    assert_eq(
        "house rule procedure spec dc",
        spec["_runtime_check_specs"]["d20.lockpick"]["default_dc"],
        15,
    )
    execution = execute_check_runtime(
        CheckArgs(skill="开锁", value=3, roll=10),
        spec,
        procedure_id="d20.lockpick",
        auto_roll=False,
        source="debug_house_rule",
    )
    trace = execution.trace.to_metadata()
    house_rules = trace["result_axes"]["_house_rules"]
    assert_eq("house rule request modifier", execution.args.value, 5)
    assert_true("house rule request pass", execution.result.passed, execution.rendered)
    assert_eq("house rule dc threshold", execution.result.thresholds["dc"], 15)
    assert_true(
        "house rule trace id",
        "table.d20.lockpick_training" in house_rules["ids"],
        repr(trace),
    )
    assert_true(
        "house rule request params",
        execution.args.extras["params"]["allowLuckSpend"] is True,
        repr(execution.args.extras),
    )


def case_runtime_check_spec_builds_catalog_indexes() -> None:
    ruleset = SimpleNamespace(
        book_title="Triangle Agency",
        check_spec={},
        dice_ir={
            "package": {
                "compiled": {
                    "default_procedure_id": "triangle.standard_quality",
                    "check_specs": [
                        {
                            "procedure_id": "triangle.standard_quality",
                            "aliases": ["Quality"],
                            "semantic_tags": ["quality_check"],
                            "check_spec": {
                                "engine": "pool_count_n",
                                "per_die_target": 3,
                            },
                        }
                    ],
                },
            },
        },
        parsed_v6={},
    )
    spec = build_runtime_check_spec(ruleset)
    index = spec["_runtime_procedure_index"]["triangle.standard_quality"]
    assert_true("catalog index aliases", "Quality" in index["aliases"], repr(index))
    assert_true("catalog index semantic tag", "quality_check" in index["semantic_tags"], repr(index))
    assert_eq(
        "catalog semantic index",
        spec["_runtime_semantic_index"]["quality_check"],
        ["triangle.standard_quality"],
    )


def case_failed_embedded_dice_ir_does_not_block_background_compile() -> None:
    from routes.rulesets import _extract_embedded_dice_ir  # noqa: PLC0415

    failed_artifact = {
        "version": 6,
        "core_rules": "roll some dice",
        "rule_packages": [],
        "parameter_families": [],
        "dice_ir": {"error": "stage8 failed before producing check_specs"},
    }
    assert_eq(
        "failed embedded dice_ir ignored",
        _extract_embedded_dice_ir(failed_artifact),
        None,
    )

    compiled_artifact = {
        **failed_artifact,
        "dice_ir": {
            "package": {
                "compiled": {
                    "check_specs": [
                        {
                            "procedure_id": "demo.check",
                            "check_spec": {"engine": "d20_vs_dc"},
                        }
                    ]
                }
            }
        },
    }
    extracted = _extract_embedded_dice_ir(compiled_artifact)
    assert_true("compiled embedded dice_ir accepted", isinstance(extracted, dict))


def case_contest_marker_auto_rolls() -> None:
    random.seed(11)
    rendered = replace_contests_in_text(
        '[CONTEST system="coc_7e" mode="melee" reaction="dodge" '
        'attacker="PC" attacker_skill="格斗" attacker_value=35 '
        'defender="守卫" defender_skill="闪避" defender_value=30 '
        'reason="折叠小刀近身攻击"]',
        {"engine": "coc_7e_d100"},
    )
    assert_true("contest marker hidden", "[CONTEST" not in rendered, rendered)
    assert_true("contest renders dice block", "[dice]" in rendered, rendered)
    assert_true(
        "contest keeps opposed labels",
        "攻击方" in rendered and "防守方" in rendered,
        rendered,
    )


def case_speaker_tags_get_stable_npc_key() -> None:
    rendered = annotate_speak_tags(
        "门后传来一句：「别碰它。」[speak:fearful]凯伊[/speak]",
        [{"key": "kei", "name": "凯伊", "summary": "门后的人"}],
    )
    assert_true("speaker tag preserves emotion", "[speak:fearful:kei]" in rendered, rendered)
    assert_true("speaker tag preserves label", "凯伊[/speak]" in rendered, rendered)


def case_speaker_short_name_avoids_descriptive_false_match() -> None:
    hidden_npcs = [{
        "key": "npc_b8584aa1",
        "name": "赛斯",
        "description": "赛斯身材精壮，浑身布满仪式性伤疤和拉丁文纹身。",
    }, "legacy-bad-entry"]
    rendered = annotate_speak_tags(
        "「实话？」[speak:angry]拉斯[/speak]",
        hidden_npcs,
    )
    assert_true("short proper name not fuzzy-matched", "npc_b8584aa1" not in rendered, rendered)
    assert_true("short proper name tag preserved", "[speak:angry]拉斯[/speak]" in rendered, rendered)
    assert_true("short proper name can become spoken npc", is_probable_named_speaker("拉斯"))
    assert_true("generic label not auto npc", not is_probable_named_speaker("陌生人"))
    assert_true("descriptive label is player-known roster candidate", is_trackable_visible_speaker("灰发工装男人"))
    assert_true("bare stranger label is not roster spam", not is_trackable_visible_speaker("陌生人"))
    assert_true(
        "descriptive labels still resolve",
        resolve_speaker_label(
            "灰发工装男人",
            [{"key": "worker", "description": "一个灰发工装男人守在门口"}],
        ) == "worker",
    )
    priest_npc = {
        "key": "priest",
        "name": "莫德凯·奥斯庭 (泰拉里什)",
        "player_known_name": "祭司",
        "portrait_prompt": "通常表现为一名圣灵降临派牧师。",
    }
    assert_true(
        "title label resolves to existing npc",
        resolve_speaker_label("奥斯庭牧师", [priest_npc]) == "priest",
    )
    assert_true("title label is public label, not revealed true name", not is_probable_named_speaker("奥斯庭牧师"))


def case_spoken_npc_auto_create_visible_roster_entry() -> None:
    sess = SimpleNamespace(
        id="session-test",
        user_id="user-test",
        module_state={
            "scene": "scene_gas_station",
            "scene_name": "埃索加油站",
            "title": "血色公路",
        },
        memory_state={"npcs": []},
        character={},
    )

    created = asyncio.run(ensure_spoken_npcs_with_scene(
        sess,
        "「你该走了。」[speak:angry]拉斯[/speak]「别问。」[speak]陌生人[/speak]",
        turn_marker="turn-test",
    ))
    assert_true("spoken npc created", len(created) == 1, repr(created))
    npc = sess.memory_state["npcs"][0]
    assert_true("spoken npc visible name", npc["name"] == "拉斯", repr(npc))
    # Auto-creation never flips name_revealed. A [speak] tag is just dialogue
    # attribution; the player may not have been told the speaker's true name
    # in-fiction. Reveal must come from an explicit [NPC_TURN_SYNC] event.
    assert_true("spoken npc not auto-revealed", npc["name_revealed"] is False, repr(npc))
    assert_true("spoken npc scene", npc["last_seen_scene"] == "scene_gas_station", repr(npc))
    assert_true("spoken npc portrait seed", bool(npc.get("portrait_prompt")), repr(npc))


def case_spoken_descriptive_npc_auto_create_known_roster_entry() -> None:
    sess = SimpleNamespace(
        id="session-test",
        user_id="user-test",
        module_state={
            "scene": "scene_gas_station",
            "scene_name": "埃索加油站",
            "title": "血色公路",
        },
        memory_state={"npcs": []},
        character={},
    )

    created = asyncio.run(ensure_spoken_npcs_with_scene(
        sess,
        "「退后。」[speak:calm]灰发工装男人[/speak]",
        turn_marker="turn-test",
    ))
    assert_true("descriptive spoken npc created", len(created) == 1, repr(created))
    npc = sess.memory_state["npcs"][0]
    assert_true("descriptive npc public label", npc["player_known_name"] == "灰发工装男人", repr(npc))
    assert_true("descriptive npc name unrevealed", npc["name_revealed"] is False, repr(npc))
    assert_true("descriptive npc scene", npc["last_seen_scene"] == "scene_gas_station", repr(npc))
    assert_true("descriptive npc portrait seed", bool(npc.get("portrait_prompt")), repr(npc))


def case_spoken_title_label_updates_existing_npc_alias() -> None:
    sess = SimpleNamespace(
        id="session-test",
        user_id="user-test",
        module_state={
            "scene": "scene_church",
            "scene_name": "教堂",
            "title": "血色公路",
        },
        memory_state={
            "npcs": [
                {
                    "key": "priest",
                    "name": "莫德凯·奥斯庭 (泰拉里什)",
                    "player_known_name": "祭司",
                    "name_revealed": False,
                    "portrait_prompt": "通常表现为一名圣灵降临派牧师。",
                    "portrait_url": "/api/media/files/priest.jpg",
                },
            ],
        },
        character={},
    )

    created = asyncio.run(ensure_spoken_npcs_with_scene(
        sess,
        "「但可惜。」[speak:calm]奥斯庭牧师[/speak]",
        turn_marker="turn-test",
    ))
    assert_true("title label reuses existing npc", created == [], repr(created))
    npc = sess.memory_state["npcs"][0]
    assert_true("title label becomes alias", "奥斯庭牧师" in npc.get("aliases", []), repr(npc))
    assert_true("public label upgraded", npc["player_known_name"] == "奥斯庭牧师", repr(npc))
    assert_true("existing portrait preserved", bool(npc.get("portrait_url")), repr(npc))
    assert_true("title label scene stamped", npc["last_seen_scene"] == "scene_church", repr(npc))


def case_update_npc_params_dot_path() -> None:
    raw = (
        "PC 一刀划过守卫的颈侧。\n"
        '[UPDATE_NPC_PARAMS]{"npc_key":"guard_chen","updates":{"hp.current":6,'
        '"composure_under_threat":2},"reason":"slashed by knife"}'
        '[/UPDATE_NPC_PARAMS]'
    )
    extraction = parse_chatrpg_markers(raw)
    assert_true("npc update parsed", len(extraction.npc_param_updates) == 1)
    sess = SimpleNamespace(
        module_state={},
        memory_state={
            "npcs": [
                {"key": "guard_chen", "name": "守卫陈",
                 "params": {"hp": {"current": 9, "max": 10}}},
            ],
        },
        character={},
    )
    gm_meta: dict[str, object] = {}
    summary = apply_chatrpg_markers(sess, extraction, gm_message_metadata=gm_meta)
    assert_true(
        "hp.current updated",
        sess.memory_state["npcs"][0]["params"]["hp"]["current"] == 6,
        repr(sess.memory_state["npcs"][0]["params"]),
    )
    assert_true(
        "hp.max preserved",
        sess.memory_state["npcs"][0]["params"]["hp"]["max"] == 10,
    )
    assert_true(
        "composure top-level set",
        sess.memory_state["npcs"][0]["params"]["composure_under_threat"] == 2,
    )
    assert_true(
        "summary counts updates",
        summary.get("npc_param_updates") == 1,
        repr(summary),
    )


def case_update_npc_params_unknown_key_does_not_crash() -> None:
    raw = (
        '[UPDATE_NPC_PARAMS]{"npc_key":"ghost","updates":{"hp.current":1},'
        '"reason":"test"}[/UPDATE_NPC_PARAMS]'
    )
    extraction = parse_chatrpg_markers(raw)
    sess = SimpleNamespace(module_state={}, memory_state={"npcs": []}, character={})
    gm_meta: dict[str, object] = {}
    summary = apply_chatrpg_markers(sess, extraction, gm_message_metadata=gm_meta)
    assert_true(
        "missing npc reported as not_found",
        summary.get("npc_param_updates") == 0,
    )


def case_update_pc_params_writes_character() -> None:
    raw = (
        "你按住伤口，意识模糊。\n"
        '[UPDATE_PC_PARAMS]{"updates":{"hp.current":7,"sp.current":4},'
        '"reason":"hit by guard"}[/UPDATE_PC_PARAMS]'
    )
    extraction = parse_chatrpg_markers(raw)
    assert_true("pc update parsed", extraction.pc_param_update is not None)
    sess = SimpleNamespace(
        module_state={},
        memory_state={},
        character={"hp": {"current": 11, "max": 14}, "sp": {"current": 7, "max": 9}},
    )
    gm_meta: dict[str, object] = {}
    summary = apply_chatrpg_markers(sess, extraction, gm_message_metadata=gm_meta)
    assert_true(
        "pc.hp.current",
        sess.character["hp"]["current"] == 7,
        repr(sess.character),
    )
    assert_true("pc.hp.max preserved", sess.character["hp"]["max"] == 14)
    assert_true("pc.sp.current", sess.character["sp"]["current"] == 4)
    assert_true("summary flags pc update", summary.get("pc_param_update") is True)


def case_take_time_initializes_and_advances_clock() -> None:
    extraction = parse_chatrpg_markers("[TAKE_TIME]20min[/TAKE_TIME]")
    sess = SimpleNamespace(module_state={}, memory_state={}, character={})
    gm_meta: dict[str, object] = {}
    summary = apply_chatrpg_markers(sess, extraction, gm_message_metadata=gm_meta)

    assert_true("take time summary", summary.get("elapsed_minutes_added") == 20, repr(summary))
    assert_true("take time elapsed", sess.module_state["elapsed_minutes"] == 20, repr(sess.module_state))
    assert_true("take time day default", sess.module_state["day_count"] == 1, repr(sess.module_state))
    assert_true("take time clock default start", sess.module_state["in_game_time"] == "09:20", repr(sess.module_state))


def case_take_time_rolls_clock_over_midnight() -> None:
    extraction = parse_chatrpg_markers("[TAKE_TIME]20min[/TAKE_TIME]")
    sess = SimpleNamespace(
        module_state={"day_count": 1, "in_game_time": "23:50", "elapsed_minutes": 0},
        memory_state={},
        character={},
    )
    gm_meta: dict[str, object] = {}
    apply_chatrpg_markers(sess, extraction, gm_message_metadata=gm_meta)

    assert_true("take time midnight day", sess.module_state["day_count"] == 2, repr(sess.module_state))
    assert_true("take time midnight clock", sess.module_state["in_game_time"] == "00:10", repr(sess.module_state))
    assert_true("take time midnight period", sess.module_state["in_game_period"] == "night", repr(sess.module_state))


def main() -> None:
    case_check_marker_auto_rolls()
    case_check_marker_default_pending()
    case_mandatory_sanity_check_auto_rolls()
    case_pending_extras_roundtrip_generic_values()
    case_pending_extras_roundtrip_json64()
    case_sanity_check_infers_procedure_and_renders_loss()
    case_coc_sanity_pack_runs_as_generic_ir()
    case_sanity_check_rolls_loss_dice_with_client_roll()
    case_sanity_check_falls_back_when_ruleset_lacks_sanity_proc()
    case_compiled_catalog_alias_routes_generic_procedure()
    case_check_marker_pending_keeps_procedure_id()
    case_check_runtime_trace_for_procedure()
    case_pending_resolve_writes_trace_metadata()
    case_pending_resolve_uses_client_roll()
    case_dice_roller_seeded_trace()
    case_coc_bonus_penalty_trace()
    case_actor_adapter_pc_pending_value()
    case_actor_adapter_npc_resolve_value()
    case_actor_adapter_missing_value_warns()
    case_check_engine_registry_has_builtins()
    case_resolution_ir_v1_is_rejected()
    case_generic_ir_auto_rolls_non_roll_sources()
    case_generic_ir_auto_rolls_variable_count()
    case_generic_ir_coc_skill_uses_numeric_value_alias()
    case_generic_ir_sanity_direct_aliases()
    case_direct_compiler_validation_matches_flag_axes()
    case_direct_compiler_normalizes_resource_max_inputs()
    case_rule_consequence_sanity_loss_updates_state_without_int()
    case_rule_consequence_sanity_loss_five_auto_int_success()
    case_rule_consequence_sanity_daily_indefinite()
    case_rule_consequence_catalog_triangle_resource_trigger()
    case_house_rule_overlay_applies_spec_and_request()
    case_runtime_check_spec_builds_catalog_indexes()
    case_failed_embedded_dice_ir_does_not_block_background_compile()
    case_contest_marker_auto_rolls()
    case_speaker_tags_get_stable_npc_key()
    case_speaker_short_name_avoids_descriptive_false_match()
    case_spoken_npc_auto_create_visible_roster_entry()
    case_spoken_descriptive_npc_auto_create_known_roster_entry()
    case_spoken_title_label_updates_existing_npc_alias()
    case_update_npc_params_dot_path()
    case_update_npc_params_unknown_key_does_not_crash()
    case_update_pc_params_writes_character()
    case_take_time_initializes_and_advances_clock()
    case_take_time_rolls_clock_over_midnight()
    print("All runtime marker cases passed.")


if __name__ == "__main__":
    main()
