"""Long-rulebook preparation for ChatLab-style v6 ruleset parsing.

The upstream v6 parser expects a whole-book markdown view for stages 1-3.
Large commercial rulebooks can exceed the local relay model's context window,
so AiChatTrpg first turns an oversized source into a loss-conscious working
source, then feeds that source to the copied v6 stages unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from agents.trpg.rule_parser_v4.llm_call import TokenTracker
from agents.trpg.rule_parser_v6.file_block_parser import find_block
from agents.trpg.rule_parser_v6.llm_utils import run_stage_llm
from agents.trpg.rule_parser_v6.preprocess import make_lined_view, make_plain_view
from agents.trpg.rule_parser_v6.prompts import SHARED_SYSTEM
from services.ruleset_source_filter import SourceSection, filter_ruleset_source

logger = logging.getLogger("chatrpg.ruleset_source_compactor")

ENGLISH_MAX_WORKING_SOURCE_CHARS = 1_000_000
CHINESE_MAX_WORKING_SOURCE_CHARS = 200_000
ENGLISH_PRECOMPACT_CHUNK_CHARS = 300_000
CHINESE_PRECOMPACT_CHUNK_CHARS = 180_000


@dataclass(frozen=True)
class PreparedRulesetSource:
    markdown: str
    plain_view: str
    lined_view: str
    raw_lines: list[str]
    compacted: bool
    original_chars: int
    original_lines: int
    working_chars: int
    working_lines: int
    chunk_count: int
    merge_passes: int
    source_filtered: bool
    dropped_sections: list[SourceSection]
    parameter_sections: list[SourceSection]
    dropped_chars: int
    parameter_chars: int
    parameter_lined_view: str
    parameter_raw_lines: list[str]
    discovery_lined_view: str


async def prepare_ruleset_source(
    markdown: str,
    *,
    book_title: str,
    output_language: str,
    model: str,
    base_url: str,
    api_key: str,
    tracker: TokenTracker,
) -> PreparedRulesetSource:
    """Return the markdown view to feed into the v6 stages."""
    filtered = filter_ruleset_source(markdown)
    source_markdown = filtered.main_markdown
    plain = make_plain_view(source_markdown)
    lined, raw_lines = make_lined_view(source_markdown)
    limit = _working_source_limit(output_language)
    chunk_chars = _precompact_chunk_limit(output_language)
    merge_group_chars = int(limit * 0.95)
    if len(plain) <= limit:
        logger.info(
            "[ruleset-prep] source filter title=%s original=%d main=%d "
            "dropped=%d parameter=%d dropped_sections=%d parameter_sections=%d",
            book_title,
            filtered.original_chars,
            filtered.main_chars,
            filtered.dropped_chars,
            filtered.parameter_chars,
            len(filtered.dropped_sections),
            len(filtered.parameter_sections),
        )
        return PreparedRulesetSource(
            markdown=source_markdown,
            plain_view=plain,
            lined_view=lined,
            raw_lines=raw_lines,
            compacted=False,
            original_chars=filtered.original_chars,
            original_lines=filtered.original_lines,
            working_chars=len(plain),
            working_lines=len(raw_lines),
            chunk_count=1,
            merge_passes=0,
            source_filtered=True,
            dropped_sections=filtered.dropped_sections,
            parameter_sections=filtered.parameter_sections,
            dropped_chars=filtered.dropped_chars,
            parameter_chars=filtered.parameter_chars,
            parameter_lined_view=filtered.parameter_lined_view,
            parameter_raw_lines=filtered.parameter_raw_lines,
            discovery_lined_view=_build_discovery_lined_view(raw_lines),
        )

    chunks = _split_lined_chunks(raw_lines, chunk_chars=chunk_chars)
    logger.info(
        "[ruleset-prep] compacting long source title=%s chars=%d "
        "limit=%d chunk_chars=%d chunks=%d",
        book_title,
        len(plain),
        limit,
        chunk_chars,
        len(chunks),
    )
    digests: list[str] = []
    for idx, (start, end, chunk) in enumerate(chunks, start=1):
        logger.info(
            "[ruleset-prep] digest chunk %d/%d lines=%d-%d chars=%d",
            idx,
            len(chunks),
            start,
            end,
            len(chunk),
        )
        digests.append(
            await _digest_chunk(
                chunk,
                index=idx,
                total=len(chunks),
                start_line=start,
                end_line=end,
                book_title=book_title,
                output_language=output_language,
                model=model,
                base_url=base_url,
                api_key=api_key,
                tracker=tracker,
            ),
        )
        logger.info(
            "[ruleset-prep] digest chunk %d/%d ready chars=%d",
            idx,
            len(chunks),
            len(digests[-1]),
        )

    merged, passes = await _merge_until_fit(
        digests,
        book_title=book_title,
        output_language=output_language,
        model=model,
        base_url=base_url,
        api_key=api_key,
        tracker=tracker,
        limit=limit,
        merge_group_chars=merge_group_chars,
    )
    working_lined, working_raw = make_lined_view(merged)
    working_plain = make_plain_view(merged)
    return PreparedRulesetSource(
        markdown=merged,
        plain_view=working_plain,
        lined_view=working_lined,
        raw_lines=working_raw,
        compacted=True,
        original_chars=filtered.original_chars,
        original_lines=filtered.original_lines,
        working_chars=len(working_plain),
        working_lines=len(working_raw),
        chunk_count=len(chunks),
        merge_passes=passes,
        source_filtered=True,
        dropped_sections=filtered.dropped_sections,
        parameter_sections=filtered.parameter_sections,
        dropped_chars=filtered.dropped_chars,
        parameter_chars=filtered.parameter_chars,
        parameter_lined_view=filtered.parameter_lined_view,
        parameter_raw_lines=filtered.parameter_raw_lines,
        discovery_lined_view=_build_discovery_lined_view(working_raw),
    )


def _split_lined_chunks(
    raw_lines: list[str],
    *,
    chunk_chars: int,
) -> list[tuple[int, int, str]]:
    chunks: list[tuple[int, int, str]] = []
    buffer: list[str] = []
    start_line = 1
    current_chars = 0

    for line_no, line in enumerate(raw_lines, start=1):
        rendered = f"{line_no:06d}: {line}"
        if buffer and current_chars + len(rendered) + 1 > chunk_chars:
            chunks.append((start_line, line_no - 1, "\n".join(buffer)))
            buffer = []
            start_line = line_no
            current_chars = 0
        buffer.append(rendered)
        current_chars += len(rendered) + 1

    if buffer:
        chunks.append((start_line, len(raw_lines), "\n".join(buffer)))
    return chunks


async def _digest_chunk(
    chunk: str,
    *,
    index: int,
    total: int,
    start_line: int,
    end_line: int,
    book_title: str,
    output_language: str,
    model: str,
    base_url: str,
    api_key: str,
    tracker: TokenTracker,
) -> str:
    filename = f"source_digests/chunk_{index:03d}.md"
    user_message = _chunk_prompt(
        filename=filename,
        index=index,
        total=total,
        start_line=start_line,
        end_line=end_line,
        book_title=book_title,
        output_language=output_language,
        chunk=chunk,
    )
    chunk_logger = _ChunkLogger(f"precompact:{index:03d}")
    raw, blocks = await run_stage_llm(
        stage=f"precompact:{index:03d}",
        model=model,
        base_url=base_url,
        api_key=api_key,
        system_prefix=SHARED_SYSTEM,
        user_message=user_message,
        tracker=tracker,
        on_chunk=chunk_logger,
        stream=True,
        log_tag=f"V6-precompact-{index:03d}",
    )
    chunk_logger.finish()
    content = find_block(blocks, filename) or raw
    return (
        f"# Source Digest {index}/{total}: lines {start_line}-{end_line}\n\n"
        f"{content.strip()}\n"
    )


async def _merge_until_fit(
    digests: list[str],
    *,
    book_title: str,
    output_language: str,
    model: str,
    base_url: str,
    api_key: str,
    tracker: TokenTracker,
    limit: int,
    merge_group_chars: int,
) -> tuple[str, int]:
    current = digests
    passes = 0
    while len("\n\n".join(current)) > limit and len(current) > 1:
        passes += 1
        next_round: list[str] = []
        for group_index, group in enumerate(
            _group_by_chars(current, merge_group_chars=merge_group_chars),
            start=1,
        ):
            filename = f"source_digests/merge_{passes}_{group_index:03d}.md"
            logger.info(
                "[ruleset-prep] merge pass=%d group=%d items=%d chars=%d",
                passes,
                group_index,
                len(group),
                len("\n\n".join(group)),
            )
            user_message = _merge_prompt(
                filename=filename,
                book_title=book_title,
                output_language=output_language,
                digests="\n\n---\n\n".join(group),
            )
            chunk_logger = _ChunkLogger(
                f"precompact:merge:{passes}:{group_index:03d}",
            )
            raw, blocks = await run_stage_llm(
                stage=f"precompact:merge:{passes}:{group_index:03d}",
                model=model,
                base_url=base_url,
                api_key=api_key,
                system_prefix=SHARED_SYSTEM,
                user_message=user_message,
                tracker=tracker,
                on_chunk=chunk_logger,
                stream=True,
                log_tag=f"V6-precompact-merge-{passes}-{group_index:03d}",
            )
            chunk_logger.finish()
            merged = (find_block(blocks, filename) or raw).strip()
            logger.info(
                "[ruleset-prep] merge pass=%d group=%d ready chars=%d",
                passes,
                group_index,
                len(merged),
            )
            next_round.append(merged)
        current = next_round

    merged = "\n\n".join(current).strip()
    if len(merged) > limit:
        logger.warning(
            "[ruleset-prep] compacted source still large chars=%d limit=%d",
            len(merged),
            limit,
        )
    return merged, passes


def _group_by_chars(
    items: list[str],
    *,
    merge_group_chars: int,
) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    size = 0
    for item in items:
        if current and size + len(item) > merge_group_chars:
            groups.append(current)
            current = []
            size = 0
        current.append(item)
        size += len(item)
    if current:
        groups.append(current)
    return groups


def _working_source_limit(output_language: str) -> int:
    if (output_language or "").strip().lower().startswith("chinese"):
        return CHINESE_MAX_WORKING_SOURCE_CHARS
    return ENGLISH_MAX_WORKING_SOURCE_CHARS


def _precompact_chunk_limit(output_language: str) -> int:
    if (output_language or "").strip().lower().startswith("chinese"):
        return CHINESE_PRECOMPACT_CHUNK_CHARS
    return ENGLISH_PRECOMPACT_CHUNK_CHARS


def _build_discovery_lined_view(raw_lines: list[str]) -> str:
    """Compact line-numbered outline for Stage 3 manifest discovery."""
    headings: list[tuple[int, int, str]] = []
    for idx, line in enumerate(raw_lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            if 1 <= level <= 4 and stripped[level:level + 1] == " ":
                headings.append((idx, level, stripped))

    heading_ranges: dict[int, int] = {}
    for pos, (line_no, level, _title) in enumerate(headings):
        end = len(raw_lines)
        for next_line, next_level, _next_title in headings[pos + 1:]:
            if next_level <= level:
                end = next_line - 1
                break
        heading_ranges[line_no] = end

    include: set[int] = set()
    for line_no, _level, _title in headings:
        include.add(line_no)
        # Keep a small amount of immediate context under each top heading.
        for extra in range(line_no + 1, min(len(raw_lines), line_no + 6) + 1):
            include.add(extra)

    stub_terms = (
        "Parameter Family Source:",
        "original_line_hints:",
        "Removed Built-In Scenario",
        "Investigator Sheet",
        "character sheet",
    )
    for idx, line in enumerate(raw_lines, start=1):
        if any(term.lower() in line.lower() for term in stub_terms):
            for extra in range(max(1, idx - 2), min(len(raw_lines), idx + 8) + 1):
                include.add(extra)

    out: list[str] = []
    for idx in sorted(include):
        line = raw_lines[idx - 1]
        out.append(f"[L{idx:06d}] {line}")
        if idx in heading_ranges:
            out.append(
                f"[L{idx:06d}] section_range: [[{idx}, {heading_ranges[idx]}]]",
            )
    return "\n".join(out)


class _ChunkLogger:
    def __init__(self, stage: str) -> None:
        self.stage = stage
        self.chars = 0
        self.next_log_at = 2_000

    async def __call__(self, _stage: str, text: str) -> None:
        self.chars += len(text or "")
        if self.chars >= self.next_log_at:
            logger.info(
                "[ruleset-prep] stream %s chars=%d",
                self.stage,
                self.chars,
            )
            self.next_log_at += 2_000

    def finish(self) -> None:
        logger.info(
            "[ruleset-prep] stream %s complete chars=%d",
            self.stage,
            self.chars,
        )


def _chunk_prompt(
    *,
    filename: str,
    index: int,
    total: int,
    start_line: int,
    end_line: int,
    book_title: str,
    output_language: str,
    chunk: str,
) -> str:
    return f"""Task: prepare a thick, high-fidelity v6 working source for one rulebook chunk.

