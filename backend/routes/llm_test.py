"""Unified LLM test endpoint.

The debug panel sends a single prompt with the full provider config
attached so we don't need to persist anything before testing. Every
supported provider (openai-compatible family, native gemini, native
claude, mock) goes through the same factory and the same ChatMessage
contract — `build_client` does the routing.

`PROVIDER_DEFAULTS` is the single source of truth for ordering, labels,
default base URLs, default models, and (for codex-relay-style "debug"
providers that ignore the key) a fallback api_key.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from llm import ChatMessage, build_client, list_providers
from services import admin_config

router = APIRouter(prefix="/api/llm", tags=["llm"])


# Order here = order in the dropdown. openai_compat first because it's
# the most flexible "I'll bring my own endpoint" option; debug second
# because it's the in-tree dev default. Ranges are sorted by relevance
# rather than alphabetically.
PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "openai_compat": {
        "label": "OpenAI Compatible",
        "base_url": "",
        "model": "",
        "kind": "openai_compat",
        "default_api_key": "",
    },
    "debug": {
        "label": "Debug (codex-relay)",
        "base_url": "http://127.0.0.1:18888/v1",
        "model": "gpt-5.5",
        "kind": "openai_compat",
        # codex-relay accepts any non-empty value
        "default_api_key": "codex-relay-local",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "kind": "openai_compat",
        "default_api_key": "",
    },
    "claude": {
        "label": "Claude",
        "base_url": "",
        "model": "claude-sonnet-4-6",
        "kind": "native",
        "default_api_key": "",
    },
    "gemini": {
        "label": "Gemini",
        "base_url": "",
        "model": "gemini-2.5-pro",
        "kind": "native",
        "default_api_key": "",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "kind": "openai_compat",
        "default_api_key": "",
    },
    "kimi": {
        "label": "Kimi (Moonshot)",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-32k",
        "kind": "openai_compat",
        "default_api_key": "",
    },
    "qwen": {
        "label": "Qwen (DashScope)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "kind": "openai_compat",
        "default_api_key": "",
    },
    "glm": {
        "label": "GLM (Zhipu)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-plus",
        "kind": "openai_compat",
        "default_api_key": "",
    },
    "doubao": {
        "label": "Doubao (Volc Ark)",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "",
        "kind": "openai_compat",
        "default_api_key": "",
    },
    "grok": {
        "label": "Grok (xAI)",
        "base_url": "https://api.x.ai/v1",
        "model": "grok-2",
        "kind": "openai_compat",
        "default_api_key": "",
    },
    "minimax": {
        "label": "MiniMax",
        "base_url": "https://api.minimax.chat/v1",
        "model": "abab6.5s-chat",
        "kind": "openai_compat",
        "default_api_key": "",
    },
    "mock": {
        "label": "Mock",
        "base_url": "",
        "model": "mock-gm",
        "kind": "mock",
        "default_api_key": "",
    },
}


class ProviderInfo(BaseModel):
    provider: str
    label: str
    kind: str
    default_base_url: str = ""
    default_model: str = ""
    saved_api_key: bool = False
    saved_base_url: str = ""
    saved_model: str = ""


class TestRequest(BaseModel):
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""
    prompt: str
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


class TestResponse(BaseModel):
    text: str
    provider: str
    model: str
    total_ms: int
    first_token_ms: int | None = None
    chars: int = 0
    chars_per_second: float = 0.0
    finish_reason: str | None = None
    error: str | None = None


class ListModelsRequest(BaseModel):
    provider: str
    api_key: str = ""
    base_url: str = ""


class ListModelsResponse(BaseModel):
    provider: str
    models: list[str] = []
    error: str | None = None


def _provider_order() -> list[str]:
    known = list_providers()
    # Use PROVIDER_DEFAULTS' insertion order, then anything from the
    # factory not yet in the dict (defensive — keeps providers visible
    # even if someone forgot to add a label).
    ordered = [p for p in PROVIDER_DEFAULTS if p in known]
    extra = [p for p in known if p not in PROVIDER_DEFAULTS]
    return ordered + extra


def _resolve(
    provider: str, api_key: str, base_url: str
) -> tuple[str, str]:
    """Fill blank api_key/base_url from saved admin config + defaults."""
    api_key = api_key.strip()
    base_url = base_url.strip()
    saved = admin_config.get_provider(provider) or {}
    defaults = PROVIDER_DEFAULTS.get(provider, {})
    if not api_key:
        api_key = saved.get("api_key", "") or str(defaults.get("default_api_key", ""))
    if not base_url:
        base_url = saved.get("base_url", "") or str(defaults.get("base_url", ""))
    return api_key, base_url


@router.get("/providers", response_model=list[ProviderInfo])
async def get_providers() -> list[ProviderInfo]:
    """Return every supported provider with defaults + saved overrides."""
    saved = admin_config.load_all()
    out: list[ProviderInfo] = []
    for name in _provider_order():
        meta = PROVIDER_DEFAULTS.get(name, {
            "label": name,
            "base_url": "",
            "model": "",
            "kind": "openai_compat",
        })
        cfg = saved.get(name) or {}
        models = cfg.get("models") or []
        out.append(
            ProviderInfo(
                provider=name,
                label=str(meta["label"]),
                kind=str(meta["kind"]),
                default_base_url=str(meta["base_url"]),
                default_model=cfg.get("default_model") or str(meta["model"]),
                saved_api_key=bool(cfg.get("api_key"))
                or bool(meta.get("default_api_key")),
                saved_base_url=cfg.get("base_url") or "",
                saved_model=models[0] if models else "",
            )
        )
    return out


@router.post("/test", response_model=TestResponse)
async def test_chat(body: TestRequest) -> TestResponse:
    if body.provider not in list_providers():
        raise HTTPException(400, f"Unknown provider '{body.provider}'")
    if not body.prompt.strip():
        raise HTTPException(400, "prompt is required")
    if not body.model.strip() and body.provider != "mock":
        raise HTTPException(400, "model is required")

    api_key, base_url = _resolve(body.provider, body.api_key, body.base_url)

    try:
        client = build_client(
            provider=body.provider,
            model=body.model or "mock-gm",
            api_key=api_key,
            base_url=base_url,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    messages = [ChatMessage(role="user", content=body.prompt)]

    started = time.perf_counter()
    first_at: float | None = None
    chunks: list[str] = []
    finish: str | None = None
    error: str | None = None
    # Default the LLM-side temperature to a neutral value if the panel
    # didn't send one — production callers will set this themselves.
    temperature = 0.7 if body.temperature is None else body.temperature
    try:
        async for chunk in client.stream_chat(messages, temperature=temperature):
            if chunk.delta:
                if first_at is None:
                    first_at = time.perf_counter()
                chunks.append(chunk.delta)
            if chunk.finish_reason:
                finish = chunk.finish_reason
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    ended = time.perf_counter()
    text = "".join(chunks)
    total_ms = int((ended - started) * 1000)
    first_ms = int((first_at - started) * 1000) if first_at else None
    if first_at and ended > first_at:
        gen_seconds = ended - first_at
        cps = len(text) / gen_seconds if gen_seconds > 0 else 0.0
    else:
        cps = 0.0

    return TestResponse(
        text=text,
        provider=body.provider,
        model=body.model,
        total_ms=total_ms,
        first_token_ms=first_ms,
        chars=len(text),
        chars_per_second=round(cps, 1),
        finish_reason=finish,
        error=error,
    )


# ---------------------------------------------------------------------------
# Model discovery — POST because the body carries a key and may be long.
# ---------------------------------------------------------------------------


@router.post("/models", response_model=ListModelsResponse)
async def list_provider_models(body: ListModelsRequest) -> ListModelsResponse:
    if body.provider not in list_providers():
        raise HTTPException(400, f"Unknown provider '{body.provider}'")
    api_key, base_url = _resolve(body.provider, body.api_key, body.base_url)
    kind = str(PROVIDER_DEFAULTS.get(body.provider, {}).get("kind", "openai_compat"))

    try:
        if body.provider == "mock":
            return ListModelsResponse(provider=body.provider, models=["mock-gm"])
        if not api_key:
            return ListModelsResponse(
                provider=body.provider, models=[], error="api_key required"
            )
        if kind == "openai_compat":
            if not base_url:
                return ListModelsResponse(
                    provider=body.provider, models=[], error="base_url required"
                )
            models = await _list_openai_compat(api_key, base_url)
        elif body.provider == "gemini":
            models = await _list_gemini(api_key)
        elif body.provider == "claude":
            models = await _list_claude(api_key)
        else:
            return ListModelsResponse(
                provider=body.provider, models=[], error=f"unsupported kind '{kind}'"
            )
    except Exception as e:
        return ListModelsResponse(
            provider=body.provider, models=[], error=f"{type(e).__name__}: {e}"
        )

    return ListModelsResponse(provider=body.provider, models=sorted(set(models)))


async def _list_openai_compat(api_key: str, base_url: str) -> list[str]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    page = await client.models.list()
    return [getattr(m, "id", "") for m in page.data if getattr(m, "id", "")]


async def _list_gemini(api_key: str) -> list[str]:
    """List Gemini models via the REST API directly.

    The google-genai SDK's `models.list()` is version-sensitive — older
    pins (e.g. 0.3.x) hit the deprecated /v1/models path and get 501.
    The /v1beta/models REST contract is stable across all live SDKs, so
    we just call it directly.
    """
    import httpx

    url = "https://generativelanguage.googleapis.com/v1beta/models"
    async with httpx.AsyncClient(timeout=15.0) as http:
        res = await http.get(url, params={"key": api_key})
    res.raise_for_status()
    payload = res.json()
    out: list[str] = []
    for m in payload.get("models", []):
        name = m.get("name", "") or ""
        if name.startswith("models/"):
            name = name[len("models/") :]
        # Only models that support generateContent are usable from the
        # chat panel; filter out embeddings, AQA, etc.
        methods = m.get("supportedGenerationMethods") or []
        if name and (not methods or "generateContent" in methods):
            out.append(name)
    return out


async def _list_claude(api_key: str) -> list[str]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    page = await client.models.list()
    return [getattr(m, "id", "") for m in page.data if getattr(m, "id", "")]
