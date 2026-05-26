"""v6 orchestrator — drive stages 1-8 against one ruleset.

Yields `(event, label, data)` tuples so the route layer can translate
them into SSE. Supports full-pipeline runs and targeted re-runs for
individual stages / items.

Parse modes:
- "full"     : Stage 1 → 2 → 3 → 4×N → 5×N → 6 → 7 → 8
- "core"     : Stage 1 only
- "companion": Stage 2 only
- "discovery": Stage 3 only
- "package"  : single package by target_slug (package_id)
- "family"   : single family by target_slug (family_id)
- "character_sheet": Stage 6 only
- "finalize" : rebuild manifest from current artifact state (no LLM)
- "dice_ir"  : Stage 8 only — recompile the generic dice rule IR

save_checkpoint(patch) persists the v6 artifact dict after each
sub-step so a mid-run crash still keeps earlier work.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from agents.trpg.rule_parser_v4.llm_call import TokenTracker

from .pipeline_helpers import (
    character_descriptor as _character_descriptor,
    find_descriptor as _find_descriptor,
    make_artifact_seed as _make_artifact_seed,
    now_iso as _now_iso,
    upsert as _upsert,
)
from .preprocess import load_book_views
from .stages import (
    assemble_final_manifest,
    run_character_sheet_stage,
    run_companion_stage,
    run_core_stage,
    run_dice_ir_stage,
    run_discovery_stage,
    run_family_stage,
    run_package_stage,
)
from .stages.companion import companion_filename_for_mode
from .stages.core_hooks import (
    apply_core_retrieval_hooks,
    strip_core_retrieval_hooks,
)
from .stages.parameter_family import run_families
from .stages.rule_package import run_packages

logger = logging.getLogger("chatlab.trpg")

HEARTBEAT_SECONDS = 15.0

VALID_MODES = {
    "full",
    "core",
    "companion",
    "discovery",
    "package",
    "family",
    "character_sheet",
    "finalize",
    "dice_ir",
}


async def run_v6_pipeline(
    file_ids: List[str],
    model: str,
    base_url: str,
    api_key: str,
    db,
    *,
    book_id: str,
    book_title: str,
    world_mode: str,
    output_language: Optional[str] = None,
    extra_hint: Optional[str] = None,
    existing_artifact: Optional[Dict[str, Any]] = None,
    parse_mode: str = "full",
    target_slug: Optional[str] = None,
    stream: bool = True,
    save_checkpoint=None,
    dice_ir_config: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[Tuple[str, str, str], None]:
    """Drive the v6 pipeline. See module docstring for event shape."""
    tracker = TokenTracker()
    mode = (parse_mode or "full").strip().lower()
    if mode not in VALID_MODES:
        yield "error", "", f"Unknown parse mode: {mode}"
        return

    artifact = _make_artifact_seed(
        book_id=book_id,
        book_title=book_title,
        world_mode=world_mode,
        output_language=output_language,
        model=model,
        existing=existing_artifact or {},
    )

    async def _persist(patch: Dict[str, Any]) -> None:
        if not save_checkpoint:
            return
        try:
            await save_checkpoint(patch)
        except Exception as exc:
            logger.warning("[V6] checkpoint save failed: %s", exc)

    # Heartbeat + event plumbing: stage executors write to a queue so
    # the generator can emit heartbeats during long LLM waits.
    async def _run_with_queue(coro_factory):
        q: asyncio.Queue = asyncio.Queue()

        async def _on_progress(label: str, status: str):
            await q.put(("progress", label, status))

        async def _on_chunk(label: str, text: str):
            await q.put(("stream", label, text))

        async def _runner():
            try:
                return await coro_factory(_on_progress, _on_chunk)
            finally:
                await q.put(None)

        return q, asyncio.create_task(_runner())

    async def _drain_queue(q: asyncio.Queue, heartbeat_label: str):
        while True:
            try:
                evt = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield "heartbeat", heartbeat_label, "working"
                continue
            if evt is None:
                break
            yield evt

    # Load book views once, even for single-stage runs. Line-numbered
    # view is always cheap relative to the parse itself.
    yield "progress", "load", "Loading rulebook markdown..."
    try:
        plain_view, lined_view, raw_lines = await load_book_views(file_ids, db)
    except Exception as exc:
        yield "error", "", f"Failed to load files: {exc}"
        return
    yield "progress", "load", (
        f"Loaded plain={len(plain_view):,} chars "
        f"lines={len(raw_lines):,}"
    )

    def _core_context() -> str:
        return strip_core_retrieval_hooks(artifact.get("core_rules") or "")

    # ---- Stage 1: core_rules.md ----
    async def _run_core():
        nonlocal artifact
        q, task = await _run_with_queue(
            lambda op, oc: run_core_stage(
                book_id=book_id, book_title=book_title,
                output_language=output_language,
                book_markdown_plain=plain_view,
                extra_hint=extra_hint,
                model=model, base_url=base_url, api_key=api_key,
                tracker=tracker, on_progress=op, on_chunk=oc,
                stream=stream,
            )
        )
        async for evt in _drain_queue(q, "core"):
            yield evt
        result = await task
        artifact["core_rules"] = result["content"]
        await _persist({"core_rules": artifact["core_rules"]})

    # ---- Stage 2: companion ----
    async def _run_companion():
        nonlocal artifact
        q, task = await _run_with_queue(
            lambda op, oc: run_companion_stage(
                world_mode=world_mode,
                book_id=book_id, book_title=book_title,
                output_language=output_language,
                book_markdown_plain=plain_view,
                extra_hint=extra_hint,
                model=model, base_url=base_url, api_key=api_key,
                tracker=tracker, on_progress=op, on_chunk=oc,
                stream=stream,
            )
        )
        async for evt in _drain_queue(q, "companion"):
            yield evt
        result = await task
        artifact["companion"] = {
            "filename": result["filename"],
            "content": result["content"],
            "world_mode": result["world_mode"],
        }
        await _persist({"companion": artifact["companion"]})

    # ---- Stage 3: discovery manifest ----
    async def _run_discovery():
        nonlocal artifact
        companion_filename = (artifact.get("companion") or {}).get("filename") \
            or companion_filename_for_mode(world_mode)
        q, task = await _run_with_queue(
            lambda op, oc: run_discovery_stage(
                book_id=book_id, book_title=book_title,
                world_mode=world_mode,
                companion_file=companion_filename,
                output_language=output_language,
                current_core_rules_md=_core_context(),
                current_companion_md=(artifact.get("companion") or {}).get("content") or "",
                book_markdown_lined=lined_view,
                extra_hint=extra_hint,
                model=model, base_url=base_url, api_key=api_key,
                tracker=tracker, on_progress=op, on_chunk=oc,
                stream=stream,
            )
        )
        async for evt in _drain_queue(q, "discovery"):
            yield evt
        result = await task
        artifact["discovery_manifest"] = result["manifest"]
        await _persist({"discovery_manifest": artifact["discovery_manifest"]})

    # ---- Stage 4: rule packages (all, or single by slug) ----
    async def _run_all_packages():
        nonlocal artifact
        descriptors = (artifact.get("discovery_manifest") or {}).get(
            "detailed_rule_packages",
        ) or []
        if not descriptors:
            yield "progress", "package", "No packages to extract"
            return
        q, task = await _run_with_queue(
            lambda op, oc: run_packages(
                packages=descriptors,
                book_id=book_id, book_title=book_title,
                output_language=output_language,
                current_core_rules_md=_core_context(),
                lined_view=lined_view, raw_lines=raw_lines,
                extra_hint=extra_hint,
                model=model, base_url=base_url, api_key=api_key,
                tracker=tracker, on_progress=op, on_chunk=oc,
                stream=stream,
            )
        )
        async for evt in _drain_queue(q, "package"):
            yield evt
        results = await task
        artifact["rule_packages"] = results
        await _persist({"rule_packages": results})

    async def _run_single_package(slug: str):
        nonlocal artifact
        descriptors = (artifact.get("discovery_manifest") or {}).get(
            "detailed_rule_packages",
        ) or []
        descriptor = _find_descriptor(descriptors, "package_id", slug)
        if not descriptor:
            yield "error", f"package:{slug}", f"No package descriptor for {slug}"
            return
        q, task = await _run_with_queue(
            lambda op, oc: run_package_stage(
                book_id=book_id, book_title=book_title,
                output_language=output_language,
                package_descriptor=dict(descriptor),
                current_core_rules_md=_core_context(),
                lined_view=lined_view, raw_lines=raw_lines,
                extra_hint=extra_hint,
                model=model, base_url=base_url, api_key=api_key,
                tracker=tracker, on_progress=op, on_chunk=oc,
                stream=stream,
            )
        )
        async for evt in _drain_queue(q, f"package:{slug}"):
            yield evt
        result = await task
        artifact["rule_packages"] = _upsert(
            artifact.get("rule_packages") or [], "package_id", result,
        )
        await _persist({"rule_packages": artifact["rule_packages"]})

    # ---- Stage 5: parameter families (all, or single by slug) ----
    async def _run_all_families():
        nonlocal artifact
        descriptors = (artifact.get("discovery_manifest") or {}).get(
            "parameter_families",
        ) or []
        if not descriptors:
            yield "progress", "family", "No families to extract"
            return
        q, task = await _run_with_queue(
            lambda op, oc: run_families(
                families=descriptors,
                book_id=book_id, book_title=book_title,
                output_language=output_language,
                lined_view=lined_view, raw_lines=raw_lines,
                extra_hint=extra_hint,
                model=model, base_url=base_url, api_key=api_key,
                tracker=tracker, on_progress=op, on_chunk=oc,
                stream=stream,
            )
        )
        async for evt in _drain_queue(q, "family"):
            yield evt
        results = await task
        artifact["parameter_families"] = results
        await _persist({"parameter_families": results})

    async def _run_single_family(slug: str):
        nonlocal artifact
        descriptors = (artifact.get("discovery_manifest") or {}).get(
            "parameter_families",
        ) or []
        descriptor = _find_descriptor(descriptors, "family_id", slug)
        if not descriptor:
            yield "error", f"family:{slug}", f"No family descriptor for {slug}"
            return
        q, task = await _run_with_queue(
            lambda op, oc: run_family_stage(
                book_id=book_id, book_title=book_title,
                output_language=output_language,
                family_descriptor=dict(descriptor),
                lined_view=lined_view, raw_lines=raw_lines,
                extra_hint=extra_hint,
                model=model, base_url=base_url, api_key=api_key,
                tracker=tracker, on_progress=op, on_chunk=oc,
                stream=stream,
            )
        )
        async for evt in _drain_queue(q, f"family:{slug}"):
            yield evt
        result = await task
        artifact["parameter_families"] = _upsert(
            artifact.get("parameter_families") or [], "family_id", result,
        )
        await _persist({"parameter_families": artifact["parameter_families"]})

    # ---- Stage 6: character sheet ----
    async def _run_character_sheet():
        nonlocal artifact
        manifest = artifact.get("discovery_manifest") or {}
        cs_desc = manifest.get("character_sheet_package") or {}
        if not cs_desc.get("present"):
            yield "progress", "character_sheet", "Descriptor marks sheet as not present — skipped"
            return
        descriptor = _character_descriptor(manifest)
        q, task = await _run_with_queue(
            lambda op, oc: run_character_sheet_stage(
                book_id=book_id, book_title=book_title,
                output_language=output_language,
                character_descriptor=descriptor,
                current_core_rules_md=_core_context(),
                lined_view=lined_view, raw_lines=raw_lines,
                extra_hint=extra_hint,
                model=model, base_url=base_url, api_key=api_key,
                tracker=tracker, on_progress=op, on_chunk=oc,
                stream=stream,
            )
        )
        async for evt in _drain_queue(q, "character_sheet"):
            yield evt
        try:
            result = await task
            artifact["character_sheet"] = {
                "template_filename": result["template_filename"],
                "template_content": result["template_content"],
                "template_json": result["template_json"],
                "guide_filename": result["guide_filename"],
                "guide_content": result["guide_content"],
            }
        except Exception as exc:
            logger.error("[V6] character_sheet stage failed: %s", exc)
            artifact["character_sheet"] = {
                "error": str(exc),
            }
            yield "progress", "character_sheet", f"Character sheet failed: {exc}"
        await _persist({"character_sheet": artifact["character_sheet"]})

    # ---- Stage 7: final manifest (pure reducer, no LLM) ----
    def _rebuild_final_manifest():
        manifest = assemble_final_manifest(
            discovery_manifest=artifact.get("discovery_manifest") or {},
            produced_package_results=artifact.get("rule_packages") or [],
            produced_family_results=artifact.get("parameter_families") or [],
            character_sheet_present=bool(
                ((artifact.get("discovery_manifest") or {}).get(
                    "character_sheet_package",
                ) or {}).get("present"),
            ),
            character_sheet_failed=bool(
                (artifact.get("character_sheet") or {}).get("error"),
            ),
        )
        artifact["final_manifest"] = manifest
        return manifest

    async def _finalize():
        manifest = _rebuild_final_manifest()
        next_core, hook_stats = apply_core_retrieval_hooks(
            artifact.get("core_rules") or "",
            manifest=manifest,
            produced_family_results=artifact.get("parameter_families") or [],
            output_language=output_language,
        )
        patch: Dict[str, Any] = {"final_manifest": manifest}
        if next_core != (artifact.get("core_rules") or ""):
            artifact["core_rules"] = next_core
            patch["core_rules"] = next_core
        await _persist(patch)
        pkg_count = len(manifest.get("detailed_rule_packages") or [])
        fam_count = len(manifest.get("parameter_families") or [])
        yield "progress", "finalize", (
            f"Final manifest assembled: packages={pkg_count} families={fam_count}"
        )
        if patch.get("core_rules"):
            yield "progress", "finalize", (
                "Core on-demand detail index refreshed: "
                f"packages={hook_stats['packages']} families={hook_stats['families']}"
            )

    # ---- Stage 8: dice rule IR (generic check engine) ----
    async def _run_dice_ir():
        nonlocal artifact
        if not dice_ir_config or not dice_ir_config.get("api_key"):
            yield "progress", "dice_ir", (
                "dice_ir_config not provided — skipping stage 8"
            )
            return
        q, task = await _run_with_queue(
            lambda op, oc: run_dice_ir_stage(
                book_title=book_title,
                book_markdown_plain=plain_view,
                output_language=output_language or "English",
                file_ids=list(file_ids or []),
                dice_ir_config=dict(dice_ir_config),
                previous_artifact=artifact.get("dice_ir") or {},
                on_progress=op, on_chunk=oc,
            )
        )
        async for evt in _drain_queue(q, "dice_ir"):
            yield evt
        try:
            result = await task
            artifact["dice_ir"] = result
            await _persist({"dice_ir": result})
            compiled = (
                result.get("package", {}).get("compiled")
                if isinstance(result.get("package"), dict)
                else {}
            ) or {}
            specs = compiled.get("check_specs") if isinstance(compiled.get("check_specs"), list) else []
            yield "progress", "dice_ir", (
                f"Dice IR compiled: {len(specs)} candidate check_specs"
            )
        except Exception as exc:
            logger.error("[V6] dice_ir stage failed: %s", exc)
            yield "progress", "dice_ir", f"Dice IR compile failed: {exc}"

    # ---- Dispatch ----
    try:
        if mode == "full":
            async for evt in _run_core():
                yield evt
            async for evt in _run_companion():
                yield evt
            async for evt in _run_discovery():
                yield evt
            async for evt in _run_all_packages():
                yield evt
            async for evt in _run_all_families():
                yield evt
            async for evt in _run_character_sheet():
                yield evt
            async for evt in _finalize():
                yield evt
            async for evt in _run_dice_ir():
                yield evt
        elif mode == "core":
            async for evt in _run_core():
                yield evt
            async for evt in _finalize():
                yield evt
        elif mode == "companion":
            async for evt in _run_companion():
                yield evt
            async for evt in _finalize():
                yield evt
        elif mode == "discovery":
            async for evt in _run_discovery():
                yield evt
            async for evt in _finalize():
                yield evt
        elif mode == "package":
            slug = (target_slug or "").strip()
            if not slug:
                yield "error", "", "package mode requires target_slug"
                return
            async for evt in _run_single_package(slug):
                yield evt
            async for evt in _finalize():
                yield evt
        elif mode == "family":
            slug = (target_slug or "").strip()
            if not slug:
                yield "error", "", "family mode requires target_slug"
                return
            async for evt in _run_single_family(slug):
                yield evt
            async for evt in _finalize():
                yield evt
        elif mode == "character_sheet":
            async for evt in _run_character_sheet():
                yield evt
            async for evt in _finalize():
                yield evt
        elif mode == "finalize":
            async for evt in _finalize():
                yield evt
        elif mode == "dice_ir":
            async for evt in _run_dice_ir():
                yield evt
            async for evt in _finalize():
                yield evt
    except asyncio.CancelledError:
        logger.warning("[V6] pipeline cancelled mode=%s", mode)
        raise
    except Exception as exc:
        logger.exception("[V6] pipeline error mode=%s", mode)
        yield "error", "", f"Pipeline error: {exc}"
        return

    # Final SSE "complete" event with summary payload.
    totals = tracker.to_dict()["total"]
    artifact["parsed_at"] = _now_iso()
    artifact["token_usage"] = tracker.to_dict()
    artifact["stats"] = {
        "plain_chars": len(plain_view),
        "total_lines": len(raw_lines),
        "packages_count": len([
            r for r in (artifact.get("rule_packages") or []) if not r.get("error")
        ]),
        "families_count": len([
            r for r in (artifact.get("parameter_families") or []) if not r.get("error")
        ]),
        "character_sheet_present": bool(
            (artifact.get("character_sheet") or {}).get("template_content"),
        ),
    }

    logger.info(
        "[V6] pipeline complete mode=%s calls=%d input=%d output=%d "
        "cache_hit=%.0f%%",
        mode, totals["calls"], totals["input"], totals["output"],
        (totals.get("cache_hit_rate") or 0.0) * 100,
    )
    yield "progress", "tokens", (
        f"in={totals['input']} (cached={totals['cached']}, "
        f"hit={totals['cache_hit_rate']:.0%}) out={totals['output']} "
        f"calls={totals['calls']}"
    )
    yield "complete", mode, json.dumps(artifact, ensure_ascii=False)
