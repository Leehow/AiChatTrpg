"""Persistent audit logger for destructive operations.

The main backend log under /tmp gets overwritten on restart, which
makes it impossible to forensically audit who deleted what during a
prior process. This module adds a dedicated logger named
``chatrpg.audit`` that writes to ``backend/.logs/audit.log`` in
**append** mode, so the trail survives restarts and stays out of the
main app log.

Usage::

    from core.audit_log import audit

    audit(
        "draft.delete",
        actor=user.id,
        target=draft_id,
        extra={"title": draft.title},
    )

The format is one JSON line per event so it's grep-able and easy to
post-process. Failures inside the audit path are swallowed — we never
let logging block a real request.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


_LOG_DIR = Path(__file__).resolve().parents[1] / ".logs"
_LOG_PATH = _LOG_DIR / "audit.log"

_logger: logging.Logger | None = None


def _get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    log = logging.getLogger("chatrpg.audit")
    log.setLevel(logging.INFO)
    # Don't bubble to root — the main backend log doesn't need duplicate
    # entries; this file is the canonical audit trail.
    log.propagate = False
    if log.handlers:
        _logger = log
        return log
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        # Rotate at 5 MB, keep 10 backups → ~50 MB cap, plenty for an
        # audit trail of destructive ops.
        handler = RotatingFileHandler(
            _LOG_PATH,
            maxBytes=5 * 1024 * 1024,
            backupCount=10,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(handler)
    except Exception:
        # If the log file is unwritable, fall back to a stderr handler
        # so we don't lose the audit entirely.
        log.addHandler(logging.StreamHandler())
    _logger = log
    return log


def audit(
    event: str,
    *,
    actor: str | None = None,
    target: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit one structured audit line.

    `event` is a dotted name (``draft.delete``, ``ruleset.delete``).
    `actor` is the user id or service name doing the action.
    `target` is the row id being acted on.
    `extra` is any free-form context (kept terse — this is for grep, not
    deep analytics).
    """
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "actor": actor,
        "target": target,
    }
    if extra:
        payload["extra"] = extra
    try:
        _get_logger().info(json.dumps(payload, ensure_ascii=False))
    except Exception:
        # Audit must never raise into a request handler.
        pass
