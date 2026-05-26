"""Voice assignment + hidden Gemini-style performance notes.

The streaming flow in `services.trpg_tts` takes parsed segments, resolves
runtime providers/voices here, and then attaches per-segment delivery
notes (emotion, character style, nearby narration cues).
"""

from __future__ import annotations

from typing import Any

from orm.models import GameSession

from services import admin_config
from services.media_generation import catalog_tts_voices, default_voice_for
from services.trpg_npc.assets import (
    _keyword_voice,
    _stable_voice,
    _tts_provider_for_model,
)
from services.trpg_tts_segments import (
    TtsSegment,
    _find_character_for_segment,
    _session_npcs,
)
from services.trpg_tts_text import (
    _DELIVERY_SENTENCE_RE,
    _gender_hint,
    _truncate_prompt_text,
)

_DELIVERY_CUE_KEYWORDS = (
    "语气", "口气", "声音", "声线", "嗓音", "低声", "压低", "轻声", "小声",
    "平平", "平淡", "平静", "冷静", "淡淡", "没有起伏", "不带情绪",
    "顿了顿", "停顿", "慢慢", "清楚", "一字一句", "咬字",
    "flat", "matter-of-fact", "quiet", "low voice", "calm", "plain",
)
_FLAT_DELIVERY_KEYWORDS = (
    "语气平平", "平平", "平淡", "平静", "冷静", "淡淡", "没有起伏",
    "不带情绪", "flat", "plain", "matter-of-fact",
)
_LOW_DELIVERY_KEYWORDS = ("低声", "压低", "轻声", "小声", "low voice", "quiet")
_DELIBERATE_DELIVERY_KEYWORDS = ("顿了顿", "停顿", "清楚", "一字一句", "咬字")


def _assign_segments(
    segments: list[TtsSegment],
    *,
    session: GameSession,
    dialogue_runtime,
    narration_runtime,
) -> list[TtsSegment]:
    narration_voice = _narration_voice(narration_runtime)
    npcs = _session_npcs(session)
    used_dialogue_voices: set[str] = set()

    for seg in segments:
        if seg.kind == "narrator" or seg.speaker == "narrator":
            seg.provider = narration_runtime.provider
            seg.model = narration_runtime.model
            seg.voice = narration_voice
            continue

        npc = _find_character_for_segment(seg, session, npcs)
        seg.provider = dialogue_runtime.provider
        seg.model = dialogue_runtime.model
        seg.voice = _dialogue_voice(seg, npc, dialogue_runtime, used_dialogue_voices)
        if seg.voice:
            used_dialogue_voices.add(seg.voice)

    return segments


def _narration_voice(runtime) -> str:
    settings = admin_config.get_media_settings()
    narration = settings.get("narration_voice")
    if isinstance(narration, dict):
        if (
            str(narration.get("provider") or "").strip() == runtime.provider
            and str(narration.get("model") or "").strip() == runtime.model
        ):
            voice = str(narration.get("voice") or "").strip()
            if voice:
                return voice
    return default_voice_for(runtime.provider, runtime.model)


def _dialogue_voice(
    seg: TtsSegment,
    npc: dict[str, Any] | None,
    runtime,
    used: set[str],
) -> str:
    valid = _valid_voice_ids(runtime)
    provider_key = _tts_provider_for_model(runtime.model)
    if npc:
        for candidate in _npc_voice_candidates(npc, provider_key):
            if not valid or candidate in valid:
                return candidate
        chosen = _keyword_voice(npc, runtime.model, used) or _stable_voice(npc, runtime.model, used)
        if chosen and (not valid or chosen in valid):
            return chosen

    fallback_npc = {
        "key": seg.npc_key or seg.speaker,
        "name": seg.speaker,
        "summary": seg.speaker,
        "gender": _gender_hint(seg.speaker),
    }
    chosen = _keyword_voice(fallback_npc, runtime.model, used) or _stable_voice(
        fallback_npc,
        runtime.model,
        used,
    )
    if chosen and (not valid or chosen in valid):
        return chosen
    return default_voice_for(runtime.provider, runtime.model)


def _npc_voice_candidates(npc: dict[str, Any], provider_key: str) -> list[str]:
    candidates: list[str] = []
    if str(npc.get("tts_voice_provider") or "").strip() == provider_key:
        candidates.append(str(npc.get("active_tts_voice") or "").strip())
    overrides = npc.get("tts_voice_overrides")
    if isinstance(overrides, dict):
        candidates.append(str(overrides.get(provider_key) or "").strip())
    candidates.append(str(npc.get("active_tts_voice") or "").strip())
    candidates.append(str(npc.get("tts_voice") or "").strip())
    return [c for c in candidates if c]


