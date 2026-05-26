"""Issue model used by the DesignState validator.

Issues are returned with three severity tiers:

- `blocking` -- must be cleared before compile is allowed.
- `warning`  -- author should look, but compile is still permitted.
- `info`     -- neutral hints, e.g. recommended next action.

Codes are short stable strings so the frontend can render localized copy
without parsing free-form messages.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Severity = Literal["blocking", "warning", "info"]


class DesignIssue(BaseModel):
    code: str
    severity: Severity
    message: str
    path: list[str | int] = Field(default_factory=list)
    hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


__all__ = ["Severity", "DesignIssue"]
