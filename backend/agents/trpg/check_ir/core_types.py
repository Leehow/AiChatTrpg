"""Public types for the dice-rule IR interpreter.

Holds the exception hierarchy and the ``Die`` value object that every other
``core_*`` module consumes. Splitting these into a leaf module keeps the
runtime/expression/steps/axes modules free of circular imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class DiceIRValidationError(ValueError):
    """The IR shape is invalid or references missing static fields."""


class DiceIRExecutionError(RuntimeError):
    """The IR was valid enough to run, but execution failed."""


class DiceIRManualResolutionRequired(RuntimeError):
    """The IR needs a human/player choice that was not supplied."""


@dataclass
class Die:
    """Normalized die result with enough metadata for mixed dice systems."""

    id: str
    value: int
    sides: int
    faceset: str
    source_group: str
    tags: List[str] = field(default_factory=list)
    kept: bool = True
    exploded_from: Optional[str] = None
    locked: bool = False
    original_value: Optional[int] = None

    def copy(self, **updates: Any) -> "Die":
        data = self.to_dict()
        data.update(updates)
        return Die(
            id=str(data["id"]),
            value=int(data["value"]),
            sides=int(data["sides"]),
            faceset=str(data["faceset"]),
            source_group=str(data["source_group"]),
            tags=list(data.get("tags") or []),
            kept=bool(data.get("kept", True)),
            exploded_from=data.get("exploded_from"),
            locked=bool(data.get("locked", False)),
            original_value=data.get("original_value"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "value": self.value,
            "sides": self.sides,
            "faceset": self.faceset,
            "source_group": self.source_group,
            "tags": list(self.tags),
            "kept": self.kept,
            "exploded_from": self.exploded_from,
            "locked": self.locked,
            "original_value": self.original_value,
        }
