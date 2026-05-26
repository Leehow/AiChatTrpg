"""Deterministic tests for the dice CodeAct primitives.

No DB, no LLM, no network. Pure import + execute. Run:

    cd backend && source .venv/bin/activate
    python debug/trpg/test_dice_codeact_primitives.py

Asserts:
  1. Every advertised skeleton family compiles via the validator
     with its own canned sample suite.
  2. `propose_ir_skeleton` returns a deep-copy (mutations of the
     output never bleed into the source examples).
  3. `mutate_ir` supports add/replace/remove on dict and list nodes
     and rejects malformed ops with `CodeActPrimitiveError`.
  4. `run_sample` returns structured failure dicts instead of raising
     when the IR is malformed.
  5. `simulate_probability` is seed-reproducible: same seed ⇒ same
     tier histogram.
  6. `simulate_probability` honours the hard cap (`n>10000` rejects).
  7. The Nd<sides> roll-group case (FitD action roll) resolves
     `count_from: args.value` correctly when args_template is given.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))


def fail(label: str, why: str = "") -> None:
    print(f"FAIL: {label} {why}")
    sys.exit(1)


def assert_true(label: str, cond: bool, why: str = "") -> None:
    if not cond:
        fail(label, why)
    print(f"OK: {label}")


from agents.rule_editor_dice import codeact_primitives as P  # noqa: E402
from agents.rule_editor_dice import codeact_fixtures as F  # noqa: E402


def test_skeleton_families_validate() -> None:
    print("\n--- 1. each skeleton validates against its canned samples ---")
    sample_families = set(F.KNOWN_SAMPLE_FAMILIES)
    for fam in F.KNOWN_SKELETON_FAMILIES:
        ir = P.propose_ir_skeleton(fam, procedure_id="x", name="X")
        if fam not in sample_families:
            print(f"OK: {fam} (no sample suite — skeleton-only)")
            continue
        samples = P.generate_sample_cases(fam)
        v = P.validate_proposal(ir, samples)
        assert_true(
            f"{fam} validates with default samples",
            v["ok"],
            why=f"errors={v['errors']}",
        )


def test_coc_high_skill_samples_validate() -> None:
    print("\n--- 1b. CoC d100 high-skill sample suites validate ---")
    ir = P.propose_ir_skeleton("coc_7e_d100", procedure_id="x", name="X")

    samples_95 = P.generate_sample_cases("coc_7e_d100", {"skill": 95})
    failure_95 = next((c for c in samples_95 if c["name"] == "failure"), None)
    assert_true(
        "skill=95 emits a failure sample (roll between skill and fumble band)",
        failure_95 is not None and failure_95["args"]["roll"] == [96],
        why=f"failure={failure_95}",
    )
    v95 = P.validate_proposal(ir, samples_95)
    assert_true(
        "skill=95 sample suite validates end-to-end",
        v95["ok"],
        why=f"errors={v95['errors']}",
    )

    samples_99 = P.generate_sample_cases("coc_7e_d100", {"skill": 99})
    failure_99 = next((c for c in samples_99 if c["name"] == "failure"), None)
    assert_true(
        "skill=99 omits failure sample (no eligible non-fumble roll)",
        failure_99 is None,
        why=f"unexpected failure case: {failure_99}",
    )
    v99 = P.validate_proposal(ir, samples_99)
    assert_true(
        "skill=99 sample suite validates end-to-end",
        v99["ok"],
        why=f"errors={v99['errors']}",
    )


def test_skeleton_is_deep_copy() -> None:
    print("\n--- 2. propose_ir_skeleton returns a deep-copy ---")
    ir = P.propose_ir_skeleton("coc_7e_d100", procedure_id="x", name="X")
    ir["steps"].append({"id": "tampered", "op": "formula", "expr": "1"})
    # Re-fetch and confirm the source template wasn't poisoned.
    ir2 = P.propose_ir_skeleton("coc_7e_d100", procedure_id="x", name="X")
    assert_true(
        "second fetch is unaffected by first-call mutation",
        not any(s.get("id") == "tampered" for s in ir2["steps"]),
    )


def test_mutate_ir_supports_basic_ops() -> None:
    print("\n--- 3. mutate_ir supports add/replace/remove ---")
    ir = P.propose_ir_skeleton("pbta_2d6", procedure_id="x", name="X")
    original_labels = copy.deepcopy(ir["labels"])

    m_replace = P.mutate_ir(
        ir, [{"op": "replace", "path": "/labels/hit", "value": "BIG WIN"}],
    )
    assert_true(
        "replace updates target without touching original",
        m_replace["labels"]["hit"] == "BIG WIN"
        and ir["labels"] == original_labels,
    )

    m_add = P.mutate_ir(
        ir, [{"op": "add", "path": "/labels/extra", "value": "NEW"}],
    )
    assert_true("add inserts a new key", m_add["labels"]["extra"] == "NEW")

    m_remove = P.mutate_ir(ir, [{"op": "remove", "path": "/labels/miss"}])
    assert_true("remove deletes key", "miss" not in m_remove["labels"])

    m_step = P.mutate_ir(
        ir, [{"op": "replace", "path": "/steps/0/expr", "value": "2d6"}],
    )
    assert_true(
        "list-indexed pointer replaces correctly",
        m_step["steps"][0]["expr"] == "2d6",
    )

    # Malformed ops surface as CodeActPrimitiveError.
    try:
        P.mutate_ir(ir, [{"op": "delete", "path": "/labels/hit"}])
    except P.CodeActPrimitiveError as exc:
        assert_true(
            "unsupported op kind rejected",
            "unsupported patch op" in str(exc),
        )
    else:
        fail("unsupported patch op should have raised")

    try:
        P.mutate_ir(ir, [{"op": "remove", "path": "/labels/nope"}])
    except P.CodeActPrimitiveError:
        print("OK: remove on missing key rejected")
    else:
        fail("remove on missing key should have raised")


def test_run_sample_handles_bad_ir() -> None:
    print("\n--- 4. run_sample returns structured failure on bad IR ---")
    bad_ir = {"schema_version": "totally_unknown_v1", "steps": []}
    r = P.run_sample(bad_ir, {})
    assert_true(
        "schema mismatch surfaces as ok=False",
        r.get("ok") is False and r.get("error_kind") == "validation",
        why=str(r),
    )

    ir = P.propose_ir_skeleton("coc_7e_d100", procedure_id="x", name="X")
    r2 = P.run_sample(ir, {})  # missing required `skill` / `roll`
    assert_true(
        "missing required arg surfaces as ok=False",
        r2.get("ok") is False and r2.get("error_kind") == "execution",
        why=str(r2),
    )


def test_simulate_is_reproducible() -> None:
    print("\n--- 5. simulate_probability is seed-reproducible ---")
    ir = P.propose_ir_skeleton("coc_7e_d100", procedure_id="x", name="X")
    args_template = {"skill": 50}

    sim_a = P.simulate_probability(
        ir, n=300, seed=42, args_template=args_template,
    )
    sim_b = P.simulate_probability(
        ir, n=300, seed=42, args_template=args_template,
    )
    assert_true(
        "same seed ⇒ same tier histogram",
        sim_a["tiers"] == sim_b["tiers"]
        and sim_a["pass_rate"] == sim_b["pass_rate"],
    )

    sim_c = P.simulate_probability(
        ir, n=300, seed=43, args_template=args_template,
    )
    assert_true(
        "different seed ⇒ different histogram (very high probability)",
        sim_c["tiers"] != sim_a["tiers"],
    )

    # Sanity: CoC d100 skill=50 pass_rate hovers ~0.50 with sampling
    # noise. Loose band to keep the test deterministic but informative.
    assert_true(
        "CoC d100 skill=50 pass rate in (0.30, 0.70)",
        0.30 < (sim_a["pass_rate"] or 0.0) < 0.70,
        why=f"pass_rate={sim_a['pass_rate']}",
    )


def test_simulate_hard_cap() -> None:
    print("\n--- 6. simulate_probability rejects oversized n ---")
    ir = P.propose_ir_skeleton("d20_vs_dc", procedure_id="x", name="X")
    try:
        P.simulate_probability(
            ir, n=20000, seed=1,
            args_template={"target": 15, "value": 0},
        )
    except P.CodeActPrimitiveError as exc:
        assert_true("hard cap message present", "hard cap" in str(exc))
    else:
        fail("n>10000 should have raised CodeActPrimitiveError")


def test_simulate_nd_roll_group_count_from_args() -> None:
    print("\n--- 7. Nd<sides> count_from args.value resolves ---")
    ir = P.propose_ir_skeleton("fitd_pool", procedure_id="x", name="X")
    sim = P.simulate_probability(
        ir, n=300, seed=42, args_template={"value": 3},
    )
    assert_true(
        "fitd_pool simulation runs cleanly with args.value=3",
        sim["errors"] == 0 and sum(sim["tiers"].values()) == 300,
        why=f"errors={sim['errors']} samples={sum(sim['tiers'].values())}",
    )

    # Missing args.value ⇒ CodeActPrimitiveError (count cannot resolve).
    try:
        P.simulate_probability(ir, n=10, seed=1)
    except P.CodeActPrimitiveError:
        print("OK: missing count_from arg rejected")
    else:
        fail("missing count_from arg should have raised")


def main() -> None:
    test_skeleton_families_validate()
    test_coc_high_skill_samples_validate()
    test_skeleton_is_deep_copy()
    test_mutate_ir_supports_basic_ops()
    test_run_sample_handles_bad_ir()
    test_simulate_is_reproducible()
    test_simulate_hard_cap()
    test_simulate_nd_roll_group_count_from_args()
    print("\nAll dice CodeAct primitive checks passed.")


if __name__ == "__main__":
    main()
