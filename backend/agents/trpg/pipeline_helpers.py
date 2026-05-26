"""TRPG LLM client helpers for chatrpg.

This is a stripped-down version of chatlab's `pipeline_helpers` — just enough
for the dice-IR compiler / extractor pieces to work. ChatLab's variants pull
in usage tracking, gemini shim, qwen quirks, etc. that aren't relevant to
chatrpg's open-source single-user runtime.
"""

from __future__ import annotations

from typing import Any, Dict

import httpx
from openai import AsyncOpenAI

from core.config import get_settings


def get_session_ruleset(session: Any) -> Any:
    """Resolve the runtime ruleset attached to a TRPG session.

    chatlab uses this to bridge cached SimpleNamespace proxies. chatrpg V1
    has no game-time session pipeline yet, so we fall back to whatever the
    ORM relationship returns. The function exists so coc_runtime can import
    it without paying for the chatlab session-cache machinery.
    """
    if session is None:
        return None
    return getattr(session, "ruleset", None) or getattr(session, "_ruleset", None)


def apply_trpg_request_defaults(request_kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """No-op in chatrpg.

    chatlab applies model-specific kwargs (e.g. disable thinking on
    qwen3.5-flash). chatrpg defaults to codex-relay's gpt-5.5 which doesn't
    need any special handling, so we pass through unchanged. Kept as a function
    so the compiler/extractor imports are byte-identical to the chatlab files
    that get sync'd between the two repos.
    """
    return request_kwargs


def build_trpg_client(base_url: str, api_key: str) -> AsyncOpenAI:
    """Construct an AsyncOpenAI client with TRPG-appropriate timeouts.

    The dice-IR compiler can take >2 minutes on a full rulebook, so we use
    generous read timeouts. Connect/write/pool
    timeouts stay short — those are network-shape errors, not model latency.
    """
    s = get_settings()
    timeout = httpx.Timeout(
        connect=s.trpg_llm_connect_timeout_seconds,
        read=s.trpg_llm_read_timeout_seconds,
        write=s.trpg_llm_write_timeout_seconds,
        pool=s.trpg_llm_pool_timeout_seconds,
    )
    return AsyncOpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
    )


def resolve_compiler_api_config(
    *,
    model: str = "",
    base_url: str = "",
    api_key: str = "",
) -> Dict[str, str]:
    """Resolve compiler API config, defaulting to codex-relay.

    Caller can pass any subset; missing fields are filled from settings. This
    is the chatrpg analog to chatlab's `routes.chat_async.get_api_config_for_model`
    plus its `compiler.resolve_compiler_api_config` chain.
    """
    s = get_settings()
    requested = (model or s.dice_ir_compiler_model).strip() or s.dice_ir_compiler_model
    return {
        "model": requested,
        "base_url": (base_url or s.codex_relay_base_url).rstrip("/"),
        "api_key": api_key or s.codex_relay_api_key,
    }
