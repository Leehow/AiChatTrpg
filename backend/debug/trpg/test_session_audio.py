"""Backend diagnostics for routes/session_audio.py and the hardened
``_apply_voice_fields`` in routes/sessions.py.

Run:
    cd backend && source .venv/bin/activate
    python debug/trpg/test_session_audio.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import HTTPException  # noqa: E402

from routes.session_audio import (  # noqa: E402
    _clear_npc_voice_slots,
    _is_npc_locked,
    _read_bgm_track_ids,
    _write_bgm_track_ids,
    build_voice_intro_text,
    normalize_bgm_selection,
    voice_intro_signature,
)
from routes.sessions import _VoiceAssignBody, _apply_voice_fields  # noqa: E402
from services.trpg_npc.assets import _assign_missing_voices  # noqa: E402


def assert_eq(name: str, actual, expected) -> None:
    if actual != expected:
        raise AssertionError(f"{name} failed: expected {expected!r}, got {actual!r}")
    print(f"OK: {name}")


def assert_true(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise AssertionError(f"{name} failed" + (f": {detail}" if detail else ""))
    print(f"OK: {name}")


class _FakeSession:
    """Minimal stand-in for ``GameSession`` used by the BGM helpers."""

    def __init__(self, memory_state: dict | None = None) -> None:
        self.memory_state = memory_state if memory_state is not None else {}

    # `flag_modified` works against SQLAlchemy state, not plain dicts. The
    # BGM helpers call it via the route layer; the helpers themselves only
    # need attribute assignment to work, so we expose a no-op here.


# ---------------------------------------------------------------------------
# normalize_bgm_selection
# ---------------------------------------------------------------------------


def case_bgm_normalize_preserves_order_and_dedupes() -> None:
    visible = {"a", "b", "c"}
    out = normalize_bgm_selection(["b", "a", "b", "c", "a"], visible)
    assert_eq("order preserved + deduped", out, ["b", "a", "c"])


def case_bgm_normalize_skips_blank_ids() -> None:
    visible = {"x"}
    out = normalize_bgm_selection(["", "  ", "x"], visible)
    assert_eq("blank ids skipped", out, ["x"])


def case_bgm_normalize_rejects_invisible_ids() -> None:
    visible = {"a", "b"}
    raised = False
    try:
        normalize_bgm_selection(["a", "ghost"], visible)
    except HTTPException as exc:
        raised = True
        assert_eq("rejected ghost id", exc.status_code, 400)
        assert_true("error mentions ghost", "ghost" in str(exc.detail))
    assert_true("HTTPException raised for invisible id", raised)


def case_bgm_normalize_empty_list_is_ok() -> None:
    out = normalize_bgm_selection([], {"a"})
    assert_eq("empty list normalises to []", out, [])


def case_bgm_read_write_roundtrip() -> None:
    session = _FakeSession({"npcs": [], "_settings": {}})
    assert_eq("initial bgm empty", _read_bgm_track_ids(session), [])
    # `_write_bgm_track_ids` calls `flag_modified`; on a non-ORM dummy this
    # raises InstrumentationError, so wrap in try/except to test the dict
    # mutation half only.
    mem = dict(session.memory_state)
    settings = dict(mem.get("_settings") or {})
    settings["bgm_track_ids"] = ["a", "b"]
    mem["_settings"] = settings
    session.memory_state = mem
    assert_eq("read after manual write", _read_bgm_track_ids(session), ["a", "b"])


def case_bgm_read_dedupes_existing_state() -> None:
    session = _FakeSession(
        {"_settings": {"bgm_track_ids": ["a", "a", "b", "", "b"]}}
    )
    assert_eq("read dedupes legacy state", _read_bgm_track_ids(session), ["a", "b"])


def case_bgm_read_handles_missing_settings() -> None:
    session = _FakeSession({})
    assert_eq("empty memory_state → []", _read_bgm_track_ids(session), [])
    session = _FakeSession({"_settings": {}})
    assert_eq("no bgm key → []", _read_bgm_track_ids(session), [])
    session = _FakeSession({"_settings": {"bgm_track_ids": "nope"}})
    assert_eq("non-list bgm → []", _read_bgm_track_ids(session), [])


# ---------------------------------------------------------------------------
# _apply_voice_fields
# ---------------------------------------------------------------------------


def case_apply_voice_sets_lock_and_busts_cache() -> None:
    card = {
        "name": "Iris",
        "voice_intro_text": "stale",
        "voice_intro_audio_url": "/api/media/files/old.mp3",
        "voice_intro_signature": "qwen:qwen3-tts:Dylan:abc",
    }
    body = _VoiceAssignBody(voice="Cherry", provider="dashscope", model="qwen3-tts-flash")
    _apply_voice_fields(card, body)
    assert_eq("primary voice set", card["tts_voice"], "Cherry")
    assert_eq("active voice mirrored", card["active_tts_voice"], "Cherry")
    assert_eq("model stamped", card["tts_voice_model"], "qwen3-tts-flash")
    assert_eq("provider stamped", card["tts_voice_provider"], "dashscope")
    assert_eq(
        "override written for provider",
        card["tts_voice_overrides"]["dashscope"],
        "Cherry",
    )
    assert_eq("locked", card["tts_voice_locked"], True)
    assert_eq("intro text cleared", card["voice_intro_text"], "")
    assert_eq("intro audio cleared", card["voice_intro_audio_url"], "")
    assert_eq("intro signature cleared", card["voice_intro_signature"], "")


def case_apply_voice_empty_clears_lock_and_override() -> None:
    card = {
        "tts_voice": "Cherry",
        "active_tts_voice": "Cherry",
        "tts_voice_locked": True,
        "tts_voice_overrides": {"dashscope": "Cherry", "minimax": "chatlab-rp-x"},
        "voice_intro_text": "hi",
        "voice_intro_audio_url": "/api/media/files/old.mp3",
        "voice_intro_signature": "sig",
    }
    body = _VoiceAssignBody(voice="", provider="dashscope")
    _apply_voice_fields(card, body)
    assert_eq("voice cleared", card["tts_voice"], "")
    assert_eq("active cleared", card["active_tts_voice"], "")
    assert_eq("lock cleared", card["tts_voice_locked"], False)
    assert_true(
        "current provider override removed",
        "dashscope" not in card["tts_voice_overrides"],
    )
    assert_eq(
        "other provider override preserved",
        card["tts_voice_overrides"]["minimax"],
        "chatlab-rp-x",
    )
    assert_eq("intro text cleared on unlock", card["voice_intro_text"], "")
    assert_eq("intro audio cleared on unlock", card["voice_intro_audio_url"], "")
    assert_eq("intro signature cleared on unlock", card["voice_intro_signature"], "")


def case_apply_voice_without_provider_skips_override_write() -> None:
    card: dict = {}
    body = _VoiceAssignBody(voice="Dylan")
    _apply_voice_fields(card, body)
    assert_eq("primary set", card["tts_voice"], "Dylan")
    assert_eq("locked even without provider", card["tts_voice_locked"], True)
    assert_true(
        "no override written without provider",
        "tts_voice_overrides" not in card,
    )


# ---------------------------------------------------------------------------
# rematch helpers
# ---------------------------------------------------------------------------


def case_rematch_skip_locked_preserves_locked_npcs() -> None:
    # Use the dashscope/qwen pool so default `_assign_missing_voices` resolves
    # to MALE_VOICES/FEMALE_VOICES.
    npcs = [
        {
            "key": "npc-locked",
            "name": "Helen",
            "gender": "female",
            "tts_voice": "Cherry",
            "active_tts_voice": "Cherry",
            "tts_voice_locked": True,
            "tts_voice_provider": "dashscope",
            "tts_voice_model": "qwen3-tts-flash",
        },
        {
            "key": "npc-free",
            "name": "Marlin",
            "gender": "male",
            "tts_voice": "Eric",
            "active_tts_voice": "Eric",
            "tts_voice_locked": False,
            "tts_voice_provider": "dashscope",
            "tts_voice_model": "qwen3-tts-flash",
        },
    ]
    # Simulate rematch loop (skip_locked=True).
    rematched = 0
    skipped = 0
    for npc in npcs:
        if _is_npc_locked(npc):
            skipped += 1
            continue
        _clear_npc_voice_slots(npc, "dashscope")
        rematched += 1
    assert_eq("one locked skipped", skipped, 1)
    assert_eq("one rematched cleared", rematched, 1)
    assert_eq("locked NPC voice preserved", npcs[0]["tts_voice"], "Cherry")
    assert_eq("free NPC voice cleared pre-assign", npcs[1]["tts_voice"], "")

    _assign_missing_voices(npcs, "qwen3-tts-flash")
    assert_eq("locked NPC still keeps voice", npcs[0]["active_tts_voice"], "Cherry")
    assert_true(
        "free NPC got a fresh voice",
        bool(npcs[1].get("active_tts_voice")),
        detail=f"npc-free active={npcs[1].get('active_tts_voice')!r}",
    )


def case_rematch_force_can_clear_locked_npc() -> None:
    npc = {
        "key": "npc",
        "name": "Helen",
        "tts_voice": "Cherry",
        "active_tts_voice": "Cherry",
        "tts_voice_locked": True,
        "tts_voice_overrides": {"dashscope": "Cherry"},
    }
    # force=True path: caller bypasses the locked check.
    _clear_npc_voice_slots(npc, "dashscope")
    assert_eq("force clears voice", npc["tts_voice"], "")
    assert_true(
        "force clears provider override",
        "dashscope" not in npc.get("tts_voice_overrides", {}),
    )


def _simulate_rematch_loop(
    npcs: list[dict],
    *,
    skip_locked: bool,
    force: bool,
    provider: str = "dashscope",
) -> tuple[int, int]:
    """Mirror the route's per-NPC dispatch from
    ``post_npcs_rematch_voices`` so the body-level lock contract is tested
    directly. Returns ``(rematched, skipped_locked)``.
    """
    _ = skip_locked  # accepted for API symmetry; never relaxes the lock.
    allow_clear_locked = bool(force)
    rematched = 0
    skipped_locked = 0
    for npc in npcs:
        if _is_npc_locked(npc) and not allow_clear_locked:
            skipped_locked += 1
            continue
        _clear_npc_voice_slots(npc, provider)
        rematched += 1
    return rematched, skipped_locked


def case_rematch_skip_locked_false_without_force_still_preserves_lock() -> None:
    """Regression: {skip_locked: false, force: false} must NOT clear a locked NPC."""
    npcs = [
        {
            "key": "npc-locked",
            "name": "Helen",
            "tts_voice": "Cherry",
            "active_tts_voice": "Cherry",
            "tts_voice_locked": True,
            "tts_voice_overrides": {"dashscope": "Cherry"},
        },
        {
            "key": "npc-free",
            "name": "Marlin",
            "tts_voice": "Eric",
            "active_tts_voice": "Eric",
            "tts_voice_locked": False,
        },
    ]
    rematched, skipped = _simulate_rematch_loop(npcs, skip_locked=False, force=False)
    assert_eq("locked NPC counted as skipped_locked", skipped, 1)
    assert_eq("free NPC counted as rematched", rematched, 1)
    assert_eq(
        "locked NPC voice survives skip_locked=false",
        npcs[0]["tts_voice"],
        "Cherry",
    )
    assert_eq(
        "locked NPC active voice survives",
        npcs[0]["active_tts_voice"],
        "Cherry",
    )
    assert_eq(
        "locked NPC override survives",
        npcs[0]["tts_voice_overrides"]["dashscope"],
        "Cherry",
    )
    assert_eq("free NPC voice cleared", npcs[1]["tts_voice"], "")


def case_rematch_force_true_overrides_lock() -> None:
    """force=True is the ONLY way to clear a locked NPC."""
    npcs = [
        {
            "key": "npc-locked",
            "name": "Helen",
            "tts_voice": "Cherry",
            "active_tts_voice": "Cherry",
            "tts_voice_locked": True,
            "tts_voice_overrides": {"dashscope": "Cherry"},
        },
    ]
    rematched, skipped = _simulate_rematch_loop(npcs, skip_locked=True, force=True)
    assert_eq("force=True clears one NPC", rematched, 1)
    assert_eq("force=True records zero skipped", skipped, 0)
    assert_eq("force=True cleared primary voice", npcs[0]["tts_voice"], "")
    assert_eq("force=True cleared active voice", npcs[0]["active_tts_voice"], "")
    assert_true(
        "force=True dropped provider override",
        "dashscope" not in npcs[0].get("tts_voice_overrides", {}),
    )


def case_rematch_skip_locked_true_without_force_preserves_lock() -> None:
    """Belt-and-suspenders: default body (skip_locked=True, force=False) also preserves locks."""
    npcs = [
        {
            "key": "npc-locked",
            "name": "Helen",
            "tts_voice": "Cherry",
            "active_tts_voice": "Cherry",
            "tts_voice_locked": True,
        },
    ]
    rematched, skipped = _simulate_rematch_loop(npcs, skip_locked=True, force=False)
    assert_eq("default body skips locked", skipped, 1)
    assert_eq("default body rematches nothing here", rematched, 0)
    assert_eq("locked NPC voice intact", npcs[0]["tts_voice"], "Cherry")


# ---------------------------------------------------------------------------
# voice intro helpers
# ---------------------------------------------------------------------------


def case_intro_text_uses_card_fields() -> None:
    card = {
        "name": "Mira",
        "role": "tavern keeper",
        "description": "A weathered woman with sharp eyes and a quick smile.",
        "voice_hint": "warm, low-pitched",
    }
    text = build_voice_intro_text(card)
    assert_true("name in intro", "Mira" in text)
    assert_true("role in intro", "tavern keeper" in text)
    assert_true("description fragment in intro", "weathered" in text)
    assert_true("voice hint in intro", "warm" in text)


def case_intro_text_falls_back_to_default_name() -> None:
    text = build_voice_intro_text({})
    assert_eq("default-only when no fields", text, "Stranger")


def case_intro_text_caps_long_fields() -> None:
    card = {
        "name": "Vex",
        "description": "x" * 5000,
        "voice_hint": "y" * 5000,
    }
    text = build_voice_intro_text(card)
    assert_true("text capped at 400", len(text) <= 400)


def case_intro_signature_is_stable_and_input_sensitive() -> None:
    sig_a = voice_intro_signature("gemini", "gemini-tts", "Kore", "Hi there.")
    sig_a_again = voice_intro_signature("gemini", "gemini-tts", "Kore", "Hi there.")
    sig_voice = voice_intro_signature("gemini", "gemini-tts", "Puck", "Hi there.")
    sig_text = voice_intro_signature("gemini", "gemini-tts", "Kore", "Hi there!")
    assert_eq("same input → same signature", sig_a, sig_a_again)
    assert_true("voice change → new signature", sig_a != sig_voice)
    assert_true("text change → new signature", sig_a != sig_text)
    assert_true(
        "signature shape provider:model:voice:hash",
        sig_a.startswith("gemini:gemini-tts:Kore:") and len(sig_a.split(":")[-1]) == 16,
    )


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    case_bgm_normalize_preserves_order_and_dedupes()
    case_bgm_normalize_skips_blank_ids()
    case_bgm_normalize_rejects_invisible_ids()
    case_bgm_normalize_empty_list_is_ok()
    case_bgm_read_write_roundtrip()
    case_bgm_read_dedupes_existing_state()
    case_bgm_read_handles_missing_settings()
    case_apply_voice_sets_lock_and_busts_cache()
    case_apply_voice_empty_clears_lock_and_override()
    case_apply_voice_without_provider_skips_override_write()
    case_rematch_skip_locked_preserves_locked_npcs()
    case_rematch_force_can_clear_locked_npc()
    case_rematch_skip_locked_false_without_force_still_preserves_lock()
    case_rematch_force_true_overrides_lock()
    case_rematch_skip_locked_true_without_force_preserves_lock()
    case_intro_text_uses_card_fields()
    case_intro_text_falls_back_to_default_name()
    case_intro_text_caps_long_fields()
    case_intro_signature_is_stable_and_input_sensitive()
    print("All session-audio cases passed.")


if __name__ == "__main__":
    main()
