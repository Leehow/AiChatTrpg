"""Runtime checks for TRPG message TTS parsing and voice assignment."""

from __future__ import annotations

import io
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.media_storage import store_audio_bytes  # noqa: E402
from services.trpg_tts import (  # noqa: E402
    TtsRuntime,
    _assign_segments,
    _attach_performance_notes,
    _combine_segment_events_to_mp3,
    _needs_llm_speaker_parse,
    _parse_segments,
    _prepare_tts_source,
    _segments_from_llm_payload,
)


def assert_true(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise AssertionError(f"{name} failed" + (f": {detail}" if detail else ""))
    print(f"OK: {name}")


def case_speak_markers_keep_emotion_and_key() -> None:
    raw = (
        "第一秒，风很低。\n\n"
        "「别碰它。」[speak:fearful:kei]凯伊[/speak]\n\n"
        "[oss]门外传来刹车声[/oss]"
    )
    clean = _prepare_tts_source(raw)
    segments = _parse_segments(clean)

    assert_true("three tts segments", len(segments) == 3, repr(segments))
    assert_true("narrator first", segments[0].speaker == "narrator", repr(segments[0]))
    assert_true("dialogue speaker", segments[1].speaker == "凯伊", repr(segments[1]))
    assert_true("dialogue emotion", segments[1].emotion == "fearful", repr(segments[1]))
    assert_true("dialogue npc key", segments[1].npc_key == "kei", repr(segments[1]))
    assert_true("oss rendered as narration", "远处传来" in segments[2].text, repr(segments[2]))


def case_thought_blocks_route_to_pc_voice() -> None:
    clean = _prepare_tts_source("[thought]我不能让她发现。[/thought]")
    segments = _parse_segments(clean)

    assert_true("thought becomes one segment", len(segments) == 1, repr(segments))
    assert_true("thought speaker is PC", segments[0].speaker == "PC", repr(segments[0]))
    assert_true("thought is dialogue", segments[0].kind == "dialogue", repr(segments[0]))


def case_fixed_speaker_key_slot_is_parsed() -> None:
    segments = _parse_segments("「别碰它。」[speak::vern]Vern[/speak]")

    assert_true("key-only speak tag parsed", len(segments) == 1, repr(segments))
    assert_true("key-only speaker", segments[0].speaker == "Vern", repr(segments[0]))
    assert_true("key-only npc key", segments[0].npc_key == "vern", repr(segments[0]))


def case_untagged_corner_quotes_use_llm_fallback_not_hardcoded_rules() -> None:
    text = "Vern 抬起头。「别碰它。」他说。"
    segments = _parse_segments(text)

    assert_true(
        "untagged quote has no hardcoded speaker",
        not any(seg.kind == "dialogue" for seg in segments),
        repr(segments),
    )
    assert_true("untagged quote asks fallback", _needs_llm_speaker_parse(text, segments), repr(segments))


def case_control_marker_aliases_are_not_spoken() -> None:
    clean = _prepare_tts_source(
        "车灯晃了一下。[UPDATEOBJECTIVE]{\"objective\":\"不要读出来\"}[/UPDATEOBJECTIVE]"
    )
    segments = _parse_segments(clean)

    assert_true("control marker alias stripped", len(segments) == 1, repr(segments))
    assert_true("control marker body stripped", "不要读出来" not in segments[0].text, repr(segments[0]))
    assert_true("narration survives control stripping", segments[0].text == "车灯晃了一下。", repr(segments[0]))


def case_llm_fallback_strips_dialogue_quote_wrapper() -> None:
    segments = _segments_from_llm_payload([
        {"speaker": "PC", "text": "「镇上有没有医生？」"},
        {"speaker": "narrator", "text": "Vern 抬起目光。"},
    ])

    assert_true("llm fallback strips dialogue wrapper", segments[0].text == "镇上有没有医生？", repr(segments[0]))
    assert_true("llm fallback keeps narrator prose", segments[1].text == "Vern 抬起目光。", repr(segments[1]))


def case_combined_message_audio_is_mp3() -> None:
    first = _tiny_wav_bytes(amplitude=800)
    second = _tiny_wav_bytes(amplitude=1200)
    first_url = store_audio_bytes(first, "audio/wav")
    second_url = store_audio_bytes(second, "audio/wav")

    combined = _combine_segment_events_to_mp3([
        {"segment": 1, "audio_url": first_url, "format": "wav"},
        {"segment": 2, "audio_url": second_url, "format": "wav"},
    ])

    assert_true("combined message audio generated", len(combined) > 64, str(len(combined)))
    assert_true("combined message audio is mp3", combined.startswith(b"ID3") or combined[:2] == b"\xff\xfb", combined[:8].hex())


def _tiny_wav_bytes(*, amplitude: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        sample = int(amplitude).to_bytes(2, "little", signed=True)
        wav.writeframes(sample * 2400)
    return buf.getvalue()


def case_known_npc_uses_stored_gemini_voice() -> None:
    session = SimpleNamespace(
        memory_state={
            "npcs": [{
                "key": "kei",
                "name": "凯伊",
                "gender": "female",
                "active_tts_voice": "Kore",
                "tts_voice_provider": "gemini",
                "personality": "冷静、克制，但在危险时会压低声音。",
            }]
        },
        character={},
    )
    segments = _parse_segments("「别碰它。」[speak:fearful:kei]凯伊[/speak]")
    assigned = _assign_segments(
        segments,
        session=session,  # type: ignore[arg-type]
        dialogue_runtime=TtsRuntime(provider="gemini", model="gemini-3.1-flash-tts-preview"),
        narration_runtime=TtsRuntime(provider="qwen", model="MiniMax/speech-2.8-hd"),
    )
    with_notes = _attach_performance_notes(assigned, session)  # type: ignore[arg-type]

    assert_true("known npc voice selected", with_notes[0].voice == "Kore", repr(with_notes[0]))
    assert_true("gemini model stamped", with_notes[0].provider == "gemini", repr(with_notes[0]))
    assert_true("emotion note attached", "fearful" in with_notes[0].performance_notes, with_notes[0].performance_notes)


if __name__ == "__main__":
    case_speak_markers_keep_emotion_and_key()
    case_thought_blocks_route_to_pc_voice()
    case_fixed_speaker_key_slot_is_parsed()
    case_untagged_corner_quotes_use_llm_fallback_not_hardcoded_rules()
    case_control_marker_aliases_are_not_spoken()
    case_llm_fallback_strips_dialogue_quote_wrapper()
    case_combined_message_audio_is_mp3()
    case_known_npc_uses_stored_gemini_voice()
    print("TRPG TTS checks passed.")
