"""Read-only starter blueprint library for the rule design agent."""

from __future__ import annotations

from .data import all_blueprints
from .loader import (
    BlueprintNotFoundError,
    apply_blueprint,
    get_blueprint,
    list_blueprints,
    recommend_blueprints,
)


__all__ = [
    "all_blueprints",
    "BlueprintNotFoundError",
    "apply_blueprint",
    "get_blueprint",
    "list_blueprints",
    "recommend_blueprints",
]
