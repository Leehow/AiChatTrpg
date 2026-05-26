"""v6 stage executors.

Each stage module exposes one async run_*_stage() entry point that
composes prompts + llm_utils + line_focus into a single unit of
work. The pipeline orchestrator drives them in order, aggregates
artifacts, and streams progress to the SSE client.
"""

from __future__ import annotations

from .character_sheet import run_character_sheet_stage
from .companion import run_companion_stage
from .core_rules import run_core_stage
from .dice_ir import run_dice_ir_stage
from .discovery import run_discovery_stage
from .final_manifest import assemble_final_manifest
from .parameter_family import run_family_stage
from .rule_package import run_package_stage

__all__ = [
    "run_core_stage",
    "run_companion_stage",
    "run_discovery_stage",
    "run_package_stage",
    "run_family_stage",
    "run_character_sheet_stage",
    "run_dice_ir_stage",
    "assemble_final_manifest",
]
