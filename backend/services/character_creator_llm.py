"""LLM call orchestration, model resolution, and output parsing for
character creation.

Wraps the chatrpg LLM client behind a small surface used by the chat and
card-generation flows: blocking call, streamed reply with `[CREATE_CHARACTER]`
detection, model-pool resolution, JSON extraction, language naming, and the
framework BP guide bridge.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from llm import ChatMessage, build_client
from orm.models import GameSession, ParsedModule, Ruleset
from services import admin_config, model_pool


async def _call_llm(
    db: AsyncSession,
    messages: list[ChatMessage],
    *,
    temperature: float,
) -> tuple[str, str, str]:
    """Returns (text, provider, model). Callers persist provider/model on
    the assistant message metadata so the UI can display which model wrote
    each reply."""
    provider, model, api_key, base_url = await _resolve_model(db)
    client = build_client(provider, model, api_key, base_url)
    chunks: list[str] = []
    async for chunk in client.stream_chat(messages, temperature=temperature):
        if chunk.delta:
            chunks.append(chunk.delta)
    return "".join(chunks).strip(), provider, model


async def _stream_reply_events(
    db: AsyncSession,
    messages: list[ChatMessage],
    *,
    temperature: float,
):
    provider, model, api_key, base_url = await _resolve_model(db)
    client = build_client(provider, model, api_key, base_url)
    raw_parts: list[str] = []
    async for chunk in client.stream_chat(messages, temperature=temperature):
        if not chunk.delta:
            continue
        raw_parts.append(chunk.delta)
        yield {"type": "content", "content": chunk.delta}

    raw = "".join(raw_parts).strip()
    assistant, ready = _strip_ready_marker(raw)
    yield {
        "type": "_final",
        "assistant": assistant.strip(),
        "ready": ready,
        "provider": provider,
        "model": model,
    }


def _strip_ready_marker(text: str) -> tuple[str, bool]:
    ready = "[CREATE_CHARACTER]" in text or _looks_like_character_ready_summary(text)
    hidden_pattern = re.compile(
        r"\s*<CHATRPG_READY>\s*(true|false)\s*</CHATRPG_READY>\s*",
        re.IGNORECASE,
    )
    match = hidden_pattern.search(text)
    if match:
        ready = ready or match.group(1).lower() == "true"
        text = hidden_pattern.sub("", text).strip()
    return text, ready


def _looks_like_character_ready_summary(content: str) -> bool:
    if not content:
        return False
    text = re.sub(r"\s+", " ", content).strip()
    if len(text) < 120:
        return False
    fields = (
        "姓名", "名字", "职业", "身份", "背景", "属性", "技能", "能力",
        "装备", "关系", "动机", "性格", "生命", "理智", "幸运",
        "name", "occupation", "background", "attribute", "stat",
        "skill", "ability", "equipment", "relationship", "motivation",
    )
    field_hits = sum(1 for term in fields if term.lower() in text.lower())
    ready_phrases = (
        "生成角色卡", "写成角色卡", "完整角色", "完整档案", "最终档案",
        "如果需要调整", "满意的话", "character card", "complete character",
        "final profile", "if you want changes", "generate the card",
    )
    return field_hits >= 4 and any(p.lower() in text.lower() for p in ready_phrases)


async def _resolve_model(db: AsyncSession) -> tuple[str, str, str, str]:
    entry = await model_pool.get_default(db)
    if entry is None:
        rows = await model_pool.list_entries(db)
        entry = next((row for row in rows if row.is_default), rows[0] if rows else None)
    if entry is None:
        raise ValueError("No default model configured.")
    if entry.provider == "mock":
        return "mock", entry.model or "mock-gm", "", ""

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


def _extract_json_object(text: str) -> Any:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    # `raw_decode` parses the first valid JSON object from the start and
    # ignores anything after — handles models that emit a stray trailing
    # `}` or whitespace, which `json.loads` rejects with "Extra data".
    decoder = json.JSONDecoder()
    try:
        obj, _end = decoder.raw_decode(raw)
        return obj
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    if start >= 0:
        try:
            obj, _end = decoder.raw_decode(raw[start:])
            return obj
        except json.JSONDecodeError:
            pass
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _looks_like_card(value: dict[str, Any]) -> bool:
    if "assistant" in value or "card" in value:
        return False
    return any(k in value for k in ("name", "identity", "attributes", "skills", "origin"))


def _character_summary(card: dict[str, Any]) -> str:
    name = (
        card.get("display_name")
        or card.get("name")
        or card.get("character_name")
        or (card.get("identity") if isinstance(card.get("identity"), dict) else {}).get("display_name")
        or (card.get("identity") if isinstance(card.get("identity"), dict) else {}).get("name")
        or (card.get("identity") if isinstance(card.get("identity"), dict) else {}).get("character_name")
        or "Character"
    )
    return f"{name} is ready."


def _character_output_language(ruleset: Ruleset, target_language: str = "") -> str:
    raw = (target_language or "").strip()
    if not raw:
        parsed = ruleset.parsed_v6 if isinstance(ruleset.parsed_v6, dict) else {}
        raw = str(parsed.get("output_language") or "").strip()
    return _language_name(raw) or "the player's selected language"


def _language_name(raw: str) -> str:
    s = (raw or "").strip().lower()
    names = {
        "zh": "Chinese (simplified)",
        "zh-cn": "Chinese (simplified)",
        "zh-hans": "Chinese (simplified)",
        "chinese": "Chinese (simplified)",
        "中文": "Chinese (simplified)",
        "en": "English",
        "english": "English",
        "ja": "Japanese",
        "japanese": "Japanese",
        "日本語": "Japanese",
        "ko": "Korean",
        "korean": "Korean",
        "한국어": "Korean",
        "fr": "French",
        "french": "French",
        "de": "German",
        "german": "German",
        "es": "Spanish",
        "spanish": "Spanish",
        "ru": "Russian",
        "russian": "Russian",
        "it": "Italian",
        "italian": "Italian",
        "pt": "Portuguese",
        "portuguese": "Portuguese",
    }
    if s in names:
        return names[s]
    if raw and len(raw) <= 60:
        return raw.strip()
    return ""


async def _framework_guide_output(
    db: AsyncSession,
    session: GameSession,
    ruleset: Ruleset,
    chat_history: list[dict[str, Any]],
    user_message: str,
    *,
    target_language: str = "",
):
    """Build the framework BpGuideOutput for the current turn. chatrpg uses
    this canonically — the returned thinking_lines, prompt_messages, and
    snapshot drive the streaming reply, while marker parsing happens on the
    raw LLM output.

    Returns (inputs, out)."""
    from services.trpg_framework_adapter import (
        make_chatrpg_inputs, make_chatrpg_services,
    )
    from agents.trpg.framework.bp import build_bp_guide
    from agents.trpg.framework.models import ModelConfig

    class _StubLlm:
        async def stream_chat(self, messages, *, model):
            if False:  # pragma: no cover
                yield None

    parsed_module = None
    setup = session.setup_state if isinstance(session.setup_state, dict) else {}
    module_id = str(setup.get("module_id") or "")
    if module_id and module_id != "__freeform__":
        parsed_module = await db.get(ParsedModule, module_id)
    inputs = make_chatrpg_inputs(
        orm_session=session,
        orm_ruleset=ruleset,
        parsed_module=parsed_module,
        user_message=user_message or None,
        model=ModelConfig(provider="chatrpg", model="chatrpg", temperature=0.0),
        chat_history=chat_history,
    )
    if target_language:
        inputs.session_state.setup_state["_guide_language"] = _language_name(
            target_language,
        ) or target_language
    services = make_chatrpg_services(llm=_StubLlm())
    out = build_bp_guide(inputs, services)
    return inputs, out
