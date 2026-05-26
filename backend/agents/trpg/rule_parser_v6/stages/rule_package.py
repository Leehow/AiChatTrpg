"""Stage 4 — Per-package detailed rule extraction.

Called once per entry in manifest.detailed_rule_packages. Uses
line_focus.build_narrow_excerpt() to narrow the lined source to the
package's line_hints + source_cues before prompting.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from ..file_block_parser import find_block
from ..line_focus import build_narrow_excerpt
from ..llm_utils import OnChunk, OnProgress, run_stage_llm
from ..prompts import SHARED_SYSTEM, package_user_prompt
from agents.trpg.rule_parser_v4.llm_call import TokenTracker

logger = logging.getLogger("chatlab.trpg")

STAGE_NAME = "package"


def _package_file(package_id: str) -> str:
    return f"rule_packages/{package_id}.md"


async def run_package_stage(
    *,
    book_id: str,
    book_title: str,
    output_language: Optional[str],
    package_descriptor: Dict[str, Any],
    current_core_rules_md: str,
    lined_view: str,
    raw_lines: Sequence[str],
    extra_hint: Optional[str],
    model: str,
    base_url: str,
    api_key: str,
    tracker: Optional[TokenTracker] = None,
    on_progress: OnProgress = None,
    on_chunk: OnChunk = None,
    stream: bool = True,
) -> Dict[str, Any]:
    """Run Stage 4 for one package. Returns {"package_id", "filename", "content", "excerpt_stats"}."""
    package_id = str(package_descriptor.get("package_id") or "").strip()
    if not package_id:
        raise ValueError("package_descriptor missing package_id")
    filename = _package_file(package_id)

    line_hints = package_descriptor.get("line_hints") or []
    source_cues = package_descriptor.get("source_cues") or []
    excerpt, narrowed, stats = build_narrow_excerpt(
        lined_view=lined_view,
        raw_lines=raw_lines,
        line_hints=line_hints,
        source_cues=source_cues,
    )
    stage_tag = f"{STAGE_NAME}:{package_id}"
    if on_progress:
        await on_progress(
            stage_tag,
            f"Extracting package '{package_id}' (narrowed={narrowed})",
        )

    user_message = package_user_prompt(
        book_id=book_id,
        book_title=book_title,
        package_id=package_id,
        output_language=output_language,
        package_descriptor=package_descriptor,
        current_core_rules_md=current_core_rules_md,
        source_excerpt=excerpt,
        excerpt_is_narrowed=narrowed,
        extra_hint=extra_hint,
    )
    raw, blocks = await run_stage_llm(
        stage=stage_tag,
        model=model,
        base_url=base_url,
        api_key=api_key,
        system_prefix=SHARED_SYSTEM,
        user_message=user_message,
        tracker=tracker,
        on_progress=on_progress,
        on_chunk=on_chunk,
        stream=stream,
        log_tag=f"V6-pkg-{package_id}",
    )
    content = find_block(blocks, filename)
    if not content or not content.strip():
        raise ValueError(
            f"Stage 4 package '{package_id}' produced no <<<FILE:{filename}>>> block",
        )
    logger.info(
        "[V6-pkg-%s] chars=%d narrowed=%s excerpt=%d",
        package_id, len(content), narrowed, stats.get("char_count", 0),
    )
    if on_progress:
        await on_progress(
            stage_tag,
            f"Package '{package_id}' ready ({len(content):,} chars)",
        )
    return {
        "package_id": package_id,
        "filename": filename,
        "content": content,
        "excerpt_stats": stats,
        "raw": raw,
    }


async def run_packages(
    *,
    packages: List[Dict[str, Any]],
    book_id: str,
    book_title: str,
    output_language: Optional[str],
    current_core_rules_md: str,
    lined_view: str,
    raw_lines: Sequence[str],
    extra_hint: Optional[str],
    model: str,
    base_url: str,
    api_key: str,
    tracker: Optional[TokenTracker] = None,
    on_progress: OnProgress = None,
    on_chunk: OnChunk = None,
    stream: bool = True,
) -> List[Dict[str, Any]]:
    """Iterate packages sequentially so the provider cache warms up.

    Sequential execution keeps the shared system prefix cacheable and
    avoids per-book rate-limit flakes. Errors on any single package
    are logged and skipped — the pipeline records the failure rather
    than aborting the whole parse.
    """
    out: List[Dict[str, Any]] = []
    for descriptor in packages:
        descriptor_copy = dict(descriptor)
        try:
            result = await run_package_stage(
                book_id=book_id,
                book_title=book_title,
                output_language=output_language,
                package_descriptor=descriptor_copy,
                current_core_rules_md=current_core_rules_md,
                lined_view=lined_view,
                raw_lines=raw_lines,
                extra_hint=extra_hint,
                model=model,
                base_url=base_url,
                api_key=api_key,
                tracker=tracker,
                on_progress=on_progress,
                on_chunk=on_chunk,
                stream=stream,
            )
            out.append(result)
        except Exception as exc:
            pkg_id = descriptor_copy.get("package_id", "?")
            logger.error("[V6-pkg] %s failed: %s", pkg_id, exc)
            if on_progress:
                await on_progress(
                    f"{STAGE_NAME}:{pkg_id}",
                    f"Package '{pkg_id}' failed: {exc}",
                )
            out.append({
                "package_id": pkg_id,
                "filename": _package_file(str(pkg_id)),
                "content": "",
                "error": str(exc),
            })
    return out
