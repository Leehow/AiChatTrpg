"""Static audit for the dice IR single-writer invariant.

After the M1 refactor the only agent-side path that may merge new
procedures into `draft.parsed_v6.dice_ir` (and mirror them onto a
linked target ruleset) is `apply_dice_proposal` in
`backend/agents/rule_editor_dice/tools_apply.py`. This test enforces
that invariant by static inspection so a future regression — for
example, someone re-inlining a merge into `tools_design` or adding a
shortcut writer in the main rule_editor tool set — fails loudly
before it reaches a smoke test.

No DB, no LLM, no network. Pure source-file scanning. Run:

    cd backend && source .venv/bin/activate
    python debug/trpg/test_dice_single_writer.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"

# Agent-layer directories the invariant applies to. The ruleset
# compile workflow (`services/ruleset_parse_workflow.py`,
# `routes/rulesets*.py`) writes `dice_ir` through its own deterministic
# pipeline and is not part of this invariant — agent code is.
AGENT_ROOTS = (
    BACKEND_ROOT / "agents" / "rule_editor_dice",
    BACKEND_ROOT / "agents" / "rule_editor",
)

# The lone authorized writer.
APPLY_MODULE = (
    BACKEND_ROOT / "agents" / "rule_editor_dice" / "tools_apply.py"
)

# The tool that composes through the apply boundary.
DESIGN_MODULE = (
    BACKEND_ROOT / "agents" / "rule_editor_dice" / "tools_design.py"
)


def fail(label: str, why: str = "") -> None:
    print(f"FAIL: {label} {why}")
    sys.exit(1)


def assert_true(label: str, cond: bool, why: str = "") -> None:
    if not cond:
        fail(label, why)
    print(f"OK: {label}")


def _iter_agent_files() -> list[Path]:
    out: list[Path] = []
    for root in AGENT_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            out.append(p)
    return out


def _grep_lines(path: Path, pattern: re.Pattern[str]) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(path.read_text().splitlines(), start=1):
        # Skip docstring/comment lines that merely *mention* the
        # symbol — we only care about actual code references.
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if pattern.search(line):
            hits.append((i, line.rstrip()))
    return hits


def _strip_string_literals(line: str) -> str:
    """Drop double- and single-quoted string contents from a line so
    a docstring or error message that contains the symbol we are
    scanning for does not register as a code reference."""
    line = re.sub(r'"(?:\\.|[^"\\])*"', '""', line)
    line = re.sub(r"'(?:\\.|[^'\\])*'", "''", line)
    return line


def _grep_code(path: Path, pattern: re.Pattern[str]) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for i, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if line.startswith("#"):
            continue
        if pattern.search(_strip_string_literals(raw)):
            hits.append((i, raw.rstrip()))
    return hits


def test_merge_helper_only_in_apply_module() -> None:
    print("\n--- 1. _merge_into_dice_ir owner ---")
    pattern = re.compile(r"\b_merge_into_dice_ir\b")
    offenders: list[str] = []
    for path in _iter_agent_files():
        hits = _grep_code(path, pattern)
        if not hits:
            continue
        if path.resolve() == APPLY_MODULE.resolve():
            continue
        for ln, txt in hits:
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{ln}: {txt}")
    assert_true(
        "agents/* never reference `_merge_into_dice_ir` outside "
        "tools_apply.py",
        not offenders,
        why="offenders=\n  " + "\n  ".join(offenders) if offenders else "",
    )
    # And confirm tools_apply.py actually defines + calls it (no
    # accidental rename).
    apply_src = APPLY_MODULE.read_text()
    assert_true(
        "tools_apply.py defines `_merge_into_dice_ir`",
        re.search(r"^def _merge_into_dice_ir\b", apply_src, re.MULTILINE)
        is not None,
    )
    assert_true(
        "tools_apply.py calls `_merge_into_dice_ir(` from "
        "apply_dice_proposal",
        re.search(r"\b_merge_into_dice_ir\(", apply_src) is not None,
    )


def test_parsed_v6_dice_ir_write_owner() -> None:
    print("\n--- 2. parsed_v6['dice_ir'] = ... owner ---")
    # Match `parsed_v6["dice_ir"] =` and `parsed_v6['dice_ir'] =`,
    # but NOT comparison operators.
    pattern = re.compile(
        r"""parsed_v6\s*\[\s*(?P<q>["'])dice_ir(?P=q)\s*\]\s*=(?!=)"""
    )
    offenders: list[str] = []
    for path in _iter_agent_files():
        hits = _grep_code(path, pattern)
        if not hits:
            continue
        if path.resolve() == APPLY_MODULE.resolve():
            continue
        for ln, txt in hits:
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{ln}: {txt}")
    assert_true(
        "agents/* never write `parsed_v6[\"dice_ir\"] = ...` outside "
        "tools_apply.py",
        not offenders,
        why="offenders=\n  " + "\n  ".join(offenders) if offenders else "",
    )


def test_target_ruleset_dice_ir_mirror_owner() -> None:
    print("\n--- 3. <obj>.dice_ir = ... mirror owner ---")
    pattern = re.compile(r"\b\w+\.dice_ir\s*=(?!=)")
    offenders: list[str] = []
    for path in _iter_agent_files():
        hits = _grep_code(path, pattern)
        if not hits:
            continue
        if path.resolve() == APPLY_MODULE.resolve():
            continue
        for ln, txt in hits:
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{ln}: {txt}")
    assert_true(
        "agents/* never assign to any `*.dice_ir` outside "
        "tools_apply.py",
        not offenders,
        why="offenders=\n  " + "\n  ".join(offenders) if offenders else "",
    )


def test_tools_design_composes_through_apply() -> None:
    print("\n--- 4. tools_design composes through apply_dice_proposal ---")
    src = DESIGN_MODULE.read_text()
    assert_true(
        "tools_design imports apply_dice_proposal from .tools_apply",
        re.search(
            r"from\s+\.tools_apply\s+import\s+[^\n]*\bapply_dice_proposal\b",
            src,
        )
        is not None,
    )
    assert_true(
        "tools_design calls apply_dice_proposal(...) from the executor",
        re.search(r"\bapply_dice_proposal\s*\(", src) is not None,
    )
    assert_true(
        "tools_design no longer imports flag_modified directly "
        "(persistence delegated to tools_apply)",
        "from sqlalchemy.orm.attributes import flag_modified" not in src,
    )
    assert_true(
        "tools_design no longer references `needs_dice_compile` "
        "(persistence delegated to tools_apply)",
        "needs_dice_compile" not in src,
    )


def test_apply_module_exports_proposal_function() -> None:
    print("\n--- 5. tools_apply exposes apply_dice_proposal ---")
    src = APPLY_MODULE.read_text()
    assert_true(
        "tools_apply.py defines `async def apply_dice_proposal`",
        re.search(
            r"^async def apply_dice_proposal\b", src, re.MULTILINE,
        )
        is not None,
    )
    # Importability smoke — exercises the module path without
    # hitting the DB.
    sys.path.insert(0, str(BACKEND_ROOT))
    from agents.rule_editor_dice.tools_apply import (  # noqa: E402
        apply_dice_proposal as _apply,
    )
    assert_true(
        "apply_dice_proposal is importable",
        callable(_apply),
    )


def test_dice_tools_export_unchanged() -> None:
    print("\n--- 6. DICE_TOOLS surface unchanged ---")
    sys.path.insert(0, str(BACKEND_ROOT))
    from agents.rule_editor_dice.tools import DICE_TOOLS  # noqa: E402
    names = sorted(t.name for t in DICE_TOOLS)
    expected = sorted([
        "read_dice_state",
        "design_dice_procedure",
        "test_dice_procedure",
    ])
    if names != expected:
        fail(
            "DICE_TOOLS export drift",
            why=f"got={names} expected={expected}",
        )
    print(f"OK: DICE_TOOLS exposes exactly {expected}")
    # apply_dice_proposal MUST NOT be advertised in M1 — the writer
    # stays a Python-internal boundary until CodeAct / bridge work
    # (M2+) explicitly chooses to expose it.
    assert_true(
        "apply_dice_proposal is NOT advertised as a DICE_TOOL",
        "apply_dice_proposal" not in names,
    )


def main() -> None:
    test_merge_helper_only_in_apply_module()
    test_parsed_v6_dice_ir_write_owner()
    test_target_ruleset_dice_ir_mirror_owner()
    test_tools_design_composes_through_apply()
    test_apply_module_exports_proposal_function()
    test_dice_tools_export_unchanged()
    print("\nAll dice single-writer invariant checks passed.")


if __name__ == "__main__":
    main()
