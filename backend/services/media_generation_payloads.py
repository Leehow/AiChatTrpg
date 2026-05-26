"""Per-provider HTTP request and JSON payload builders.

`_image_request` and `_speech_request` are the two top-level helpers that the
facade calls; the rest are provider-specific payload shapers grouped here so
the table of provider variants stays in one place.
"""

from __future__ import annotations

from typing import Any

from services.media_generation_types import (
    DEFAULT_AUDIO_FORMAT,
    DEFAULT_IMAGE_SIZE,
    MediaModelRuntime,
)
from services.media_generation_utils import (
    _aspect_ratio_from_size,
    _audio_mime_type,
    _dashscope_multimodal_endpoint,
    _dashscope_size,
    _doubao_size,
    _gemini_base,
    _is_minimax_tts_model,
    _minimax_base,
    _pixel_dimensions,
    _versioned_base,
)


def _image_request(
    *,
    endpoint_provider: str,
    runtime: MediaModelRuntime,
    prompt: str,
    size: str,
    n: int,
    response_format: str,
) -> tuple[str, dict[str, Any]]:
    provider = endpoint_provider
    model = runtime.model
    if provider == "gemini":
        endpoint = f"{_gemini_base(runtime.base_url)}/models/{model}:predict"
        return endpoint, _gemini_image_payload(prompt, size, n)
    if provider == "qwen":
        endpoint = _dashscope_multimodal_endpoint(runtime.base_url)
        return endpoint, _dashscope_image_payload(model, prompt, size, n)
    if provider == "minimax":
        endpoint = f"{_minimax_base(runtime.base_url)}/image_generation"
        return endpoint, _minimax_image_payload(model, prompt, size, n)
    if provider == "grok":
        endpoint = f"{_versioned_base(runtime.base_url or 'https://api.x.ai/v1')}/images/generations"
        return endpoint, _xai_image_payload(model, prompt, size, n, response_format)
    if provider == "doubao":
        endpoint = f"{_versioned_base(runtime.base_url)}/images/generations"
        return endpoint, _doubao_image_payload(model, prompt, size, n)
    endpoint = f"{_versioned_base(runtime.base_url)}/images/generations"
    return endpoint, _openai_image_payload(model, prompt, size, n, response_format)


def _speech_request(
    *,
    endpoint_provider: str,
    runtime: MediaModelRuntime,
    text: str,
    voice: str,
    audio_format: str,
    instructions: str,
    language: str,
) -> tuple[str, dict[str, Any], str]:
    provider = endpoint_provider
    model = runtime.model
    if provider == "gemini":
        endpoint = f"{_gemini_base(runtime.base_url)}/models/{model}:generateContent"
        return endpoint, _gemini_tts_payload(model, text, voice, instructions), "audio/wav"
    if provider == "qwen":
        endpoint = _dashscope_multimodal_endpoint(runtime.base_url)
        return endpoint, _dashscope_tts_payload(model, text, voice, instructions), "audio/wav"
    if provider == "minimax":
        endpoint = f"{_minimax_base(runtime.base_url)}/t2a_v2"
        return endpoint, _minimax_tts_payload(model, text, voice, audio_format), _audio_mime_type(audio_format)
    if provider == "grok":
        endpoint = f"{_versioned_base(runtime.base_url or 'https://api.x.ai/v1')}/tts"
        return endpoint, _xai_tts_payload(text, voice, audio_format, language), _audio_mime_type(audio_format)
    if provider == "glm":
        endpoint = f"{_versioned_base(runtime.base_url)}/chat/completions"
        return endpoint, _glm_voice_payload(model, text), "audio/wav"
    endpoint = f"{_versioned_base(runtime.base_url)}/audio/speech"
    return endpoint, _openai_tts_payload(model, text, voice, audio_format, instructions), _audio_mime_type(audio_format)


def _openai_image_payload(
    model: str,
    prompt: str,
    size: str,
    n: int,
    response_format: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "size": size or DEFAULT_IMAGE_SIZE,
        "n": max(1, min(int(n or 1), 4)),
    }
    if response_format:
        payload["response_format"] = response_format
    return payload


def _xai_image_payload(
    model: str,
    prompt: str,
    size: str,
    n: int,
    response_format: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": max(1, min(int(n or 1), 4)),
        "aspect_ratio": _aspect_ratio_from_size(size),
        "resolution": "1k",
    }
    if response_format:
        payload["response_format"] = response_format
    return payload


