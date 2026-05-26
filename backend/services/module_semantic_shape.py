"""ChatLab-style shape helpers for module semantic parsing."""

from __future__ import annotations

import re
from typing import Any

PLAYABLE_TYPES = {"location", "mission", "chapter", "scene"}
APPENDIX_TYPES = {"appendix", "appendix_rules", "appendix_list", "appendix_others"}
GLOBAL_REF_TYPES = {
    "intro",
    "rules",
    "npc_list",
    "map",
    "handout",
    "timeline",
    *APPENDIX_TYPES,
}

SPLIT_THRESHOLD = 10000
MERGE_THRESHOLD = 3000
MERGE_CAP = 6000


def split_structure_packs(sections: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    playable, appendix, other = [], [], []
    for section in sections:
        section_type = str(section.get("type") or "other")
        title = str(section.get("title") or "")
        if section_type in APPENDIX_TYPES or re.search(r"(附录|appendix)", title, re.I):
            appendix.append(section)
        elif section_type in PLAYABLE_TYPES:
            playable.append(section)
        else:
            other.append(section)
    return {"playable": playable, "appendix": appendix, "other": other}


def rebalance_playable(playable: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(playable, key=lambda s: _int(s.get("line_start") or s.get("start_line")))
    merged: list[dict[str, Any]] = []
    buffer: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        merged.append(_combine(buffer))
        buffer = []

    for section in ordered:
        tokens = _int(section.get("token_count"))
        parent = section.get("parent")
        if tokens >= MERGE_THRESHOLD:
            flush()
            merged.append(section)
            continue
        if (
            buffer
            and buffer[-1].get("parent") == parent
            and sum(_int(s.get("token_count")) for s in buffer) + tokens <= MERGE_CAP
        ):
            buffer.append(section)
        else:
            flush()
            buffer = [section]
    flush()
    return [{**section, "unit_id": f"u{idx + 1}"} for idx, section in enumerate(merged)]


def split_oversized_by_outline(
    markdown: str,
    playable: list[dict[str, Any]],
    outline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for section in playable:
        tokens = _int(section.get("token_count"))
        if tokens <= SPLIT_THRESHOLD or section.get("type") == "mission":
            result.append(section)
            continue
        children = _child_headings(section, outline)
        if len(children) < 2:
            result.append(section)
            continue
        for child in children:
            start = _int(child.get("line_start"))
            end = _int(child.get("line_end"))
            text = slice_by_line(markdown, start, end)
            result.append(
                {
                    **section,
                    "title": f"{section.get('title')} - {child.get('title')}",
                    "start_line": start,
                    "end_line": end,
                    "line_start": start,
                    "line_end": end,
                    "char_count": len(text),
                    "token_count": estimate_tokens(text),
                    "summary": str(child.get("preview") or "")[:180],
                    "parent": section.get("title"),
                }
            )
    return result


def derive_playable_units(
    playable: list[dict[str, Any]],
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    index_by_title = {str(s.get("title")): i for i, s in enumerate(sections)}
    units = []
    for section in playable:
        title = str(section.get("title") or "Untitled")
        kind = str(section.get("type") or "chapter")
        units.append(
            {
                "title": title,
                "kind": kind if kind in PLAYABLE_TYPES else "chapter",
                "summary": section.get("summary", ""),
                "line_start": _int(section.get("line_start") or section.get("start_line")),
                "line_end": _int(section.get("line_end") or section.get("end_line")),
                "section_indexes": [index_by_title.get(title, 0)],
            }
        )
    return units


def derive_global_refs(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "title": s.get("title", ""),
            "kind": s.get("type", "other"),
            "summary": s.get("summary", ""),
            "line_start": _int(s.get("line_start") or s.get("start_line")),
            "line_end": _int(s.get("line_end") or s.get("end_line")),
        }
        for s in sections
        if str(s.get("type") or "other") in GLOBAL_REF_TYPES
    ]


def normalize_sections(raw: list[Any], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections = []
    valid = PLAYABLE_TYPES | GLOBAL_REF_TYPES | {"other"}
    for item in raw:
        if not isinstance(item, dict):
            continue
        section_type = str(item.get("type") or "other")
        if section_type not in valid:
            section_type = "other"
        start = _int(item.get("line_start") or item.get("start_line"))
        end = _int(item.get("line_end") or item.get("end_line"))
        if end and start and end < start:
            end = start
        sections.append(
            {
                **item,
                "title": str(item.get("title") or "Untitled"),
                "type": section_type,
                "summary": str(item.get("summary") or ""),
                "line_start": start,
                "line_end": end,
                "start_line": start,
                "end_line": end,
                "char_count": _int(item.get("char_count")),
                "token_count": _int(item.get("token_count")),
            }
        )
    return sorted(sections or fallback, key=lambda s: _int(s.get("line_start")))


def infer_anchor_type(sections: list[dict[str, Any]]) -> str:
    counts = {
        "location": sum(1 for s in sections if s.get("type") == "location"),
        "mission": sum(1 for s in sections if s.get("type") == "mission"),
        "chapter": sum(1 for s in sections if s.get("type") in {"chapter", "scene"}),
    }
    if counts["location"] >= max(counts["mission"], counts["chapter"], 1):
        return "location"
    if counts["mission"] >= max(counts["chapter"], 1):
        return "mission"
    return "chapter"


def module_type(anchor_type: str) -> str:
    if anchor_type == "location":
        return "sandbox"
    if anchor_type == "mission":
        return "mission"
    return "chapter"


def quick_guide(sections: list[dict[str, Any]]) -> str:
    lines = ["## Quick Keeper Guide"]
    for section in sections[:8]:
        lines.append(f"- {section.get('title', 'Untitled')}: {section.get('summary', '')}")
    return "\n".join(lines)


def selection_rule(playable: list[dict[str, Any]]) -> str:
    if not playable:
        return ""
    first = playable[0].get("title", "first playable block")
    return f"Start with {first} unless the players choose another available lead."


def apply_playable(playable: list[dict[str, Any]], sections: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "packs": split_structure_packs(sections),
        "playable": playable,
        "playable_units": derive_playable_units(playable, sections)[:24],
        "global_refs": derive_global_refs(sections),
    }


def slice_by_line(markdown: str, start: int, end: int) -> str:
    if start <= 0 or end <= 0:
        return ""
    lines = markdown.splitlines()
    start = max(1, start)
    end = min(len(lines), max(start, end))
    return "\n".join(lines[start - 1:end]).strip()


def range_char_count(markdown: str, start: int, end: int) -> int:
    return len(slice_by_line(markdown, start, end))


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    return max(1, cjk + (len(text) - cjk) // 4)


def _combine(sections: list[dict[str, Any]]) -> dict[str, Any]:
    if len(sections) == 1:
        return sections[0]
    first = sections[0].copy()
    first["title"] = " / ".join(str(s.get("title") or "") for s in sections)
    first["end_line"] = sections[-1].get("end_line") or sections[-1].get("line_end")
    first["line_end"] = first["end_line"]
    first["char_count"] = sum(_int(s.get("char_count")) for s in sections)
    first["token_count"] = sum(_int(s.get("token_count")) for s in sections)
    return first


def _child_headings(
    section: dict[str, Any],
    outline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    start = _int(section.get("start_line") or section.get("line_start"))
    end = _int(section.get("end_line") or section.get("line_end"))
    inside = [
        item for item in outline
        if start < _int(item.get("line_start")) <= end
    ]
    if not inside:
        return []
    child_level = min(_int(item.get("level"), 1) for item in inside)
    children = [item for item in inside if _int(item.get("level"), 1) == child_level]
    if len(children) >= 2:
        return children
    deeper = [item for item in inside if _int(item.get("level"), 1) > child_level]
    if not deeper:
        return children
    deeper_level = min(_int(item.get("level"), 1) for item in deeper)
    return [item for item in deeper if _int(item.get("level"), 1) == deeper_level]


def _merge_small_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not sections:
        return []
    merged: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    def append_into(prev: dict[str, Any], sec: dict[str, Any]) -> None:
        prev["title"] = f"{prev.get('title', '')} / {sec.get('title', '')}".strip(" /")
        prev["end_line"] = sec.get("end_line") or sec.get("line_end")
        prev["line_end"] = prev["end_line"]
        prev["char_count"] = _int(prev.get("char_count")) + _int(sec.get("char_count"))
        prev["token_count"] = _int(prev.get("token_count")) + _int(sec.get("token_count"))

    def flush_pending(target: dict[str, Any]) -> list[dict[str, Any]]:
        if not pending:
            return []
        target_parent = target.get("parent")
        if target_parent and any(p.get("parent") and p.get("parent") != target_parent for p in pending):
            leftovers = list(pending)
            pending.clear()
            return leftovers
        if not target_parent and any(p.get("parent") for p in pending):
            leftovers = list(pending)
            pending.clear()
            return leftovers
        target_tokens = _int(target.get("token_count"))
        if target_tokens >= SPLIT_THRESHOLD or not merged:
            absorbed = list(pending)
            leftovers: list[dict[str, Any]] = []
        else:
            absorbed = []
            split_idx = len(pending)
            for i in range(len(pending) - 1, -1, -1):
                item = pending[i]
                if target_tokens + _int(item.get("token_count")) <= MERGE_CAP:
                    absorbed.append(item)
                    target_tokens += _int(item.get("token_count"))
                    split_idx = i
                else:
                    break
            absorbed.reverse()
            leftovers = list(pending[:split_idx])
        if absorbed:
            all_sections = absorbed + [target]
            target["title"] = " / ".join(str(s.get("title") or "") for s in all_sections)
            target["start_line"] = all_sections[0].get("start_line") or all_sections[0].get("line_start")
            target["line_start"] = target["start_line"]
            target["char_count"] = sum(_int(s.get("char_count")) for s in all_sections)
            target["token_count"] = sum(_int(s.get("token_count")) for s in all_sections)
        pending.clear()
        return leftovers

    for section in sections:
        tokens = _int(section.get("token_count"))
        if tokens >= MERGE_THRESHOLD:
            merged.extend(flush_pending(section))
            merged.append(section)
        elif (
            merged
            and section.get("parent")
            and section.get("parent") == merged[-1].get("parent")
            and _int(merged[-1].get("token_count")) + tokens <= MERGE_CAP
        ):
            append_into(merged[-1], section)
        else:
            pending.append(section)

    if pending:
        if merged:
            last = merged[-1]
            for item in pending:
                if _int(last.get("token_count")) >= SPLIT_THRESHOLD or (
                    _int(last.get("token_count")) + _int(item.get("token_count")) <= MERGE_CAP
                ):
                    append_into(last, item)
                else:
                    merged.append(item)
                    last = item
        else:
            combined = pending[0].copy()
            for item in pending[1:]:
                if _int(combined.get("token_count")) + _int(item.get("token_count")) <= MERGE_CAP:
                    append_into(combined, item)
                else:
                    merged.append(combined)
                    combined = item.copy()
            merged.append(combined)
    return merged


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
