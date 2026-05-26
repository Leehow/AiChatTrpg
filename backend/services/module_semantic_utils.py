"""Utility helpers for module semantic parsing."""

from __future__ import annotations

import re
from typing import Any

from services.module_semantic_profile import (
    clean_title_hint,
    classify_title,
    doc_profile,
    guess_title,
    is_bad_title,
    major_outline,
)
from services.module_semantic_shape import (
    derive_global_refs,
    derive_playable_units,
    estimate_tokens,
    infer_anchor_type,
    module_type,
    normalize_sections,
    quick_guide,
    range_char_count,
    rebalance_playable,
    selection_rule,
    slice_by_line,
    split_oversized_by_outline,
    split_structure_packs,
)

MAX_OUTLINE_ITEMS = 120
MAX_PREVIEW_CHARS = 420
MAX_BRIEFING_CHARS = 16000
MAX_APPENDIX_CHARS = 16000


def build_outline(markdown: str, toc: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines = markdown.splitlines()
    if not toc:
        return _fallback_outline(lines)
    raw: list[dict[str, Any]] = []
    for item in toc:
        start = _int(item.get("line_start"))
        if start <= 0:
            continue
        raw.append(
            {
                "title": str(item.get("title") or "").strip(),
                "level": _int(item.get("level"), 1),
                "line_start": start,
            }
        )
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(raw):
        start = _int(item.get("line_start"))
        level = _int(item.get("level"), 1)
        next_start = 0
        for later in raw[idx + 1:]:
            if _int(later.get("level"), 1) <= level:
                next_start = _int(later.get("line_start"))
                break
        end = next_start - 1 if next_start else len(lines)
        out.append({**item, "line_end": end, "preview": _slice_lines(lines, start, end, MAX_PREVIEW_CHARS)})
    return out or _fallback_outline(lines)


def heuristic_structure(
    markdown: str,
    outline: list[dict[str, Any]],
    title_hint: str = "",
) -> dict[str, Any]:
    sections = []
    for item in major_outline(outline):
        section_type = classify_title(str(item.get("title", "")))
        line_start = item.get("line_start", 0)
        line_end = item.get("line_end", 0)
        sections.append(
            {
                "title": item.get("title", ""),
                "type": section_type,
                "summary": _first_sentence(str(item.get("preview", ""))),
                "line_start": line_start,
                "line_end": line_end,
                "start_line": line_start,
                "end_line": line_end,
                "char_count": max(0, range_char_count(markdown, line_start, line_end)),
                "token_count": estimate_tokens(slice_by_line(markdown, line_start, line_end)),
            }
        )
    anchor_type = infer_anchor_type(sections)
    progression = "sandbox" if anchor_type == "location" else "linear"
    packs = split_structure_packs(sections)
    split_playable = split_oversized_by_outline(markdown, packs["playable"], outline)
    playable = rebalance_playable(split_playable)
    playable_units = derive_playable_units(playable, sections)
    global_refs = derive_global_refs(sections)
    return {
        "type": module_type(anchor_type),
        "title": clean_title_hint(title_hint) or guess_title(markdown, outline),
        "connection": "standalone" if progression == "sandbox" else "sequential",
        "anchor_type": anchor_type,
        "progression": progression,
        "guide": quick_guide(sections),
        "selection_rule": selection_rule(playable) if progression == "sandbox" else "",
        "sections": sections,
        "packs": packs,
        "playable": playable,
        "playable_units": playable_units[:24],
        "global_refs": global_refs,
    }


def normalize_structure(
    structure: dict[str, Any],
    outline: list[dict[str, Any]],
    title_hint: str = "",
) -> dict[str, Any]:
    fallback = heuristic_structure("", outline, title_hint)
    provided_type = structure.get("type")
    provided_connection = structure.get("connection")
    for key, value in fallback.items():
        structure.setdefault(key, value)
    if not isinstance(structure.get("sections"), list):
        structure["sections"] = fallback["sections"]
    structure["sections"] = normalize_sections(structure["sections"], fallback["sections"])
    anchor = str(structure.get("anchor_type") or "").strip() or infer_anchor_type(structure["sections"])
    progression = structure.get("progression")
    if progression not in {"linear", "sandbox"}:
        progression = "sandbox" if anchor == "location" else "linear"
    structure["anchor_type"] = anchor
    structure["progression"] = progression
    if provided_type not in {"mission", "chapter", "sandbox"}:
        structure["type"] = module_type(anchor)
    if provided_connection not in {"sequential", "branching", "standalone"}:
        structure["connection"] = "standalone" if progression == "sandbox" else "sequential"
    packs = split_structure_packs(structure["sections"])
    structure["packs"] = structure.get("packs") if isinstance(structure.get("packs"), dict) else packs
    playable = structure.get("playable")
    if not isinstance(playable, list):
        playable = rebalance_playable(packs["playable"])
    structure["playable"] = playable
    if not isinstance(structure.get("playable_units"), list):
        structure["playable_units"] = derive_playable_units(playable, structure["sections"])[:24]
    if not isinstance(structure.get("global_refs"), list):
        structure["global_refs"] = derive_global_refs(structure["sections"])
    structure["guide"] = str(structure.get("guide") or "").strip() or quick_guide(structure["sections"])
    if is_bad_title(str(structure.get("title") or "")) and title_hint:
        structure["title"] = clean_title_hint(title_hint)
    if progression == "sandbox":
        structure["selection_rule"] = str(structure.get("selection_rule") or "").strip() or selection_rule(playable)
    else:
        structure["selection_rule"] = ""
    return structure


def supporting_text(
    markdown: str,
    outline: list[dict[str, Any]],
    structure: dict[str, Any],
    max_chars: int,
) -> str:
    lines = markdown.splitlines()
    packs = structure.get("packs") if isinstance(structure.get("packs"), dict) else {}
    feed = list(packs.get("other", []))
    feed.extend(
        s for s in packs.get("appendix", [])
        if isinstance(s, dict) and s.get("type") in {"appendix_rules", "appendix_others"}
    )
    if not feed:
        feed = outline[:8]
    wanted = [(_int(i.get("line_start") or i.get("start_line")), _int(i.get("line_end") or i.get("end_line"))) for i in feed]
    return _collect_ranges(lines, wanted, max_chars)


def appendix_text(
    markdown: str,
    outline: list[dict[str, Any]],
    structure: dict[str, Any],
    max_chars: int,
) -> str:
    lines = markdown.splitlines()
    wanted = []
    packs = structure.get("packs") if isinstance(structure.get("packs"), dict) else {}
    for ref in packs.get("appendix", []):
        if isinstance(ref, dict) and ref.get("type") in {"appendix", "appendix_list", "npc_list"}:
            wanted.append((_int(ref.get("line_start") or ref.get("start_line")), _int(ref.get("line_end") or ref.get("end_line"))))
    if not wanted:
        for item in outline:
            if classify_title(str(item.get("title", ""))) in {"appendix_others", "appendix_list", "npc_list", "rules"}:
                wanted.append((_int(item.get("line_start")), _int(item.get("line_end"))))
    return _collect_ranges(lines, wanted, max_chars)


def heuristic_appendix(
    markdown: str,
    outline: list[dict[str, Any]],
    structure: dict[str, Any],
) -> dict[str, Any]:
    text = appendix_text(markdown, outline, structure, MAX_APPENDIX_CHARS)
    entries: list[dict[str, Any]] = []
    for line_no, line in _numbered_lines(text):
        clean = line.strip(" -*\t")
        if not clean or len(clean) > 120:
            continue
        match = re.match(r"^([\w一-鿿·'\"“”《》:： -]{2,40})[:：-]\s*(.+)$", clean)
        if not match:
            continue
        name = match.group(1).strip(" “”\"'")
        brief = match.group(2).strip()
        if not name or not brief:
            continue
        entries.append(
            {
                "name": name,
                "category": "appendix",
                "type": _entry_type(name + " " + brief),
                "brief": brief[:240],
                "stats_summary": "",
                "line": line_no,
            }
        )
        if len(entries) >= 80:
            break
    categories = [{"name": "appendix", "count": len(entries)}] if entries else []
    return {"categories": categories, "entries": entries}


def fallback_briefing(structure: dict[str, Any]) -> str:
    title = structure.get("title") or "Untitled module"
    lines = [f"# {title}", "", "## Structure"]
    for unit in structure.get("playable_units", [])[:12]:
        if isinstance(unit, dict):
            lines.append(f"- {unit.get('title', 'Untitled')}: {unit.get('summary', '')}")
    refs = structure.get("global_refs", [])
    if refs:
        lines.extend(["", "## Global References"])
        for ref in refs[:12]:
            if isinstance(ref, dict):
                lines.append(f"- {ref.get('title', 'Untitled')}: {ref.get('summary', '')}")
    return "\n".join(lines)


def step(
    stage: str,
    status: str,
    summary: str,
    output: dict[str, Any],
) -> dict[str, Any]:
    return {"stage": stage, "status": status, "summary": summary, "output": output}


def structure_pipeline_steps(
    structure: dict[str, Any],
    source: str,
    rebalance_logs: list[str] | None = None,
) -> list[dict[str, Any]]:
    sections = structure.get("sections", [])
    packs = structure.get("packs", {})
    playable = structure.get("playable", [])
    return [
        step(
            "2.1_structure",
            "done",
            f"{len(sections) if isinstance(sections, list) else 0} sections, anchor {structure.get('anchor_type')}, progression {structure.get('progression')}",
            {"source": source, "structure": {k: v for k, v in structure.items() if k not in {"packs", "playable", "playable_units", "global_refs"}}},
        ),
        step("2.2_split_packs", "done", _pack_summary(packs), {"packs": packs}),
        step(
            "2.3_playable_rebalance",
            "done",
            f"{len(playable) if isinstance(playable, list) else 0} playable blocks",
            {"playable": playable, "logs": rebalance_logs or []},
        ),
    ]


def _pack_summary(packs: dict[str, Any]) -> str:
    return (
        f"playable {len(packs.get('playable', []))} / "
        f"appendix {len(packs.get('appendix', []))} / "
        f"other {len(packs.get('other', []))}"
    )


def _fallback_outline(lines: list[str]) -> list[dict[str, Any]]:
    total = len(lines)
    if total == 0:
        return []
    step_size = max(1, total // 6)
    out: list[dict[str, Any]] = []
    cursor = 1
    idx = 1
    while cursor <= total and len(out) < 8:
        end = min(total, cursor + step_size - 1)
        out.append(
            {
                "title": f"Part {idx}",
                "level": 1,
                "line_start": cursor,
                "line_end": end,
                "preview": _slice_lines(lines, cursor, end, MAX_PREVIEW_CHARS),
            }
        )
        cursor = end + 1
        idx += 1
    return out


def _slice_lines(lines: list[str], start: int, end: int, max_chars: int) -> str:
    start = max(1, start)
    end = min(len(lines), max(start, end))
    text = "\n".join(lines[start - 1:end]).strip()
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n[...]"
    return text


def _collect_ranges(
    lines: list[str],
    ranges: list[tuple[int, int]],
    max_chars: int,
) -> str:
    out: list[str] = []
    total = 0
    seen: set[tuple[int, int]] = set()
    for start, end in ranges:
        if start <= 0:
            continue
        if end < start:
            end = start
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        chunk = _slice_lines(lines, start, end, max_chars)
        if not chunk:
            continue
        block = f"[lines {start}-{end}]\n{chunk}"
        if total + len(block) + 2 > max_chars:
            remain = max_chars - total
            if remain > 400:
                out.append(block[:remain].rstrip())
            break
        out.append(block)
        total += len(block) + 2
    return "\n\n".join(out)


def _entry_type(text: str) -> str:
    low = text.lower()
    if any(x in low for x in ("npc", "人物", "角色", "调查员")):
        return "npc"
    if any(x in low for x in ("monster", "怪物", "敌人")):
        return "monster"
    if any(x in low for x in ("item", "道具", "物品")):
        return "item"
    if any(x in low for x in ("spell", "法术")):
        return "spell"
    if any(x in low for x in ("location", "地点", "场所")):
        return "location"
    if any(x in low for x in ("rule", "规则")):
        return "rule"
    return "other"


def _first_sentence(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return ""
    pieces = re.split(r"(?<=[。.!?！？])\s+", clean, maxsplit=1)
    return pieces[0][:180]


def _numbered_lines(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if re.match(r"^\[lines\s+(\d+)-", line):
            continue
        out.append((idx, line))
    return out


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
