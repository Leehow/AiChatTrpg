"""Sync open-source files from chatrpg → chatlab.

Direction is one-way: chatrpg is the upstream open-source project; chatlab
overlays its closed-source extensions on top. The sync script copies a
manifest-defined allowlist of files into chatlab's matching path.

Usage:
    python scripts/sync_to_chatlab.py --chatlab-path /path/to/chatlab --dry-run
    python scripts/sync_to_chatlab.py --chatlab-path /path/to/chatlab

The manifest lives in this file (SYNC_PATHS). Edit it when adding new files
or directories that should be byte-identical between the two repos.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SYNC_PATHS: list[str] = [
    # Re-populate as the new TRPG implementation lands. Each entry is a path
    # (file or directory) under repo root that should be byte-identical between
    # chatrpg and chatlab. Anything not listed is local to chatrpg.
]

EXCLUDE_GLOBS: tuple[str, ...] = (
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
)


def is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    if "__pycache__" in parts:
        return True
    name = path.name
    return any(
        name.endswith(suffix.lstrip("*")) for suffix in EXCLUDE_GLOBS if suffix.startswith("*")
    )


def iter_files(rel_path: str) -> list[Path]:
    src = REPO_ROOT / rel_path
    if not src.exists():
        return []
    if src.is_file():
        return [src]
    files = []
    for p in src.rglob("*"):
        if p.is_file() and not is_excluded(p):
            files.append(p)
    return files


def diff_summary(src: Path, dst: Path) -> str:
    if not dst.exists():
        return "NEW"
    if filecmp.cmp(src, dst, shallow=False):
        return ""
    try:
        result = subprocess.run(
            ["diff", "-u", str(dst), str(src)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        n_changed = sum(
            1 for line in result.stdout.splitlines()
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        )
        return f"CHANGED ({n_changed} lines diff)"
    except (subprocess.SubprocessError, OSError):
        return "CHANGED"


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync chatrpg → chatlab.")
    parser.add_argument(
        "--chatlab-path",
        default="../chatlab",
        help="Absolute path to the chatlab repo root.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing.",
    )
    args = parser.parse_args()

    dst_root = Path(args.chatlab_path).expanduser().resolve()
    if not dst_root.exists():
        print(f"chatlab path does not exist: {dst_root}")
        return 1

    print(f"chatrpg: {REPO_ROOT}")
    print(f"chatlab: {dst_root}")
    print(f"mode:    {'DRY RUN' if args.dry_run else 'APPLY'}")
    print()

    n_new = n_changed = n_same = 0
    plan: list[tuple[Path, Path, str]] = []

    for rel in SYNC_PATHS:
        for src in iter_files(rel):
            rel_to_root = src.relative_to(REPO_ROOT)
            dst = dst_root / rel_to_root
            status = diff_summary(src, dst)
            if status == "":
                n_same += 1
                continue
            if status == "NEW":
                n_new += 1
            else:
                n_changed += 1
            plan.append((src, dst, status))

    if not plan:
        print("All files in sync. Nothing to do.")
        return 0

    for src, dst, status in plan:
        rel = src.relative_to(REPO_ROOT)
        print(f"  [{status:18s}] {rel}")

    print()
    print(f"summary: {n_new} new, {n_changed} changed, {n_same} unchanged")

    if args.dry_run:
        print("\n(dry run — no files written)")
        return 0

    print("\napplying...")
    for src, dst, _status in plan:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    print(f"copied {len(plan)} files into {dst_root}")
    print(
        "\n⚠️  Reminder: chatlab's frontend (Vue) may need updates if the API contract changed.\n"
        "   Re-run `python scripts/compile_api/export_spec.py` and inspect contracts/ diffs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
