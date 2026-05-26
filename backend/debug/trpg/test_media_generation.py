"""Runtime checks for unified media-generation adapters."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.media_generation import (  # noqa: E402
    MediaModelRuntime,
    avatar_image_size_for,
    _dashscope_multimodal_endpoint,
    _extract_audio_payload,
    _gemini_tts_payload,
    _image_request,
    _minimax_base,
    _parse_voice_items,
    _speech_request,
    catalog_tts_voices,
    is_image_generation_model,
    is_tts_model,
    provider_media_capability,
)


def assert_true(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise AssertionError(f"{name} failed" + (f": {detail}" if detail else ""))
    print(f"OK: {name}")


def case_xai_payload_uses_native_fields() -> None:
    endpoint, payload = _image_request(
        endpoint_provider="grok",
        runtime=MediaModelRuntime(
            provider="grok",
            model="grok-imagine-image",
            api_key="key",
            base_url="https://api.x.ai/v1",
        ),
        prompt="portrait prompt",
        size="1024x1024",
        n=1,
        response_format="b64_json",
    )
    assert_true("xai endpoint", endpoint == "https://api.x.ai/v1/images/generations", endpoint)
    assert_true("xai payload uses aspect ratio", payload["aspect_ratio"] == "1:1", repr(payload))
    assert_true("xai payload uses resolution", payload["resolution"] == "1k", repr(payload))
    assert_true("xai payload omits size", "size" not in payload, repr(payload))


def case_avatar_sizes_use_provider_minimums() -> None:
    assert_true(
        "openai gpt-image-2 avatar minimum",
        avatar_image_size_for("openai", "gpt-image-2") == "816x816",
    )
    assert_true(
        "openai legacy avatar minimum",
        avatar_image_size_for("openai", "gpt-image-1.5") == "1024x1024",
    )
    assert_true(
        "qwen image 2 avatar minimum",
        avatar_image_size_for("qwen", "qwen-image-2.0") == "512x512",
    )
    assert_true(
        "qwen max avatar minimum square preset",
        avatar_image_size_for("qwen", "qwen-image-max") == "1328x1328",
    )
    assert_true(
        "minimax avatar minimum",
        avatar_image_size_for("minimax", "image-01") == "512x512",
    )
    assert_true(
        "glm avatar minimum",
        avatar_image_size_for("glm", "glm-image") == "512x512",
    )
    assert_true(
        "doubao seedream 4.5 avatar minimum",
        avatar_image_size_for("doubao", "doubao-seedream-4-5") == "2K",
    )


def case_minimax_custom_size_uses_width_height() -> None:
    endpoint, payload = _image_request(
        endpoint_provider="minimax",
        runtime=MediaModelRuntime(
            provider="minimax",
            model="image-01",
            api_key="key",
            base_url="https://api.minimax.io/v1",
        ),
        prompt="portrait prompt",
        size="512x512",
        n=1,
        response_format="b64_json",
    )
    assert_true("minimax endpoint", endpoint == "https://api.minimax.io/v1/image_generation", endpoint)
    assert_true("minimax width minimum", payload["width"] == 512, repr(payload))
    assert_true("minimax height minimum", payload["height"] == 512, repr(payload))
    assert_true("minimax custom size omits aspect ratio", "aspect_ratio" not in payload, repr(payload))


def case_dashscope_uses_native_multimodal_endpoint() -> None:
    endpoint = _dashscope_multimodal_endpoint("https://dashscope.aliyuncs.com/compatible-mode/v1")
    assert_true(
        "dashscope native endpoint",
        endpoint == "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        endpoint,
    )


def case_minimax_media_base_uses_open_platform() -> None:
    assert_true(
        "minimax chat base remapped",
        _minimax_base("https://api.minimax.chat/v1") == "https://api.minimax.io/v1",
    )


def case_capability_detection_is_provider_aware() -> None:
    assert_true("grok image model", is_image_generation_model("grok", "grok-imagine-image"))
    assert_true("qwen tts model", is_tts_model("qwen", "qwen3-tts-flash"))
    assert_true("qwen minimax bridge tts model", is_tts_model("qwen", "MiniMax/speech-2.8-hd"))
    assert_true("deepseek no image", not is_image_generation_model("deepseek", "deepseek-v4-pro"))
    assert_true("claude no tts", not is_tts_model("claude", "claude-sonnet-4-6"))


def case_gemini_tts_payload_matches_generate_content_shape() -> None:
    payload = _gemini_tts_payload("gemini-3.1-flash-tts-preview", "你好", "Kore", "calm")
    cfg = payload["generationConfig"]
    voice = cfg["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"]
    assert_true("gemini audio modality", cfg["responseModalities"] == ["AUDIO"], repr(payload))
    assert_true("gemini voice", voice == "Kore", repr(payload))
    assert_true("gemini model in body", payload["model"] == "gemini-3.1-flash-tts-preview", repr(payload))


def case_minimax_hex_audio_is_decoded() -> None:
    payload = {"data": {"audio": "49443304"}}
    audio = _extract_audio_payload(payload, fallback_mime="audio/mpeg")
    assert_true("minimax audio bytes", audio["bytes"] == b"ID3\x04", repr(audio))
    assert_true("minimax audio mime", audio["mime"] == "audio/mpeg", repr(audio))


def case_qwen_minimax_tts_uses_dashscope_bridge_payload() -> None:
    endpoint, payload, mime = _speech_request(
        endpoint_provider="qwen",
        runtime=MediaModelRuntime(
            provider="qwen",
            model="MiniMax/speech-2.8-hd",
            api_key="key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        text="hello",
        voice="English_expressive_narrator",
        audio_format="mp3",
        instructions="",
        language="auto",
    )
    assert_true("dashscope tts endpoint", "multimodal-generation" in endpoint, endpoint)
    assert_true("dashscope bridge has input text", payload["input"]["text"] == "hello", repr(payload))
    assert_true("dashscope bridge has minimax voice setting", payload["input"]["voice_setting"]["voice_id"] == "English_expressive_narrator", repr(payload))
    assert_true("dashscope bridge mime", mime == "audio/wav", mime)


def case_glm_voice_uses_chat_completions() -> None:
    endpoint, payload, mime = _speech_request(
        endpoint_provider="glm",
        runtime=MediaModelRuntime(
            provider="glm",
            model="glm-4-voice",
            api_key="key",
            base_url="https://open.bigmodel.cn/api/paas/v4",
        ),
        text="你好",
        voice="",
        audio_format="wav",
        instructions="",
        language="auto",
    )
    assert_true("glm voice endpoint", endpoint.endswith("/chat/completions"), endpoint)
    assert_true("glm voice mime", mime == "audio/wav", mime)
    assert_true("glm voice text part", payload["messages"][0]["content"][0]["text"] == "你好", repr(payload))


def case_audio_inline_data_pcm_wraps_to_wav() -> None:
    inline_pcm = base64.b64encode(b"\x00\x00\x01\x00").decode("ascii")
    payload = {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "audio/L16;rate=24000", "data": inline_pcm}}]}}]}
    audio = _extract_audio_payload(payload, fallback_mime="audio/wav")
    assert_true("pcm wrapped as wav", audio["bytes"].startswith(b"RIFF"), repr(audio))
    assert_true("pcm mime wav", audio["mime"] == "audio/wav", repr(audio))


def case_provider_capability_docs_present() -> None:
    cap = provider_media_capability("qwen", "qwen3-tts-flash")
    assert_true("qwen tts enabled", cap.tts, repr(cap))
    assert_true("qwen docs present", any("qwen-tts" in doc for doc in cap.docs), repr(cap.docs))


def case_voice_catalogs_are_provider_aware() -> None:
    openai = {voice.id for voice in catalog_tts_voices("openai", "gpt-4o-mini-tts")}
    gemini = {voice.id for voice in catalog_tts_voices("gemini", "gemini-3.1-flash-tts-preview")}
    gemini_meta = {
        voice.id: voice
        for voice in catalog_tts_voices("gemini", "gemini-3.1-flash-tts-preview")
    }
    qwen = {voice.id for voice in catalog_tts_voices("qwen", "qwen3-tts-flash")}
    bridge = {voice.id for voice in catalog_tts_voices("qwen", "MiniMax/speech-2.8-hd")}
    assert_true("openai catalog includes latest voice", "cedar" in openai, repr(openai))
    assert_true("gemini catalog includes kore", "Kore" in gemini, repr(gemini))
    assert_true("gemini catalog carries gender", gemini_meta["Kore"].gender == "female", repr(gemini_meta["Kore"]))
    assert_true("gemini catalog carries role description", "指挥官" in gemini_meta["Kore"].description, repr(gemini_meta["Kore"]))
    assert_true("qwen catalog includes current voice", "Ethan" in qwen, repr(qwen))
    assert_true("qwen minimax bridge catalog", "English_expressive_narrator" in bridge, repr(bridge))
    assert_true("qwen minimax bridge catalog is not truncated", "audiobook_female_1" in bridge and "Sweet_Girl" in bridge, repr(bridge))
    assert_true("qwen minimax bridge catalog count", len(bridge) == 42, repr(len(bridge)))


def case_live_voice_response_parser_handles_provider_shapes() -> None:
    xai = _parse_voice_items(
        {"voices": [{"voice_id": "eve", "name": "Eve", "description": "Energetic"}]},
        source="live",
    )
    minimax = _parse_voice_items(
        {
            "system_voice": [{
                "voice_id": "Chinese (Mandarin)_News_Anchor",
                "voice_name": "News Anchor",
                "description": ["Professional female anchor"],
            }],
            "voice_clone": [{"voice_id": "custom-clone", "voice_name": "Clone"}],
        },
        source="live",
    )
    assert_true("xai voice parser", xai[0].id == "eve" and xai[0].name == "Eve", repr(xai))
    assert_true("minimax system parser", minimax[0].id == "Chinese (Mandarin)_News_Anchor", repr(minimax))
    assert_true("minimax clone parser", minimax[1].id == "custom-clone", repr(minimax))


if __name__ == "__main__":
    case_xai_payload_uses_native_fields()
    case_avatar_sizes_use_provider_minimums()
    case_minimax_custom_size_uses_width_height()
    case_dashscope_uses_native_multimodal_endpoint()
    case_minimax_media_base_uses_open_platform()
    case_capability_detection_is_provider_aware()
    case_gemini_tts_payload_matches_generate_content_shape()
    case_minimax_hex_audio_is_decoded()
    case_qwen_minimax_tts_uses_dashscope_bridge_payload()
    case_glm_voice_uses_chat_completions()
    case_audio_inline_data_pcm_wraps_to_wav()
    case_provider_capability_docs_present()
    case_voice_catalogs_are_provider_aware()
    case_live_voice_response_parser_handles_provider_shapes()
    print("Media-generation checks passed.")