Book: {book_title}
Chunk: {index}/{total}
Original source lines: {start_line}-{end_line}
OUTPUT_LANGUAGE: {output_language}

The downstream ChatLab v6 stages will use all chunk digests as their source for:
core_rules.md, companion guide, knowledge_manifest.json, rule packages,
parameter JSON families, character sheet template, final manifest, and dice IR.

Working-source requirements:
- Preserve operational rules, procedures, timing order, exact thresholds, dice formulas, costs, durations, damage, sanity, advancement, combat, magic, equipment, chase, recovery, and character-creation details.
- Preserve compact tables when the rows are mechanically meaningful. If a table is too long, keep the column schema, row patterns, and exact lookup boundary.
- Keep source headings and original line references where useful.
- Include lore/style only when it affects play, tone, roles, setting assumptions, or GM behavior.
- Omit decorative prose and duplicate examples unless an example defines a rule.
- Do not invent package ids, schemas, or final conclusions.
- Do not optimize for brevity. For English books the downstream main v6
  stages can accept up to about 1,000,000 characters, so preserve detail
  aggressively and allow a long output when the chunk contains real rules.

Return exactly one file block:
<<<FILE:{filename}>>>
# thick markdown working source here
<<<END_FILE>>>

SOURCE CHUNK
```text
{chunk}
```"""


def _merge_prompt(
    *,
    filename: str,
    book_title: str,
    output_language: str,
    digests: str,
) -> str:
    return f"""Task: merge v6 working sources without losing rules.

Book: {book_title}
OUTPUT_LANGUAGE: {output_language}

Merge the supplied working sources into a denser source for the downstream
ChatLab v6 stages. Preserve exact mechanics, thresholds, formulas, table
schemas, character creation, combat, sanity, magic, advancement, and lookup
boundaries. Remove duplicated prose, repeated headings, and purely decorative
examples. Keep original source-line references when they identify where a rule
came from.

Do not optimize for brevity. Keep the merged English working source detailed up
to the million-character budget when the material is mechanically useful.

Return exactly one file block:
<<<FILE:{filename}>>>
# merged thick markdown working source here
<<<END_FILE>>>

WORKING SOURCES
```markdown
{digests}
```"""