def _valid_voice_ids(runtime) -> set[str]:
    return {voice.id for voice in catalog_tts_voices(runtime.provider, runtime.model)}


def _attach_performance_notes(
    segments: list[TtsSegment],
    session: GameSession,
) -> list[TtsSegment]:
    npcs = _session_npcs(session)
    for idx, seg in enumerate(segments):
        notes: list[str] = []
        if seg.kind == "narrator":
            notes.append(
                "TRPG narrator delivery: immersive, cinematic, controlled, and natural. "
                "Do not explain rules or read hidden tags aloud."
            )
        else:
            notes.append(_emotion_delivery_note(seg.emotion))
            profile = _character_style_note(seg, session, npcs)
            if profile:
                notes.append(f"Character profile: {profile}.")
            cue_text = _nearby_delivery_cues(segments, idx)
            if cue_text:
                notes.append(f"Local narration cues, do not read aloud: {cue_text}.")
                interpreted = _delivery_cue_interpretation(cue_text)
                if interpreted:
                    notes.append(interpreted)
            notes.append(
                "Speak only the dialogue text. Keep the acting understated unless an inline audio tag requires more."
            )
        seg.performance_notes = _truncate_prompt_text(" ".join(notes), 700)
    return segments


def _nearby_delivery_cues(segments: list[TtsSegment], idx: int) -> str:
    cues: list[str] = []
    for neighbor_idx in (idx - 1, idx + 1):
        if 0 <= neighbor_idx < len(segments) and segments[neighbor_idx].kind == "narrator":
            cue = _extract_delivery_cue_text(segments[neighbor_idx].text)
            if cue:
                cues.append(cue)
    return _truncate_prompt_text(" ".join(dict.fromkeys(cues)), 220)


def _extract_delivery_cue_text(text: str, max_chars: int = 180) -> str:
    chunks = [c.strip() for c in _DELIVERY_SENTENCE_RE.split(text or "") if c and c.strip()]
    cue_chunks = [
        c for c in chunks
        if any(keyword.lower() in c.lower() for keyword in _DELIVERY_CUE_KEYWORDS)
    ]
    return _truncate_prompt_text(" ".join(cue_chunks[-2:]), max_chars) if cue_chunks else ""


def _character_style_note(
    seg: TtsSegment,
    session: GameSession,
    npcs: list[dict[str, Any]],
) -> str:
    char = _find_character_for_segment(seg, session, npcs)
    if not isinstance(char, dict):
        return ""
    voice_card = char.get("voice_card") if isinstance(char.get("voice_card"), dict) else {}
    parts: list[str] = []
    for key in ("speaking_style", "mannerisms", "catchphrase"):
        value = voice_card.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{key}: {value.strip()}")
    for key in ("dialogue_style", "personality", "summary", "description", "voice_hint"):
        value = char.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{key}: {value.strip()}")
    return _truncate_prompt_text(" | ".join(parts), 260)


def _emotion_delivery_note(emotion: str) -> str:
    emotion = (emotion or "").lower()
    mapping = {
        "calm": "Emotion marker is calm: neutral, restrained, low-intensity delivery.",
        "happy": "Emotion marker is happy: lightly amused or warm, not cartoonish.",
        "sad": "Emotion marker is sad: subdued and natural, not melodramatic.",
        "angry": "Emotion marker is angry: controlled tension; do not shout unless an inline audio tag says so.",
        "fearful": "Emotion marker is fearful: tense and contained; avoid exaggerated panic.",
        "surprised": "Emotion marker is surprised: brief, natural surprise; avoid overacting.",
        "disgusted": "Emotion marker is disgusted: mild aversion unless the line is explicit.",
    }
    return mapping.get(
        emotion,
        "Default dialogue delivery: natural and understated; scale emotion from the words and nearby narration.",
    )


def _delivery_cue_interpretation(cue_text: str) -> str:
    lowered = (cue_text or "").lower()
    notes: list[str] = []
    if any(keyword.lower() in lowered for keyword in _FLAT_DELIVERY_KEYWORDS):
        notes.append("Nearby narration indicates a flat/plain tone: keep pitch and energy steady.")
    if any(keyword.lower() in lowered for keyword in _LOW_DELIVERY_KEYWORDS):
        notes.append("Nearby narration indicates low/quiet speech: speak low and controlled.")
    if any(keyword.lower() in lowered for keyword in _DELIBERATE_DELIVERY_KEYWORDS):
        notes.append("Nearby narration indicates deliberate clarity or a pause: speak clearly and measured.")
    return " ".join(notes)
