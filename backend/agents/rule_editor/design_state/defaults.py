"""Default shape and enumerated values for a DesignState authoring artifact.

DesignState is the authoring-side artifact that users and the rule-design
agent edit. It is **not** the runtime artifact -- the runtime artifact remains
`parsed_v6` and is produced by a future compile step.

The shape here is intentionally a plain `dict[str, Any]` (mirroring the
`parsed_v6` pattern in `template.py`) so it is easy to serialize, copy, and
test. Typed pydantic models live next to the patch ops in `models.py`.
"""

from __future__ import annotations

from typing import Any


SCHEMA_VERSION = 1


# Authoring phases. The agent moves the design state through these phases as
# it fills in slots. P0 keeps the list closed; future phases append at the end.
PHASES: tuple[str, ...] = (
    "intake",
    "blueprint_selection",
    "core_loop",
    "character_model",
    "resolution_model",
    "procedures",
    "catalogs",
    "playtest",
    "ready",
)


# Brief fields the agent records from the user's pitch.
BRIEF_FIELDS: tuple[str, ...] = ("concept", "tone", "complexity", "genre")


# Taxonomy keys describing the rule project at a high level. Open vocabulary;
# the validator only checks that values are strings.
TAXONOMY_FIELDS: tuple[str, ...] = (
    "genre",
    "tone",
    "complexity",
    "era",
    "setting_type",
)


# Slot status values. `missing` is the default; `drafting` is in-progress;
# `filled` is the only status that satisfies a required slot for compile.
SLOT_STATUSES: tuple[str, ...] = ("missing", "drafting", "filled")


# Catalogs that can hold id-keyed entries. P0 leaves the per-entry shape open
# (just `{"id": str, ...}`); P1 will tighten this with action templates.
CATALOG_NAMES: tuple[str, ...] = ("skills", "actions", "resources", "gear")


# Compile status values reflect the latest compile attempt against parsed_v6.
COMPILE_STATUSES: tuple[str, ...] = ("idle", "running", "success", "failed")


def empty_design_state() -> dict[str, Any]:
    """Fresh DesignState for a new draft. Always returns a new dict."""
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "intake",
        "brief": {
            "concept": "",
            "tone": "",
            "complexity": "",
            "genre": "",
            "assumptions": [],
        },
        "taxonomy": {
            "genre": "",
            "tone": "",
            "complexity": "",
            "era": "",
            "setting_type": "",
        },
        "blueprint": {
            "id": "",
            "taxonomy_overrides": {},
            "slots_required": [],
        },
        "slots": {},
        "core_loop": {
            "summary": "",
            "phases": [],
            "pacing": "",
        },
        "character_model": {
            "archetypes": [],
            "attributes": [],
            "derived_stats": [],
            "progression_model": "",
        },
        "resolution_model": {
            "mechanic": "",
            "dice": "",
            "success_thresholds": [],
            "notes": "",
        },
        "procedures": [],
        "catalogs": {name: [] for name in CATALOG_NAMES},
        "action_templates": [],
        "playtests": [],
        "compile": {
            "status": "idle",
            "error": "",
            "parsed_v6_ref": "",
        },
    }


__all__ = [
    "SCHEMA_VERSION",
    "PHASES",
    "BRIEF_FIELDS",
    "TAXONOMY_FIELDS",
    "SLOT_STATUSES",
    "CATALOG_NAMES",
    "COMPILE_STATUSES",
    "empty_design_state",
]
