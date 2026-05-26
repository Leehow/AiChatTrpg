"""Starter V6 raw artifact for a blank draft.

The shape mirrors what `rule_parser_v6` writes to the DB: a flat dict with
`core_rules`, `companion`, `rule_packages`, `parameter_families`,
`character_sheet`, plus top-level meta (`book_id`, `book_title`,
`world_mode`). Compiled artifacts (`dice_ir`, `check_spec`, `character_ui`)
are absent until the agent triggers a compile pass.
"""

from __future__ import annotations

from typing import Any


def empty_v6() -> dict[str, Any]:
    """Fresh V6 artifact for a blank draft. Always returns a new dict."""
    return {
        "version": 6,
        "book_id": "",
        "book_title": "",
        "world_mode": "",
        "output_language": "",
        "core_rules": "",
        "companion": {"filename": "world_guide.md", "content": ""},
        "rule_packages": [],
        "parameter_families": [],
        "character_sheet": None,
    }
