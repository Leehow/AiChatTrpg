from __future__ import annotations

from .base import LLMClient
from .claude import ClaudeClient
from .gemini import GeminiClient
from .mock import MockClient
from .openai_compat import OpenAICompatClient

OPENAI_COMPAT_PROVIDERS = (
    "openai_compat",  # generic — user provides their own base_url
    "debug",          # local codex-relay (port 18888) — dev default
    "openai",
    "deepseek",
    "kimi",
    "qwen",
    "glm",
    "doubao",
    "grok",
    "minimax",
)

NATIVE_PROVIDERS = ("gemini", "claude")

ALL_PROVIDERS = OPENAI_COMPAT_PROVIDERS + NATIVE_PROVIDERS + ("mock",)


def list_providers() -> list[str]:
    return list(ALL_PROVIDERS)


def build_client(
    provider: str,
    model: str,
    api_key: str,
    base_url: str = "",
) -> LLMClient:
    if provider == "mock":
        return MockClient(model=model or "mock-gm")

    if not api_key:
        raise ValueError(
            f"Provider '{provider}' has no API key configured. "
            f"Set the corresponding *_API_KEY in backend/.env."
        )

    if provider in OPENAI_COMPAT_PROVIDERS:
        if not base_url:
            raise ValueError(f"Provider '{provider}' requires base_url.")
        return OpenAICompatClient(
            provider=provider, model=model, api_key=api_key, base_url=base_url
        )
    if provider == "gemini":
        return GeminiClient(provider=provider, model=model, api_key=api_key)
    if provider == "claude":
        return ClaudeClient(provider=provider, model=model, api_key=api_key)

    raise ValueError(f"Unknown provider '{provider}'. Known: {ALL_PROVIDERS}")
