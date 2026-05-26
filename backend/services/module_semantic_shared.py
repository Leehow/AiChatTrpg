"""Loader for the shared TRPG module parser package."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_shared_parser_path() -> None:
    backend_vendor = Path(__file__).resolve().parents[1] / "vendor"
    sibling_shared = Path(__file__).resolve().parents[3] / "trpg"
    for shared_root in (sibling_shared, backend_vendor):
        if shared_root.exists() and str(shared_root) not in sys.path:
            sys.path.insert(0, str(shared_root))