def _gemini_image_payload(prompt: str, size: str, n: int) -> dict[str, Any]:
    return {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": max(1, min(int(n or 1), 4)),
            "aspectRatio": _aspect_ratio_from_size(size),
            "imageSize": "1K",
        },
    }


def _dashscope_image_payload(model: str, prompt: str, size: str, n: int) -> dict[str, Any]:
    return {
        "model": model,
        "input": {
            "messages": [{
                "role": "user",
                "content": [{"text": prompt}],
            }],
        },
        "parameters": {
            "size": _dashscope_size(size),
            "n": max(1, min(int(n or 1), 6)),
        },
    }


def _doubao_image_payload(model: str, prompt: str, size: str, n: int) -> dict[str, Any]:
    return {
        "model": model,
        "prompt": prompt,
        "size": _doubao_size(size),
        "n": max(1, min(int(n or 1), 4)),
        "response_format": "b64_json",
    }


def _minimax_image_payload(model: str, prompt: str, size: str, n: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model or "image-01",
        "prompt": prompt[:1500],
        "response_format": "base64",
        "n": max(1, min(int(n or 1), 9)),
        "prompt_optimizer": True,
    }
    dimensions = _pixel_dimensions(size)
    if dimensions:
        payload["width"], payload["height"] = dimensions
    else:
        payload["aspect_ratio"] = _aspect_ratio_from_size(size)
    return payload


def _openai_tts_payload(
    model: str,
    text: str,
    voice: str,
    audio_format: str,
    instructions: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "input": text,
        "voice": voice or "coral",
        "response_format": audio_format or DEFAULT_AUDIO_FORMAT,
    }
    if instructions:
        payload["instructions"] = instructions
    return payload


def _xai_tts_payload(text: str, voice: str, audio_format: str, language: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "text": text,
        "voice_id": voice or "eve",
        "language": language or "auto",
    }
    fmt = (audio_format or DEFAULT_AUDIO_FORMAT).lower()
    if fmt and fmt != DEFAULT_AUDIO_FORMAT:
        payload["output_format"] = {"codec": fmt}
    return payload


def _gemini_tts_payload(model: str, text: str, voice: str, instructions: str) -> dict[str, Any]:
    notes = (instructions or "").strip()
    notes_block = f"Delivery notes: {notes}\n" if notes else ""
    prompt = (
        "Synthesize speech for the following transcript. "
        "Do not read these instructions aloud. Preserve the transcript language naturally. "
        "Inline audio tags in square brackets are performance directions, not literal text. "
        "Use the configured prebuilt voice consistently for the whole transcript; "
        "do not invent alternate character voices unless the transcript explicitly asks. "
        "Keep acting controlled, understated, and natural. For neutral or calm dialogue, keep pitch, "
        "energy, and emotional color stable; avoid melodrama, theatrical sarcasm, or exaggerated emphasis "
        "unless an inline audio tag explicitly requires it.\n\n"
        "### DIRECTOR'S NOTES\n"
        f"{notes_block}\n"
        "### TRANSCRIPT\n"
        f"{text}"
    )
    return {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": voice or "Kore"},
                },
            },
        },
        "model": model,
    }


def _dashscope_tts_payload(model: str, text: str, voice: str, instructions: str) -> dict[str, Any]:
    if _is_minimax_tts_model(model):
        return _dashscope_minimax_tts_payload(model, text, voice)
    payload = {
        "model": model,
        "input": {
            "text": text,
            "voice": voice or "Cherry",
            "language_type": "auto",
        },
    }
    if instructions:
        payload["parameters"] = {
            "instructions": instructions,
            "optimize_instructions": True,
        }
    return payload


def _dashscope_minimax_tts_payload(model: str, text: str, voice: str) -> dict[str, Any]:
    return {
        "model": model,
        "input": {
            "text": text,
            "voice_setting": {
                "voice_id": voice or "English_expressive_narrator",
                "speed": 1,
                "vol": 1,
                "pitch": 0,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
            "subtitle_enable": False,
        },
    }


def _minimax_tts_payload(model: str, text: str, voice: str, audio_format: str) -> dict[str, Any]:
    fmt = (audio_format or DEFAULT_AUDIO_FORMAT).lower()
    return {
        "model": model or "speech-2.8-hd",
        "text": text,
        "stream": False,
        "language_boost": "auto",
        "output_format": "hex",
        "voice_setting": {
            "voice_id": voice or "English_expressive_narrator",
            "speed": 1,
            "vol": 1,
            "pitch": 0,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": fmt,
            "channel": 1,
        },
    }


def _glm_voice_payload(model: str, text: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [{"type": "text", "text": text}],
        }],
        "stream": False,
    }
