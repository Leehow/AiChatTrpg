"""Runtime checks for NPC portrait queueing and voice assignment."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.trpg_npc.assets import (  # noqa: E402
    GEMINI_FEMALE,
    GEMINI_MALE,
    MINIMAX_MALE,
    ModelRuntime,
    _assign_missing_voices,
    _mark_portrait_requests,
)
from services.media_generation import extract_image_url  # noqa: E402


def assert_true(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise AssertionError(f"{name} failed" + (f": {detail}" if detail else ""))
    print(f"OK: {name}")


def case_gemini_voice_pool_matches_character_gender() -> None:
    npcs = [
        {"key": "anna", "name": "Anna", "gender": "female"},
        {"key": "guard", "name": "Guard", "gender": "male"},
    ]

    changed = _assign_missing_voices(npcs, "gemini-3.1-flash-tts-preview")

    assert_true("two voices assigned", changed == 2, repr(npcs))
    assert_true("female uses gemini female pool", npcs[0]["tts_voice"] in GEMINI_FEMALE, repr(npcs[0]))
    assert_true("male uses gemini male pool", npcs[1]["tts_voice"] in GEMINI_MALE, repr(npcs[1]))
    assert_true("active voice stamped", bool(npcs[0]["active_tts_voice"]), repr(npcs[0]))
    assert_true("provider stamped", npcs[0]["tts_voice_provider"] == "gemini", repr(npcs[0]))


def case_provider_override_preserves_existing_primary_voice() -> None:
    npc = {
        "key": "elder",
        "name": "Old Guard",
        "gender": "male",
        "tts_voice": "Cherry",
    }

    changed = _assign_missing_voices([npc], "MiniMax/speech-2.8-hd")

    assert_true("override assigned", changed == 1, repr(npc))
    assert_true("primary voice preserved", npc["tts_voice"] == "Cherry", repr(npc))
    assert_true("minimax override valid", npc["tts_voice_overrides"]["minimax"] in MINIMAX_MALE, repr(npc))
    assert_true("active voice uses override", npc["active_tts_voice"] == npc["tts_voice_overrides"]["minimax"], repr(npc))


def case_portrait_queue_skips_existing_portraits() -> None:
    npcs = [
        {"key": "fresh", "name": "Fresh NPC", "summary": "A watchful informant."},
        {"key": "done", "name": "Done NPC", "portrait_url": "https://img.example/done.png"},
    ]

    queued = _mark_portrait_requests(npcs, ModelRuntime(provider="debug", model="gpt-5.5-image"))

    assert_true("only missing portrait queued", queued == ["fresh"], repr(queued))
    assert_true("queued status stamped", npcs[0]["portrait_auto_status"] == "queued", repr(npcs[0]))
    assert_true("existing portrait untouched", "portrait_auto_status" not in npcs[1], repr(npcs[1]))


def case_extracts_generated_image_references() -> None:
    assert_true(
        "markdown url extracted",
        extract_image_url("![portrait](https://example.com/a.png)") == "https://example.com/a.png",
    )
    assert_true(
        "data uri extracted",
        extract_image_url("data:image/png;base64,QUJD") == "data:image/png;base64,QUJD",
    )


if __name__ == "__main__":
    case_gemini_voice_pool_matches_character_gender()
    case_provider_override_preserves_existing_primary_voice()
    case_portrait_queue_skips_existing_portraits()
    case_extracts_generated_image_references()
    print("NPC asset checks passed.")
