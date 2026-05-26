"""Stage 3 — Unified Knowledge Manifest Discovery.

Reads the line-numbered whole-book view alongside the already-built
resident core and companion. Emits a JSON manifest that drives the
rest of the pipeline (which packages, which families, line_hints per
item for narrow-excerpt slicing).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..llm_utils import (
    OnChunk,
    OnProgress,
    run_strict_json_stage,
    strict_json_retry_reminder,
)
from ..prompts import SHARED_SYSTEM, discovery_user_prompt
from agents.trpg.rule_parser_v4.llm_call import TokenTracker

logger = logging.getLogger("chatlab.trpg")

STAGE_NAME = "discovery"
EXPECTED_FILE = "knowledge_manifest.json"


def _normalize_manifest(
    manifest: Any,
    *,
    book_id: str,
    book_title: str,
    world_mode: str,
    companion_file: str,
) -> Dict[str, Any]:
    """Fill in defaults / coerce shape so downstream stages are safe."""
    if not isinstance(manifest, dict):
        raise ValueError("knowledge_manifest.json root must be an object")
    out = dict(manifest)
    out.setdefault("book_id", book_id)
    out.setdefault("book_title", book_title)
    out.setdefault("world_mode", world_mode)
    resident = out.get("resident")
    if not isinstance(resident, dict):
        resident = {}
    resident.setdefault("core_file", "core_rules.md")
    resident.setdefault("companion_file", companion_file)
    out["resident"] = resident

    for list_key in ("detailed_rule_packages", "parameter_families", "aliases"):
        if not isinstance(out.get(list_key), list):
            out[list_key] = []

    cs = out.get("character_sheet_package")
    if not isinstance(cs, dict):
        cs = {"present": False}
    cs.setdefault("present", False)
    cs.setdefault(
        "template_file",
        "character_sheet/character_sheet_template.json",
    )
    cs.setdefault(
        "guide_file",
        "character_sheet/character_creation_guide.md",
    )
    out["character_sheet_package"] = cs
    return out


def _summarize(manifest: Dict[str, Any]) -> str:
    pkgs: List[Dict[str, Any]] = manifest.get("detailed_rule_packages") or []
    fams: List[Dict[str, Any]] = manifest.get("parameter_families") or []
    cs = manifest.get("character_sheet_package") or {}
    return (
        f"packages={len(pkgs)} families={len(fams)} "
        f"character_sheet={'yes' if cs.get('present') else 'no'}"
    )


async def run_discovery_stage(
    *,
    book_id: str,
    book_title: str,
    world_mode: str,
    companion_file: str,
    output_language: Optional[str],
    current_core_rules_md: str,
    current_companion_md: str,
    book_markdown_lined: str,
    extra_hint: Optional[str],
    model: str,
    base_url: str,
    api_key: str,
    tracker: Optional[TokenTracker] = None,
    on_progress: OnProgress = None,
    on_chunk: OnChunk = None,
    stream: bool = True,
) -> Dict[str, Any]:
    """Run Stage 3. Returns the normalized manifest dict."""
    if on_progress:
        await on_progress(STAGE_NAME, "Discovering packages, families, aliases...")

    user_message = discovery_user_prompt(
        book_id=book_id,
        book_title=book_title,
        world_mode=world_mode,
        companion_file=companion_file,
        output_language=output_language,
        current_core_rules_md=current_core_rules_md,
        current_companion_md=current_companion_md,
        book_markdown_lined=book_markdown_lined,
        extra_hint=extra_hint,
    )
    retry_msg = strict_json_retry_reminder() + "\n\n" + user_message

    parsed, raw, _blocks = await run_strict_json_stage(
        stage=STAGE_NAME,
        model=model,
        base_url=base_url,
        api_key=api_key,
        system_prefix=SHARED_SYSTEM,
        user_message=user_message,
        expected_filename=EXPECTED_FILE,
        retry_user_message=retry_msg,
        tracker=tracker,
        on_progress=on_progress,
        on_chunk=on_chunk,
        stream=stream,
        log_tag="V6-discovery",
    )
    manifest = _normalize_manifest(
        parsed,
        book_id=book_id,
        book_title=book_title,
        world_mode=world_mode,
        companion_file=companion_file,
    )
    logger.info("[V6-discovery] %s", _summarize(manifest))
    if on_progress:
        await on_progress(STAGE_NAME, f"Manifest ready: {_summarize(manifest)}")
    return {"manifest": manifest, "raw": raw}
