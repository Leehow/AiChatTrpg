"""Shared, app-independent TRPG module parsing rules."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from .prompts import DISTILL_PROMPT, INDEX_PROMPT, PARSE_PROMPT, SPLIT_PROMPT

JsonCaller = Callable[[str, str], Awaitable[dict[str, Any] | None]]
TextCaller = Callable[[str, str], Awaitable[str]]

VALID_TYPES = {
    "location", "mission", "chapter", "scene",
    "intro", "rules", "npc_list", "map", "handout", "timeline",
    "appendix", "appendix_rules", "appendix_list", "appendix_others",
}
PLAYABLE_TYPES = {"location", "mission", "chapter", "scene"}
APPENDIX_TYPES = {"appendix", "appendix_rules", "appendix_list", "appendix_others"}
OTHER_TYPES = {"intro", "rules", "npc_list", "map", "handout", "timeline"}
APPENDIX_TITLE_RE = re.compile(r"(附录|appendix)", re.IGNORECASE)

ANCHOR_TO_MODULE = {
    "location": ("sandbox", "standalone"),
    "mission": ("mission", "standalone"),
    "chapter": ("chapter", "sequential"),
    "story_arc": ("chapter", "sequential"),
}

MAX_TOKENS = 800_000
SPLIT_THRESHOLD = 5_000
SPLIT_TARGET = 4_500
MERGE_THRESHOLD = 3_000
MERGE_CAP = 6_000

async def parse_structure(
    markdown: str,
    profile: dict[str, Any],
    call_json: JsonCaller,
) -> dict[str, Any] | None:
    lines = markdown.splitlines()
    numbered = "\n".join(f"L{i + 1}: {line}" for i, line in enumerate(lines))
    if estimate_mixed_tokens(numbered) > MAX_TOKENS:
        return None
    payload = json.dumps(
        {
            "module_title": profile.get("title", ""),
            "language": profile.get("language", ""),
            "total_lines": len(lines),
        },
        ensure_ascii=False,
    )
    result = await call_json(PARSE_PROMPT, f"{payload}\n\n{numbered}")
    if not result or "sections" not in result:
        return None

    anchor_type = str(result.get("anchor_type") or "chapter")
    progression = result.get("progression")
    if progression not in ("linear", "sandbox"):
        progression = "sandbox" if anchor_type == "location" else "linear"
    sections = clean_sections(result.get("sections") or [], lines)
    normalize_preplay_sections(sections)
    mod_type, connection = ANCHOR_TO_MODULE.get(anchor_type, ("chapter", "sequential"))
    return {
        "type": mod_type,
        "title": profile.get("title") or "Untitled Module",
        "connection": connection,
        "anchor_type": anchor_type,
        "progression": progression,
        "guide": str(result.get("guide") or "").strip(),
        "selection_rule": (
            str(result.get("selection_rule") or "").strip()
            if progression == "sandbox" else ""
        ),
        "sections": sections,
    }

def clean_sections(raw_sections: list[Any], lines: list[str]) -> list[dict[str, Any]]:
    total = len(lines)
    sections: list[dict[str, Any]] = []
    for section in raw_sections:
        if not isinstance(section, dict):
            continue
        start = _int(section.get("start_line") or section.get("line_start"))
        end = _int(section.get("end_line") or section.get("line_end"))
        if not (1 <= start <= total and 1 <= end <= total):
            start = end = 0
            text = ""
        else:
            text = "\n".join(lines[start - 1:end])
        section_type = str(section.get("type") or "intro")
        if section_type not in VALID_TYPES:
            section_type = "intro"
        sections.append({
            "title": str(section.get("title") or ""),
            "type": section_type,
            "start_line": start,
            "end_line": end,
            "line_start": start,
            "line_end": end,
            "char_count": len(text),
            "token_count": estimate_mixed_tokens(text),
            "summary": str(section.get("summary") or ""),
        })
    sections = sorted(sections, key=lambda item: item.get("start_line") or 0)
    if sections and sections[0].get("start_line", 0) > 1:
        first = sections[0]
        text = "\n".join(lines[:first.get("end_line", 1)])
        first.update({"start_line": 1, "line_start": 1, "char_count": len(text), "token_count": estimate_mixed_tokens(text)})
    return sections

def normalize_preplay_sections(sections: list[dict[str, Any]]) -> None:
    first_main = next(
        (
            i for i, section in enumerate(sections)
            if section.get("type") in PLAYABLE_TYPES
            and _int(section.get("token_count")) >= SPLIT_THRESHOLD
        ),
        None,
    )
    if first_main is None:
        return
    for section in sections[:first_main]:
        if section.get("type") not in PLAYABLE_TYPES:
            continue
        tokens = _int(section.get("token_count"))
        if section.get("type") != "scene" or tokens < 200:
            section["type"] = "intro"


def split_structure_packs(sections: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    playable, appendix, other = [], [], []
    for section in sections:
        section_type = str(section.get("type") or "intro")
        title = str(section.get("title") or "")
        if APPENDIX_TITLE_RE.search(title) or section_type in APPENDIX_TYPES:
            appendix.append(section)
        elif section_type in PLAYABLE_TYPES:
            playable.append(section)
        else:
            other.append(section)
    return {"playable": playable, "appendix": appendix, "other": other}


async def rebalance_playable(
    markdown: str,
    playable: list[dict[str, Any]],
    call_json: JsonCaller,
) -> tuple[list[dict[str, Any]], list[str]]:
    logs: list[str] = []
    if not playable:
        return [], logs
    lines = markdown.splitlines()
    total = len(lines)
    split_sections: list[dict[str, Any]] = []
    for section in sorted(playable, key=lambda s: s.get("start_line") or 0):
        tokens = _int(section.get("token_count"))
        if tokens <= SPLIT_THRESHOLD or str(section.get("type") or "") == "mission":
            split_sections.append({**section, "parent": None})
            continue
        chunks = await _split_section(lines, total, section, call_json)
        if not chunks:
            split_sections.append({**section, "parent": None})
            continue
        split_sections.extend(chunks)
        logs.append(f"{section.get('title')} -> {len(chunks)} chunks")
    merged = merge_small_sections(split_sections)
    return [{**section, "unit_id": f"u{i + 1}"} for i, section in enumerate(merged)], logs


async def _split_section(
    lines: list[str],
    total: int,
    section: dict[str, Any],
    call_json: JsonCaller,
) -> list[dict[str, Any]]:
    start = _int(section.get("start_line"), 1)
    end = _int(section.get("end_line"), total)
    section_lines = [f"L{i}: {lines[i - 1]}" for i in range(start, min(end + 1, total + 1))]
    content = (
        f"Section: {section.get('title')} (L{start}–L{end}, "
        f"~{section.get('token_count', 0)} tokens)\n\n" + "\n".join(section_lines)
    )
    parsed = await call_json(SPLIT_PROMPT.format(max_tokens=SPLIT_TARGET), content)
    chunks = parsed.get("chunks") if isinstance(parsed, dict) else None
    if not isinstance(chunks, list):
        return []
    result: list[dict[str, Any]] = []
    for chunk in sorted(chunks, key=lambda c: _int(c.get("start_line")) if isinstance(c, dict) else 0):
        if not isinstance(chunk, dict):
            continue
        chunk_start = _int(chunk.get("start_line"), start)
        chunk_end = _int(chunk.get("end_line"), end)
        if not (1 <= chunk_start <= total and 1 <= chunk_end <= total):
            continue
        text = "\n".join(lines[chunk_start - 1:chunk_end])
        result.append({
            "title": str(chunk.get("title") or section.get("title") or ""),
            "type": section.get("type"),
            "start_line": chunk_start,
            "end_line": chunk_end,
            "line_start": chunk_start,
            "line_end": chunk_end,
            "char_count": len(text),
            "token_count": estimate_mixed_tokens(text),
            "summary": "",
            "parent": section.get("title"),
        })
    return result


def merge_small_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    def append_into(prev: dict[str, Any], section: dict[str, Any]) -> None:
        prev["title"] = prev["title"] + " / " + section["title"]
        prev["end_line"] = prev["line_end"] = section["end_line"]
        prev["char_count"] = prev.get("char_count", 0) + section.get("char_count", 0)
        prev["token_count"] = prev.get("token_count", 0) + section.get("token_count", 0)

    def flush_into(target: dict[str, Any]) -> list[dict[str, Any]]:
        if not pending:
            return []
        target_tokens = target.get("token_count", 0)
        absorbed: list[dict[str, Any]] = []
        if target_tokens >= SPLIT_THRESHOLD or not merged:
            absorbed = list(pending)
            split_idx = 0
        else:
            split_idx = len(pending)
            for i in range(len(pending) - 1, -1, -1):
                item = pending[i]
                if target_tokens + item.get("token_count", 0) <= MERGE_CAP:
                    absorbed.append(item)
                    target_tokens += item.get("token_count", 0)
                    split_idx = i
                else:
                    break
            absorbed.reverse()
        leftovers = list(pending[:split_idx])
        if absorbed:
            all_sections = absorbed + [target]
            target["title"] = " / ".join(s["title"] for s in all_sections)
            target["start_line"] = target["line_start"] = all_sections[0]["start_line"]
            target["char_count"] = sum(s.get("char_count", 0) for s in all_sections)
            target["token_count"] = sum(s.get("token_count", 0) for s in all_sections)
            if not target.get("summary"):
                target["summary"] = " + ".join(s["title"] for s in absorbed)
        pending.clear()
        return leftovers

    for section in sections:
        tokens = section.get("token_count", 0)
        if tokens >= MERGE_THRESHOLD:
            merged.extend(flush_into(section))
            merged.append(section)
        elif (
            merged and section.get("parent")
            and section["parent"] == merged[-1].get("parent")
            and merged[-1].get("token_count", 0) + tokens <= MERGE_CAP
        ):
            append_into(merged[-1], section)
        else:
            pending.append(section)

    if pending and merged:
        last = merged[-1]
        for item in pending:
            if (
                last.get("token_count", 0) >= SPLIT_THRESHOLD
                or last.get("token_count", 0) + item.get("token_count", 0) <= MERGE_CAP
            ):
                append_into(last, item)
            else:
                merged.append(item)
                last = item
    elif pending:
        combined = pending[0].copy()
        for item in pending[1:]:
            if combined.get("token_count", 0) + item.get("token_count", 0) <= MERGE_CAP:
                append_into(combined, item)
            else:
                merged.append(combined)
                combined = item.copy()
        merged.append(combined)
    return merged


async def distill_briefing(
    markdown: str,
    sections: list[dict[str, Any]],
    call_text: TextCaller,
) -> str:
    parts = section_texts(markdown, sections)
    if not parts:
        return ""
    return await call_text(DISTILL_PROMPT, "\n\n".join(parts))


async def index_appendix_lists(
    markdown: str,
    sections: list[dict[str, Any]],
    call_json: JsonCaller,
) -> dict[str, Any]:
    tables: list[dict[str, Any]] = []
    for section in sections:
        text = numbered_section_text(markdown, section)
        if not text:
            continue
        table = await call_json(INDEX_PROMPT.format(category=section.get("title", "appendix")), text)
        if isinstance(table, dict) and isinstance(table.get("entries"), list):
            tables.append({
                "source_title": section.get("title", ""),
                "start_line": section.get("start_line"),
                "end_line": section.get("end_line"),
                "category": table.get("category") or section.get("title", ""),
                "entries": table.get("entries", []),
            })
    index: list[dict[str, Any]] = []
    for table in tables:
        for entry in table["entries"]:
            if isinstance(entry, dict):
                index.append({
                    **entry,
                    "source": table["source_title"],
                    "source_range": f"L{table['start_line']}–L{table['end_line']}",
                })
    return {"tables": tables, "index": index}


def section_texts(markdown: str, sections: list[dict[str, Any]]) -> list[str]:
    parts = []
    for section in sections:
        text = line_span(markdown, section)
        if text:
            parts.append(
                f"=== {section.get('title')} "
                f"(L{section.get('start_line')}–L{section.get('end_line')}) ===\n{text}"
            )
    return parts


def numbered_section_text(markdown: str, section: dict[str, Any]) -> str:
    lines = markdown.splitlines()
    start = _int(section.get("start_line") or section.get("line_start"))
    end = _int(section.get("end_line") or section.get("line_end"))
    if not (start and end):
        return ""
    return "\n".join(f"L{i}: {lines[i - 1]}" for i in range(start, min(end + 1, len(lines) + 1)))


def line_span(markdown: str, section: dict[str, Any]) -> str:
    lines = markdown.splitlines()
    start = _int(section.get("start_line") or section.get("line_start"))
    end = _int(section.get("end_line") or section.get("line_end"))
    if not (start and end):
        return ""
    return "\n".join(lines[start - 1:min(end, len(lines))])


def pack_step_summary(packs: dict[str, Any]) -> str:
    return (
        f"playable {len(packs.get('playable', []))} / "
        f"appendix {len(packs.get('appendix', []))} / "
        f"other {len(packs.get('other', []))}"
    )


def estimate_mixed_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = 0
    ascii_chars = 0
    for char in text:
        if "\u4e00" <= char <= "\u9fff" or "\u3000" <= char <= "\u303f":
            cjk += 1
        else:
            ascii_chars += 1
    return cjk + (ascii_chars // 3)


def extract_json(text: str) -> dict[str, Any] | None:
    try:
        match = re.search(r"\{[\s\S]*\}", text or "")
        if match:
            value = json.loads(match.group())
            return value if isinstance(value, dict) else None
    except Exception:
        return None
    return None


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
