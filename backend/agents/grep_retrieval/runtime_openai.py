"""OpenAI-compatible runtime wiring for the grep retrieval agent.

Chatrpg uses a small set of OpenAI-spec providers (openai, deepseek,
qwen, kimi, etc.). This module supplies the three callables the
generic agent needs:

- ``build_openai_client(base_url, api_key)`` — `AsyncOpenAI` instance
- ``apply_openai_request_defaults(kwargs)`` — model-specific tweaks
  (drop temperature for reasoning models; everything else passes through)
- ``extract_json_loose(text)`` — strips ``` fences and best-effort JSON
  parses the model's reply

Use ``make_openai_runtime()`` to grab a ready-built ``GrepRetrievalRuntime``.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from openai import AsyncOpenAI

from .core import GrepRetrievalRuntime


def build_openai_client(*, base_url: str, api_key: str) -> AsyncOpenAI:
    # AsyncOpenAI rejects empty-string base_url and silently falls back to
    # api.openai.com when None — neither is what the caller wants here.
    # Pass None when empty so a caller-supplied default kicks in if any,
    # and let the openai SDK use its env-var fallback otherwise.
    return AsyncOpenAI(api_key=api_key, base_url=(base_url or None))


# Provider → OpenAI-compatible base URL. Used when the chatrpg model-pool
# stores empty base_url (the native Gemini client doesn't need one) but
# the grep agent — which speaks OpenAI tool_calls — needs an explicit
# OpenAI-compat endpoint to avoid landing on api.openai.com by default.
_PROVIDER_OPENAI_COMPAT_BASE_URL: dict[str, str] = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "deepseek": "https://api.deepseek.com/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "doubao": "https://ark.cn-beijing.volces.com/api/v3",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "grok": "https://api.x.ai/v1",
    "openai": "https://api.openai.com/v1",
    "debug": "http://127.0.0.1:18888/v1",
}


def resolve_openai_compat_base_url(provider: str, base_url: str) -> str:
    """If the caller has a base_url, use it; otherwise pick the
    OpenAI-compat endpoint for the named provider. Returns empty string
    when neither is known so the caller can decide whether to abort."""
    if base_url and base_url.strip():
        return base_url.strip()
    return _PROVIDER_OPENAI_COMPAT_BASE_URL.get(str(provider or "").strip().lower(), "")


def _model_rejects_temperature(model: str) -> bool:
    """Mirror ``llm.openai_compat._model_rejects_temperature`` so reasoning
    models (gpt-5.x, o1/o3/o4, codex) don't fail with 400 when the agent
    passes its default temperature through."""
    m = (model or "").lower()
    return m.startswith(("gpt-5", "o1", "o3", "o4")) or "codex" in m


def apply_openai_request_defaults(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Strip ``temperature`` for reasoning models. Everything else passes
    through. The grep agent doesn't set temperature itself, but callers
    sometimes do, and we don't want a stray 400 to abort retrieval."""
    out = dict(kwargs)
    model = str(out.get("model") or "")
    if _model_rejects_temperature(model):
        out.pop("temperature", None)
    return out


def extract_json_loose(text: str) -> Any:
    """Strip ```json fences then json.loads. Falls back to first {...}
    block when the model wrapped its answer in prose."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    s = s.strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", s)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def make_openai_runtime() -> GrepRetrievalRuntime:
    return GrepRetrievalRuntime(
        build_client=build_openai_client,
        apply_request_defaults=apply_openai_request_defaults,
        extract_json=extract_json_loose,
    )
