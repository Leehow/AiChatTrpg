"""Stage 8 — generic dice-rule IR compilation.

Wraps ``agents.trpg.check_ir.compile_direct.compile_to_ir_direct`` so it
fits the v6 stage protocol used by the orchestrator. The compiler owns
procedure discovery, IR emission, and sample validation. This module just
adapts inputs/outputs and shapes the artifact to live under
``parse_artifacts.v6.dice_ir``.

The IR compiler runs LLM calls under its own model/api config (default
``gpt-5.4``) which is independent of the v6 stage models. The route
layer resolves that config and passes it in as ``dice_ir_config``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("chatlab.trpg")


_DICE_IR_ARTIFACT_SCHEMA = "ruleset_dice_ir_compiler_artifact_v1"


OnProgress = Optional[Callable[[str, str], Awaitable[None]]]
OnChunk = Optional[Callable[[str, str], Awaitable[None]]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_dice_ir_stage(
    *,
    book_title: str,
    book_markdown_plain: str,
    output_language: str,
    file_ids: List[str],
    dice_ir_config: Dict[str, Any],
    previous_artifact: Optional[Dict[str, Any]] = None,
    on_progress: OnProgress = None,
    on_chunk: OnChunk = None,
) -> Dict[str, Any]:
    """Compile the merged rulebook markdown into a dice IR package.

    Returns the artifact dict to store under ``v6.dice_ir``. Preserves
    any existing ``applied_check_spec`` so re-running stage 8 doesn't
    erase the runtime apply bookkeeping.
    """
    from agents.trpg.check_ir.compile_direct import (
        DEFAULT_DICE_COMPILER_MODEL,
        compile_to_ir_direct,
    )

    if not (book_markdown_plain or "").strip():
        raise ValueError("dice_ir stage requires non-empty rulebook markdown")
    if not isinstance(dice_ir_config, dict) or not dice_ir_config.get("api_key"):
        raise ValueError("dice_ir stage requires dice_ir_config with api_key")

    model = (
        str(dice_ir_config.get("model") or "").strip()
        or DEFAULT_DICE_COMPILER_MODEL
    )
    base_url = str(dice_ir_config.get("base_url") or "")
    api_key = str(dice_ir_config.get("api_key") or "")

    if on_progress:
        await on_progress("dice_ir", f"compiling check rules with {model}")

    package = await compile_to_ir_direct(
        book_markdown_plain,
        system_name=str(book_title or "").strip(),
        house_rules="",
        model=model,
        base_url=base_url,
        api_key=api_key,
        output_language=output_language or "English",
        on_progress=on_progress,
        on_chunk=on_chunk,
    )

    artifact: Dict[str, Any] = {
        "schema_version": _DICE_IR_ARTIFACT_SCHEMA,
        "saved_at": _now_iso(),
        "source": {
            "kind": "v6_stage8",
            "file_ids": list(file_ids or []),
            "chars": len(book_markdown_plain),
        },
        "output_language": output_language,
        "language_resolution": {
            "source": "v6_pipeline",
            "language": output_language,
        },
        "model": package.get("model") or model,
        "package": package,
    }

    if isinstance(previous_artifact, dict):
        applied = previous_artifact.get("applied_check_spec")
        if isinstance(applied, dict):
            artifact["applied_check_spec"] = applied

    compiled = (
        package.get("compiled") if isinstance(package.get("compiled"), dict) else {}
    )
    specs = compiled.get("check_specs") if isinstance(compiled.get("check_specs"), list) else []
    logger.info(
        "[V6-stage8] dice_ir compiled book=%s model=%s output_language=%s "
        "specs=%d audit=%s",
        book_title, model, output_language, len(specs), bool(audit),
    )
    return artifact
