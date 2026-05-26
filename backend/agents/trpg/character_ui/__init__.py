"""LLM-driven character UI schema compiler.

Compiles a ruleset's `character_sheet.template_json` into a typed widget
schema the React renderer can consume. The schema is data-only; no code
generation, no eval. The LLM picks widget types from a fixed catalog and
binds them to the character card via JSON paths.
"""

from .compile import compile_character_ui, CharacterUICompilerError
from .widgets import (
    ATOM_TYPES,
    COMPOUND_CATALOG,
    COMPOUND_TYPES,
    PRIMITIVE_CATALOG,
    PRIMITIVE_TYPES,
    WIDGET_CATALOG,
    WIDGET_TYPES,
)

__all__ = [
    "compile_character_ui",
    "CharacterUICompilerError",
    "ATOM_TYPES",
    "COMPOUND_CATALOG",
    "COMPOUND_TYPES",
    "PRIMITIVE_CATALOG",
    "PRIMITIVE_TYPES",
    "WIDGET_CATALOG",
    "WIDGET_TYPES",
]
