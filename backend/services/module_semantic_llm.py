"""LLM helpers for module semantic parsing."""

from __future__ import annotations

import json
import re
import asyncio
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from llm import ChatMessage, build_client
from llm.factory import OPENAI_COMPAT_PROVIDERS
from services import admin_config, model_pool

SEMANTIC_LLM_TIMEOUT_SECONDS = 180


async def call_text(
    db: AsyncSession,
    system_prompt: str,
    user_content: str,
) -> str:
    resolved = await _resolve_model(db)
    if resolved is None:
        return ""
    provider, model, api_key, base_url = resolved
    messages = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=user_content),
    ]
    try:
        if provider in OPENAI_COMPAT_PROVIDERS:
            try:
                return await asyncio.wait_for(
                    _chat_completion_text(model, api_key, base_url, messages),
                    timeout=SEMANTIC_LLM_TIMEOUT_SECONDS,
                )
            except (asyncio.TimeoutError, Exception):
                return ""
        client = build_client(provider, model, api_key, base_url)
    except (TypeError, ValueError):
        return ""
    try:
        return await asyncio.wait_for(
            _collect_stream_text(client, messages),
            timeout=SEMANTIC_LLM_TIMEOUT_SECONDS,
        )
    except (asyncio.TimeoutError, Exception):
        return ""


async def _collect_stream_text(client, messages: list[ChatMessage]) -> str:
    chunks: list[str] = []
    async for chunk in client.stream_chat(messages):
        if chunk.delta:
            chunks.append(chunk.delta)
    return "".join(chunks).strip()


async def _chat_completion_text(
    model: str,
    api_key: str,
    base_url: str,
    messages: list[ChatMessage],
) -> str:
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": m.role, "content": m.content} for m in messages],
    )
    return (response.choices[0].message.content or "").strip()


async def call_json(
    db: AsyncSession,
    system_prompt: str,
    user_content: str,
) -> dict[str, Any] | None:
    text = await call_text(db, system_prompt, user_content)
    if not text:
        return None
    raw = _strip_fence(text)
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


async def _resolve_model(db: AsyncSession) -> tuple[str, str, str, str] | None:
    entry = await model_pool.get_default(db)
    if entry is None:
        return None
    saved = admin_config.get_provider(entry.provider) or {}
    api_key = saved.get("api_key", "") or _provider_default_key(entry.provider)
    base_url = saved.get("base_url", "") or _provider_default_base_url(entry.provider)
    return entry.provider, entry.model, api_key, base_url


def _provider_default_key(provider: str) -> str:
    if provider == "debug":
        return "codex-relay-local"
    return ""


def _provider_default_base_url(provider: str) -> str:
    if provider == "debug":
        return "http://127.0.0.1:18888/v1"
    return ""


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|markdown|md)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()
