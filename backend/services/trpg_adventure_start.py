"""Adventure start selection and initial runtime state.

ChatLab starts play by asking the player which playable unit (location,
mission, or chapter) should be loaded, then writes that unit into active
module memory before IC turns begin. ChatRPG keeps this lighter: one selected
unit becomes the current scene, active module chapter, and optional initial NPC
roster.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from orm.models import GameSession, ParsedModule
from services.module_semantic_shape import slice_by_line
from services.trpg_npc.psychology import ensure_npc_psychology
from services.trpg_npc.visibility import ensure_npc_visibility_fields

MAX_ACTIVE_MODULE_CHARS = 32000
MAX_INITIAL_NPCS = 8


def build_adventure_start_options(module: ParsedModule | None) -> dict[str, Any]:
    if module is None:
        return {
            "has_module": False,
            "module_id": None,
            "module_title": "",
            "semantic_status": "",
            "semantic_error": "",
            "anchor_type": "freeform",
            "progression": "freeform",
            "selection_rule": "",
            "needs_selection": False,
            "units": [],
        }

    structure = _as_dict(module.semantic_structure)
    units = _normalise_units(structure, module)
    return {
        "has_module": True,
        "module_id": str(module.id),
        "module_title": _module_title(module),
        "semantic_status": str(module.semantic_status or ""),
        "semantic_error": str(module.semantic_error or ""),
        "anchor_type": str(structure.get("anchor_type") or structure.get("type") or "chapter"),
        "progression": str(structure.get("progression") or ""),
        "selection_rule": str(structure.get("selection_rule") or ""),
        "needs_selection": len(units) > 1,
        "units": units,
    }


def activate_adventure_start(
    session: GameSession,
    module: ParsedModule | None,
    *,
    unit_index: int | None = None,
    unit_id: str | None = None,
) -> dict[str, Any]:
    """Mutate session runtime state for the selected adventure start.

    Caller owns commit/refresh. Returns a compact summary for tests/API logs.
    """
    setup = dict(session.setup_state) if isinstance(session.setup_state, dict) else {}

    if module is None:
        setup["completed"] = True
        setup["step"] = 2
        setup["start_unit_index"] = None
        setup["start_unit_id"] = None
        setup["start_unit_title"] = None
        session.setup_state = setup
        flag_modified(session, "setup_state")
        module_state = (
            dict(session.module_state)
            if isinstance(session.module_state, dict) else {}
        )
        module_state.setdefault("day_count", 1)
        module_state.setdefault("in_game_time", "09:00")
        session.module_state = module_state
        flag_modified(session, "module_state")
        _ensure_base_memory(session)
        return {"mode": "freeform", "scene": "", "npc_count": 0}

    options = build_adventure_start_options(module)
    units = list(options.get("units") or [])
    selected = _select_unit(units, unit_index=unit_index, unit_id=unit_id)
    if selected is None:
        selected = _whole_module_unit(module)

    title = str(selected.get("title") or options.get("module_title") or "Opening")
    unit_idx = int(selected.get("index") or 0)
    unit_key = str(selected.get("unit_id") or f"unit_{unit_idx}")
    scene_key = _scene_key(title, unit_idx)
    raw_content = _unit_text(module, selected)
    summary = str(selected.get("summary") or "").strip()
    module_title = str(options.get("module_title") or _module_title(module))
    kind = str(selected.get("kind") or selected.get("type") or options.get("anchor_type") or "chapter")

    module_state = (
        dict(session.module_state)
        if isinstance(session.module_state, dict) else {}
    )
    module_state.update({
        "tag": kind,
        "title": module_title,
        "scene": scene_key,
        "scene_name": title,
        "scene_name_for": scene_key,
        "scene_reason": "adventure_start",
        "desc": summary or title,
        "progress": module_state.get("progress") or [False, False, False, False, False],
        "active_module_content": {
            "module_id": str(module.id),
            "module_title": module_title,
            "unit_index": unit_idx,
            "unit_id": unit_key,
            "unit_title": title,
            "kind": kind,
            "summary": summary,
            "line_start": selected.get("line_start") or selected.get("start_line") or 0,
            "line_end": selected.get("line_end") or selected.get("end_line") or 0,
            "selection_rule": options.get("selection_rule") or "",
            "briefing_md": str(module.briefing_md or ""),
            "raw_content": raw_content,
        },
    })
    module_state.setdefault("day_count", 1)
    module_state.setdefault("in_game_time", "09:00")
    if summary and not module_state.get("objective"):
        module_state["objective"] = _first_sentence(summary)
    session.module_state = module_state
    flag_modified(session, "module_state")

    mem = (
        dict(session.memory_state)
        if isinstance(session.memory_state, dict) else {}
    )
    _ensure_memory_buckets(mem)
    mem["current_scene"] = scene_key
    _merge_scene(mem, {
        "key": scene_key,
        "name": title,
        "description": summary,
        "module_id": str(module.id),
        "module_title": module_title,
        "unit_id": unit_key,
        "unit_index": unit_idx,
        "kind": kind,
        "status": "current",
    })
    _merge_world_fact(mem, {
        "key": "adventure_start",
        "module_id": str(module.id),
        "module_title": module_title,
        "scene": scene_key,
        "scene_name": title,
        "unit_id": unit_key,
        "unit_index": unit_idx,
    })
    initial_npcs = _initial_npcs(module, raw_content, scene_key, unit_key)
    npc_count = _merge_npcs(mem, initial_npcs)
    session.memory_state = mem
    flag_modified(session, "memory_state")

    setup.update({
        "completed": True,
        "step": 2,
        "module_id": str(module.id),
        "module_title": module_title,
        "start_unit_index": unit_idx,
        "start_unit_id": unit_key,
        "start_unit_title": title,
    })
    session.setup_state = setup
    flag_modified(session, "setup_state")
    return {"mode": "module", "scene": scene_key, "npc_count": npc_count}


def active_module_chapter_from_state(module_state: dict[str, Any]) -> tuple[str, str]:
    amc = _as_dict(module_state.get("active_module_content"))
    if not amc:
        return "", ""
    name = str(
        amc.get("unit_title")
        or amc.get("section_title")
        or amc.get("module_title")
        or ""
    ).strip()
    text = str(amc.get("raw_content") or amc.get("briefing_md") or "").strip()
    return name, text


def _normalise_units(
    structure: dict[str, Any],
    module: ParsedModule,
) -> list[dict[str, Any]]:
    raw_units = structure.get("playable_units")
    if not isinstance(raw_units, list) or not raw_units:
        raw_units = structure.get("playable")
    if not isinstance(raw_units, list):
        raw_units = []

    out: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_units):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("name") or f"Unit {idx + 1}").strip()
        if not title:
            continue
        start = _int(raw.get("line_start") or raw.get("start_line"))
        end = _int(raw.get("line_end") or raw.get("end_line"))
        kind = str(raw.get("kind") or raw.get("type") or structure.get("anchor_type") or "chapter")
        out.append({
            "index": idx,
            "unit_id": str(raw.get("unit_id") or f"u{idx + 1}"),
            "title": title,
            "kind": kind,
            "summary": str(raw.get("summary") or ""),
            "line_start": start,
            "line_end": end,
            "section_indexes": raw.get("section_indexes") if isinstance(raw.get("section_indexes"), list) else [],
        })
    if out:
        return out
    return [_whole_module_unit(module)]


def _whole_module_unit(module: ParsedModule) -> dict[str, Any]:
    return {
        "index": 0,
        "unit_id": "whole_module",
        "title": _module_title(module) or "Opening",
        "kind": "chapter",
        "summary": str(module.briefing_md or "")[:240],
        "line_start": 1,
        "line_end": len(str(module.markdown or "").splitlines()),
        "section_indexes": [],
    }


def _select_unit(
    units: list[dict[str, Any]],
    *,
    unit_index: int | None,
    unit_id: str | None,
) -> dict[str, Any] | None:
    if unit_id:
        for unit in units:
            if str(unit.get("unit_id") or "") == unit_id:
                return unit
    if unit_index is not None:
        for unit in units:
            if int(unit.get("index") or 0) == int(unit_index):
                return unit
    if len(units) == 1:
        return units[0]
    return None


def _unit_text(module: ParsedModule, unit: dict[str, Any]) -> str:
    start = _int(unit.get("line_start") or unit.get("start_line"))
    end = _int(unit.get("line_end") or unit.get("end_line"))
    text = slice_by_line(str(module.markdown or ""), start, end)
    if not text:
        text = str(module.briefing_md or module.markdown or "")
    text = text.strip()
    if len(text) <= MAX_ACTIVE_MODULE_CHARS:
        return text
    return text[:MAX_ACTIVE_MODULE_CHARS].rstrip() + "\n\n[Active module content truncated for prompt budget.]"


def _initial_npcs(
    module: ParsedModule,
    active_text: str,
    scene_key: str,
    unit_id: str,
) -> list[dict[str, Any]]:
    structure = _as_dict(module.semantic_structure)
    candidates: list[dict[str, Any]] = []
    for raw in _as_list(structure.get("npc_cards")):
        npc = _npc_from_card(raw, module, scene_key, unit_id)
        if npc:
            candidates.append(npc)

    entries = _as_list(_as_dict(module.appendix_index).get("entries"))
    if not entries:
        entries = _as_list(structure.get("appendix_index"))

    active_lower = active_text.lower()
    matched: list[dict[str, Any]] = []
    fallback: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or entry.get("title") or "").strip()
        if not name:
            continue
        typ = str(entry.get("type") or entry.get("category") or "").lower()
        if typ not in {"npc", "monster", "character"} and not _looks_like_npc_entry(name, entry):
            continue
        npc = _npc_from_entry(entry, module, scene_key, unit_id)
        if not npc:
            continue
        if name.lower() in active_lower:
            matched.append(npc)
        else:
            fallback.append(npc)

    primary = [*candidates, *matched]
    source = primary if primary else fallback
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for npc in source:
        key = str(npc.get("key") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(npc)
        if len(out) >= MAX_INITIAL_NPCS:
            break
    return out


def _npc_from_card(
    raw: Any,
    module: ParsedModule,
    scene_key: str,
    unit_id: str,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or raw.get("display_name") or "").strip()
    if not name:
        return None
    summary = str(raw.get("summary") or raw.get("brief") or raw.get("description") or "").strip()
    return _npc_payload(name, summary, module, scene_key, unit_id, raw)


def _npc_from_entry(
    entry: dict[str, Any],
    module: ParsedModule,
    scene_key: str,
    unit_id: str,
) -> dict[str, Any] | None:
    name = str(entry.get("name") or entry.get("title") or "").strip()
    if not name:
        return None
    summary = str(entry.get("brief") or entry.get("summary") or entry.get("stats_summary") or "").strip()
    return _npc_payload(name, summary, module, scene_key, unit_id, entry)


def _npc_payload(
    name: str,
    summary: str,
    module: ParsedModule,
    scene_key: str,
    unit_id: str,
    raw: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    key = str(raw.get("key") or raw.get("id") or _slug_key(name, "npc"))
    payload = {
        "key": key,
        "name": name,
        "summary": summary,
        "source": "module_start",
        "module_id": str(module.id),
        "unit_id": unit_id,
        "last_seen_scene": scene_key,
        "last_seen_at": now,
        "portrait_prompt": str(raw.get("portrait_prompt") or raw.get("appearance") or "")[:500],
    }
    for field in (
        "gender",
        "age",
        "role",
        "title",
        "appearance",
        "description",
        "voice_hint",
        "personality",
        "aliases",
        "abilities",
        "motivation",
        "dialogue_style",
        # LLM-supplied psychology hints from the module card extractor —
        # let `ensure_npc_psychology` pick them up instead of regenerating
        # via regex.
        "llm_relationship_hint",
        "player_interest",
        "interest_drive",
        "emotional_state",
        "secret_agenda",
        "interaction_goals",
    ):
        value = raw.get(field)
        if value not in (None, "", []):
            payload[field] = value

    # Mechanical stats from the module's NPC card. When present these
    # replace the LLM-generated fallback in `_seed_npc_params`, since the
    # module author already wrote authoritative numbers. We accept either
    # `params` (already-normalised) or `stats` (chatlab card field).
    module_params = raw.get("params") or raw.get("stats")
    if isinstance(module_params, dict) and module_params:
        payload["params"] = dict(module_params)
        context = str(raw.get("params_context") or raw.get("stats_context") or "").strip()
        if not context:
            context = "from module appendix"
        payload["params_context"] = context

    # Adventure-start NPCs are encounter NPCs — the player has not yet
    # learned their true name, so default to a description-based public
    # label until the GM emits a reveal marker.
    ensure_npc_visibility_fields(payload, default_revealed=False)
    # Seed inner_state + player_knowledge so the GM voicing prompt has
    # motivation / mood / interest_drive to honour from turn one. The PC
    # display-name fact is only relevant for preexisting bonds, which
    # encounter NPCs aren't, so skipping the pc kwarg is fine.
    ensure_npc_psychology(payload)
    return payload


def _merge_scene(mem: dict[str, Any], scene: dict[str, Any]) -> None:
    scenes = mem.get("scenes")
    if not isinstance(scenes, list):
        scenes = []
    for existing in scenes:
        if isinstance(existing, dict) and existing.get("key") == scene["key"]:
            existing.update({k: v for k, v in scene.items() if v not in ("", None)})
            mem["scenes"] = scenes
            return
    scenes.append(scene)
    mem["scenes"] = scenes


def _merge_world_fact(mem: dict[str, Any], fact: dict[str, Any]) -> None:
    facts = mem.get("world_facts")
    if isinstance(facts, dict):
        facts.update({
            "current_scene": fact["scene"],
            "current_scene_name": fact["scene_name"],
            "module_title": fact["module_title"],
        })
        mem["world_facts"] = facts
        return
    if not isinstance(facts, list):
        facts = []
    key = fact.get("key")
    for existing in facts:
        if isinstance(existing, dict) and existing.get("key") == key:
            existing.update(fact)
            mem["world_facts"] = facts
            return
    facts.append(fact)
    mem["world_facts"] = facts


def _merge_npcs(mem: dict[str, Any], incoming: list[dict[str, Any]]) -> int:
    npcs = mem.get("npcs")
    if not isinstance(npcs, list):
        npcs = []
    by_key = {
        str(npc.get("key")): npc
        for npc in npcs
        if isinstance(npc, dict) and npc.get("key")
    }
    added = 0
    for npc in incoming:
        key = str(npc.get("key") or "")
        if not key:
            continue
        if key in by_key:
            by_key[key].update({k: v for k, v in npc.items() if v not in ("", None)})
            continue
        npcs.append(npc)
        by_key[key] = npc
        added += 1
    mem["npcs"] = npcs
    return added


def _ensure_base_memory(session: GameSession) -> None:
    mem = dict(session.memory_state) if isinstance(session.memory_state, dict) else {}
    _ensure_memory_buckets(mem)
    session.memory_state = mem
    flag_modified(session, "memory_state")


def _ensure_memory_buckets(mem: dict[str, Any]) -> None:
    for key in ("scenes", "npcs", "plot_threads", "world_facts"):
        mem.setdefault(key, [])


def _module_title(module: ParsedModule) -> str:
    cached = str(getattr(module, "extracted_title", "") or "").strip()
    if cached:
        return cached
    filename = str(getattr(module, "filename", "") or "").strip()
    return Path(filename).stem if filename else "Module"


def _scene_key(title: str, index: int) -> str:
    return _slug_key(title, f"scene_{index + 1}")


def _slug_key(text: str, fallback_prefix: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    if words:
        return "_".join(words[:5])[:48]
    digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:8]
    return f"{fallback_prefix}_{digest}"


def _looks_like_npc_entry(name: str, entry: dict[str, Any]) -> bool:
    text = f"{name} {entry.get('brief') or ''} {entry.get('summary') or ''}"
    return bool(re.search(r"(npc|人物|角色|怪物|敌人|守卫|老人|女人|男人|少女|少年)", text, re.I))


def _first_sentence(text: str) -> str:
    clean = " ".join(str(text or "").split())
    if not clean:
        return ""
    match = re.split(r"(?<=[。.!?！？])\s*", clean, maxsplit=1)
    return (match[0] if match else clean)[:180]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
