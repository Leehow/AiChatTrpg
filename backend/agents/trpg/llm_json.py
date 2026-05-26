"""Shared helpers for OpenAI-compatible structured TRPG LLM calls."""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable, Optional


DEFAULT_STRUCTURED_LLM_MODEL = "gpt-5.5"

OnChunk = Optional[Callable[[str, str], Awaitable[None]]]


class StructuredLLMError(ValueError):
    """A structured LLM task failed before returning usable JSON/text."""


def resolve_llm_api_config(
    *,
    model: str = DEFAULT_STRUCTURED_LLM_MODEL,
    base_url: str = "",
    api_key: str = "",
) -> dict[str, str]:
    """Resolve model/base_url/api_key for an OpenAI-compatible structured call."""

    requested = (model or DEFAULT_STRUCTURED_LLM_MODEL).strip() or DEFAULT_STRUCTURED_LLM_MODEL
    if base_url and api_key:
        return {"model": requested, "base_url": base_url.rstrip("/"), "api_key": api_key}
    try:
        from .pipeline_helpers import resolve_compiler_api_config as _resolve

        cfg = _resolve(model=requested, base_url=base_url, api_key=api_key)
        if cfg and cfg.get("base_url") and cfg.get("api_key"):
            return {
                "model": str(cfg.get("model") or requested),
                "base_url": str(cfg["base_url"]).rstrip("/"),
                "api_key": str(cfg["api_key"]),
            }
    except Exception as exc:
        raise StructuredLLMError(f"failed to resolve API config for {requested}: {exc}") from exc
    raise StructuredLLMError(f"no API config for structured LLM model: {requested}")


def extract_json_object(text: str) -> Any:
    """Parse a JSON object/array from plain or fenced model output."""

    body = (text or "").strip()
    if not body:
        raise StructuredLLMError("empty JSON response")
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", body)
        body = re.sub(r"\s*```$", "", body).strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\{\[]", body):
        try:
            obj, _end = decoder.raw_decode(body[match.start():])
            return obj
        except json.JSONDecodeError:
            continue
    raise StructuredLLMError("could not find valid JSON object in model response")


async def call_llm_json_task(
    *,
    stage: str,
    model: str,
    base_url: str,
    api_key: str,
    system_prefix: str,
    user_message: str,
    stream: bool,
    on_chunk: OnChunk = None,
) -> str:
    """Dispatch one structured LLM call against any OpenAI-compatible endpoint."""

    from .pipeline_helpers import apply_trpg_request_defaults, build_trpg_client

    client = build_trpg_client(base_url=base_url, api_key=api_key)
    messages = [
        {"role": "system", "content": system_prefix},
        {"role": "user", "content": user_message},
    ]
    kwargs = apply_trpg_request_defaults({"model": model, "messages": messages})

    text_parts: list[str] = []
    if stream:
        accumulator = await client.chat.completions.create(stream=True, **kwargs)
        async for chunk in accumulator:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            piece = getattr(delta, "content", None) if delta is not None else None
            if piece:
                text_parts.append(piece)
                if on_chunk:
                    await on_chunk(stage, piece)
        text = "".join(text_parts)
    else:
        resp = await client.chat.completions.create(**kwargs)
        choices = getattr(resp, "choices", None) or []
        text = ""
        if choices:
            msg = getattr(choices[0], "message", None)
            text = (getattr(msg, "content", "") or "") if msg is not None else ""

    if not text:
        raise StructuredLLMError(f"{stage} LLM returned empty response")
    return text
