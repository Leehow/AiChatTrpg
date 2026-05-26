"""Stage-0 source separation for uploaded rulebooks.

This pass is deliberately conservative and heading-driven. Its job is to
remove bundled adventures/scenarios from the resident source and move obvious
catalog-like rule data into a separate parameter-source view that Stage 5 can
still query by original line hints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from agents.trpg.rule_parser_v6.preprocess import make_lined_view


@dataclass(frozen=True)
class SourceSection:
    kind: str
    title: str
    start_line: int
    end_line: int
    chars: int
    family_id: str = ""


@dataclass(frozen=True)
class FilteredRulesetSource:
    main_markdown: str
    parameter_lined_view: str
    parameter_raw_lines: list[str]
    dropped_sections: list[SourceSection]
    parameter_sections: list[SourceSection]
    original_chars: int
    original_lines: int
    main_chars: int
    dropped_chars: int
    parameter_chars: int


@dataclass(frozen=True)
class _Heading:
    line_no: int
    level: int
    title: str


def filter_ruleset_source(markdown: str) -> FilteredRulesetSource:
    lines = markdown.splitlines()
    headings = _headings(lines)
    dropped = _dropped_sections(lines, headings)
    parameter_sections = _parameter_sections(lines, headings, dropped)

    dropped_ranges = [(s.start_line, s.end_line) for s in dropped]
    parameter_ranges = [(s.start_line, s.end_line) for s in parameter_sections]

    main_lines = _build_main_lines(lines, dropped, parameter_sections)
    parameter_raw = _build_parameter_raw_lines(lines, parameter_sections)
    parameter_lined, _ = make_lined_view("\n".join(parameter_raw))
    main = "\n".join(main_lines).strip()

    return FilteredRulesetSource(
        main_markdown=main,
        parameter_lined_view=parameter_lined,
        parameter_raw_lines=parameter_raw,
        dropped_sections=dropped,
        parameter_sections=parameter_sections,
        original_chars=len(markdown),
        original_lines=len(lines),
        main_chars=len(main),
        dropped_chars=_range_chars(lines, dropped_ranges),
        parameter_chars=_range_chars(lines, parameter_ranges),
    )


def _headings(lines: list[str]) -> list[_Heading]:
    out: list[_Heading] = []
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", stripped)
        if match:
            out.append(_Heading(idx, len(match.group(1)), match.group(2).strip()))
    return out


def _dropped_sections(
    lines: list[str],
    headings: list[_Heading],
) -> list[SourceSection]:
    out: list[SourceSection] = []
    for idx, heading in enumerate(headings):
        title_norm = _norm(heading.title)
        if heading.level == 1 and title_norm in {
            "cover",
            "title page",
            "copyright",
        }:
            end = _next_heading_line(headings, idx, max_level=1, default=len(lines) + 1) - 1
            out.append(_section(lines, "front_matter", heading.title, heading.line_no, end))
            continue
        if heading.level == 1 and _is_scenario_heading(title_norm):
            end = _next_heading_line(headings, idx, max_level=1, default=len(lines) + 1) - 1
            out.append(_section(lines, "bundled_scenario", heading.title, heading.line_no, end))
            continue
        if heading.level == 1 and title_norm == "index":
            end = _index_end_line(headings, idx, default=len(lines) + 1) - 1
            out.append(_section(lines, "index", heading.title, heading.line_no, end))
    return _merge_sections(out)


def _parameter_sections(
    lines: list[str],
    headings: list[_Heading],
    dropped: list[SourceSection],
) -> list[SourceSection]:
    out: list[SourceSection] = []
    for idx, heading in enumerate(headings):
        title_norm = _norm(heading.title)
        family_id = _family_for_heading(title_norm, heading.level)
        if not family_id:
            continue
        max_level = 1 if heading.level == 1 or family_id in {
            "mythos_tomes",
            "spells",
        } else 2
        end = _next_heading_line(headings, idx, max_level=max_level, default=len(lines) + 1) - 1
        section = _section(
            lines,
            "parameter_family",
            heading.title,
            heading.line_no,
            end,
            family_id=family_id,
        )
        if any(_overlaps(section, drop) for drop in dropped):
            continue
        out.append(section)
    return _merge_sections(out)


def _family_for_heading(title_norm: str, level: int) -> str:
    exact = {
        "sample occupations": "occupations",
        "skill list": "skills",
        "sample phobias": "phobias",
        "samples manias": "manias",
        "a note about the entries": "mythos_tomes",
        "the grimoire": "spells",
        "equipment - 1920s": "equipment_1920s",
        "equipment - modern era": "equipment_modern",
        "weapons table": "weapons",
        "section one: mythos monsters": "mythos_monsters",
        "section two: deities of the mythos": "mythos_deities",
        "section three: traditional horrors": "traditional_horrors",
        "section four: beasts": "beasts",
    }
    if title_norm in exact:
        return exact[title_norm]
    if level == 1 and "artifacts and alien devices" in title_norm:
        return "artifacts"
    return ""


def _build_main_lines(
    lines: list[str],
    dropped: list[SourceSection],
    parameter_sections: list[SourceSection],
) -> list[str]:
    starts: dict[int, SourceSection] = {
        s.start_line: s for s in [*dropped, *parameter_sections]
    }
    dropped_ranges = [(s.start_line, s.end_line) for s in dropped]
    parameter_ranges = [(s.start_line, s.end_line) for s in parameter_sections]

    out: list[str] = []
    for idx, line in enumerate(lines, start=1):
        section = starts.get(idx)
        if section:
            out.extend(_stub_for_section(section))
        if _in_ranges(idx, dropped_ranges) or _in_ranges(idx, parameter_ranges):
            continue
        out.append(line)
    return out


def _build_parameter_raw_lines(
    lines: list[str],
    parameter_sections: list[SourceSection],
) -> list[str]:
    ranges = [(s.start_line, s.end_line) for s in parameter_sections]
    labels = {s.start_line: s for s in parameter_sections}
    out: list[str] = []
    for idx, line in enumerate(lines, start=1):
        section = labels.get(idx)
        if section:
            out.append(
                f"# Parameter family source: {section.family_id} "
                f"({section.title}; original lines "
                f"{section.start_line}-{section.end_line})",
            )
            continue
        out.append(line if _in_ranges(idx, ranges) else "")
    return out


def _stub_for_section(section: SourceSection) -> list[str]:
    if section.kind == "parameter_family":
        return [
            "",
            f"## Parameter Family Source: {section.title}",
            f"- family_id: {section.family_id}",
            f"- original_line_hints: [[{section.start_line}, {section.end_line}]]",
            "- handling: Keep this catalog/table out of resident core. "
            "Discovery should create a parameter_families entry using the "
            "line hints above; Stage 5 can extract exact entries from the "
            "separate parameter source.",
            "",
        ]
    return [
        "",
        f"## Removed Built-In Scenario/Non-Rule Section: {section.title}",
        f"- original_lines: {section.start_line}-{section.end_line}",
        "- handling: Excluded from ruleset parsing because it is bundled "
        "scenario, index, or front matter rather than reusable system rules.",
        "",
    ]


def _is_scenario_heading(title_norm: str) -> bool:
    if "creating scenarios" in title_norm or "converting scenarios" in title_norm:
        return False
    return (
        title_norm.endswith("scenario")
        or title_norm.endswith("scenarios")
        or title_norm.startswith("chapter fifteen: scenarios")
        or "adventure" in title_norm
    )


def _index_end_line(
    headings: list[_Heading],
    idx: int,
    *,
    default: int,
) -> int:
    for nxt in headings[idx + 1:]:
        norm = _norm(nxt.title)
        if nxt.level == 1:
            return nxt.line_no
        if "investigator sheet" in norm:
            return nxt.line_no
    return default


def _next_heading_line(
    headings: list[_Heading],
    idx: int,
    *,
    max_level: int,
    default: int,
) -> int:
    for nxt in headings[idx + 1:]:
        if nxt.level <= max_level:
            return nxt.line_no
    return default


def _section(
    lines: list[str],
    kind: str,
    title: str,
    start: int,
    end: int,
    *,
    family_id: str = "",
) -> SourceSection:
    end = max(start, min(end, len(lines)))
    return SourceSection(kind, title, start, end, _range_chars(lines, [(start, end)]), family_id)


def _merge_sections(sections: Iterable[SourceSection]) -> list[SourceSection]:
    ordered = sorted(sections, key=lambda s: (s.start_line, s.end_line))
    out: list[SourceSection] = []
    for section in ordered:
        if out and section.start_line <= out[-1].end_line:
            prev = out[-1]
            out[-1] = SourceSection(
                prev.kind,
                prev.title,
                prev.start_line,
                max(prev.end_line, section.end_line),
                prev.chars + section.chars,
                prev.family_id,
            )
        else:
            out.append(section)
    return out


def _overlaps(a: SourceSection, b: SourceSection) -> bool:
    return a.start_line <= b.end_line and b.start_line <= a.end_line


def _in_ranges(line_no: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= line_no <= end for start, end in ranges)


def _range_chars(lines: list[str], ranges: list[tuple[int, int]]) -> int:
    total = 0
    for start, end in ranges:
        total += sum(len(line) + 1 for line in lines[max(0, start - 1):end])
    return total


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())
