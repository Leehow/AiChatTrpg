"""TTS segment dataclass + speaker parsing + character lookup.

Pure-ish helpers: depend on the text helpers in
`services.trpg_tts_text` plus ORM `GameSession` for session-derived data.
No DB calls, no LLM calls — the caller in `services.trpg_tts` handles
async + provider concerns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from orm.models import GameSession

from services.trpg_tts_text import (
    _QUOTE_WITH_SPEAK_RE,
    _SPEAK_TAG_RE,
    _compact_text,
    _lookup_matches,
    _normalize_lookup,
    _is_pc_speaker,
    _sanitize_speaker_name,
    _sanitize_tts_text,
    _strip_corner_quote_wrapper,
    _truncate_prompt_text,
)


@dataclass
class TtsSegment:
    index: int
    speaker: str
    text: str
    emotion: str = ""
    npc_key: str = ""
    voice: str = ""
    kind: str = "narrator"
    model: str = ""
    provider: str = ""
    performance_notes: str = ""


def _parse_segments(text: str) -> list[TtsSegment]:
    segments: list[TtsSegment] = []
    cursor = 0
    last_speaker = ""
    last_key = ""

    for match in _QUOTE_WITH_SPEAK_RE.finditer(text):
        if match.start() > cursor:
            _append_narrator(segments, text[cursor:match.start()])

        quote = _sanitize_tts_text(match.group(1) or "", keep_speak_tags=False)
        emotion = (match.group(2) or "").strip().lower()
        npc_key = (match.group(3) or "").strip()
        speaker = _sanitize_speaker_name(match.group(4) or "")
        if speaker:
            last_speaker = speaker
            last_key = npc_key
        elif last_speaker:
            speaker = last_speaker
            npc_key = last_key

        if quote:
            if speaker:
                segments.append(
                    TtsSegment(
                        index=0,
                        speaker=speaker,
                        text=quote,
                        emotion=emotion,
                        npc_key=npc_key,
                        kind="dialogue",
                    )
                )
            else:
                _append_narrator(segments, quote)
        cursor = match.end()

    if cursor < len(text):
        _append_narrator(segments, text[cursor:])

    merged: list[TtsSegment] = []
    for seg in segments:
        text_clean = _sanitize_tts_text(_SPEAK_TAG_RE.sub("", seg.text), keep_speak_tags=False)
        if not text_clean:
            continue
        seg.text = text_clean
        if (
            merged
            and seg.kind == "narrator"
            and merged[-1].kind == "narrator"
        ):
            merged[-1].text = _compact_text(f"{merged[-1].text} {seg.text}")
            continue
        merged.append(seg)

    for idx, seg in enumerate(merged, start=1):
        seg.index = idx
    return merged


def _append_narrator(segments: list[TtsSegment], raw: str) -> None:
    text = _sanitize_tts_text(_SPEAK_TAG_RE.sub("", raw or ""), keep_speak_tags=False)
    if text:
        segments.append(TtsSegment(index=0, speaker="narrator", text=text, kind="narrator"))


def _needs_llm_speaker_parse(text: str, segments: list[TtsSegment]) -> bool:
    """Use LLM fallback only when the fixed `「...」[speak]...` contract is missing."""
    if "「" not in (text or "") or "」" not in (text or ""):
        return False
    has_dialogue = any(seg.kind == "dialogue" for seg in segments)
    has_speak = bool(_SPEAK_TAG_RE.search(text or ""))
    return not has_dialogue and not has_speak


def _segments_from_llm_payload(payload: list[Any]) -> list[TtsSegment]:
    out: list[TtsSegment] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        speaker = _sanitize_speaker_name(str(item.get("speaker") or ""))
        text = _sanitize_tts_text(str(item.get("text") or ""), keep_speak_tags=False)
        if not speaker or not text:
            continue
        kind = "narrator" if _normalize_lookup(speaker) == "narrator" else "dialogue"
        if kind == "dialogue":
            text = _strip_corner_quote_wrapper(text)
        out.append(
            TtsSegment(
                index=0,
                speaker="narrator" if kind == "narrator" else speaker,
                npc_key=str(item.get("npc_key") or "").strip(),
                emotion=str(item.get("emotion") or "").strip().lower(),
                text=text,
                kind=kind,
            )
        )
    merged = _merge_adjacent_segments(out)
    for idx, seg in enumerate(merged, start=1):
        seg.index = idx
    return merged


def _merge_adjacent_segments(segments: list[TtsSegment]) -> list[TtsSegment]:
    merged: list[TtsSegment] = []
    for seg in segments:
        if (
            merged
            and merged[-1].speaker == seg.speaker
            and merged[-1].kind == seg.kind
            and merged[-1].emotion == seg.emotion
            and merged[-1].npc_key == seg.npc_key
        ):
            sep = "\n" if seg.kind == "dialogue" else " "
            merged[-1].text = _compact_text(f"{merged[-1].text}{sep}{seg.text}")
        else:
            merged.append(seg)
    return merged


def _session_npcs(session: GameSession) -> list[dict[str, Any]]:
    memory = session.memory_state if isinstance(session.memory_state, dict) else {}
    npcs = memory.get("npcs")
    if not isinstance(npcs, list):
        return []
    return [npc for npc in npcs if isinstance(npc, dict)]


def _find_character_for_segment(
    seg: TtsSegment,
    session: GameSession,
    npcs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if _is_pc_speaker(seg.speaker):
        char = session.character if isinstance(session.character, dict) else {}
        return char or None
    key = _normalize_lookup(seg.npc_key)
    name = _normalize_lookup(seg.speaker)
    for npc in npcs:
        candidates = [
            npc.get("key"),
            npc.get("id"),
            npc.get("name"),
            npc.get("player_known_name"),
            npc.get("public_name"),
            npc.get("display_name"),
        ]
        if key and any(_normalize_lookup(value) == key for value in candidates):
            return npc
        if name and any(_lookup_matches(name, _normalize_lookup(value)) for value in candidates):
            return npc
    return None


def _speaker_parse_roster(session: GameSession) -> dict[str, Any]:
    character = session.character if isinstance(session.character, dict) else {}
    identity = character.get("identity") if isinstance(character.get("identity"), dict) else {}
    pc_name = str(identity.get("name") or character.get("name") or "").strip()
    npcs = []
    for npc in _session_npcs(session):
        npcs.append({
            "key": npc.get("key") or npc.get("id") or "",
            "name": npc.get("name") or "",
            "player_known_name": npc.get("player_known_name") or npc.get("public_name") or "",
            "display_name": npc.get("display_name") or "",
            "gender": npc.get("gender") or "",
            "summary": _truncate_prompt_text(
                " ".join(
                    str(npc.get(k) or "")
                    for k in ("summary", "description", "role", "appearance", "voice_hint")
                ),
                180,
            ),
        })
    return {"pc": {"speaker": "PC", "name": pc_name}, "npcs": npcs}


def _speaker_parse_prompt(text: str, roster: dict[str, Any]) -> str:
    return (
        "Split this GM response into TTS segments.\n"
        "Fixed format contract: ONLY text inside CJK corner brackets 「...」 is spoken dialogue. "
        "Other quote styles are narrator text. For each 「...」 line, infer the speaker from nearby narration "
        "and the roster. Narrator prose outside 「...」 remains speaker=narrator.\n"
        "Return JSON array only. Each item shape: "
        '{"speaker":"narrator|PC|NPC display label","npc_key":"","emotion":"","text":"..."}.\n'
        "For dialogue items, put only the spoken words in text; do not include the surrounding 「」 brackets.\n"
        "Use speaker PC for the player character. For known NPCs, set npc_key to their key when confident; "
        "otherwise use the stable public label as speaker and leave npc_key empty. Do not invent dialogue.\n\n"
        f"Roster:\n{json.dumps(roster, ensure_ascii=False)}\n\n"
        f"GM response:\n{text}"
    )


def _segment_public_payload(seg: TtsSegment) -> dict[str, Any]:
    return {
        "segment": seg.index,
        "speaker": seg.speaker,
        "kind": seg.kind,
        "voice": seg.voice,
        "provider": seg.provider,
        "model": seg.model,
        "text_preview": _truncate_prompt_text(seg.text, 90),
    }
