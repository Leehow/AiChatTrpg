"""Mock LLM client for testing without real API keys.

Streams a deterministic narrative based on the player's input. Useful for
local end-to-end smoke tests, CI, and demo deployments where you want the
UI to work without provisioning a key. Set provider='mock' on a session.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from .base import CachedPrompt, ChatMessage, StreamChunk


@dataclass
class MockClient:
    provider: str = "mock"
    model: str = "mock-gm"
    api_key: str = ""
    base_url: str = ""

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        extra: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        system_text = "\n".join(m.content for m in messages if m.role == "system").lower()
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        if "complete trpg player character" in system_text or "character card" in system_text:
            narrative = (
                '{"assistant":"档案已经整理完毕。这个人可以进入故事了。",'
                '"card":{"name":"摩根·维尔[Morgan Vale]",'
                '"identity":{"name":"摩根·维尔[Morgan Vale]","original_name":"Morgan Vale"},'
                '"occupation":"Investigator",'
                '"attributes":{"strength":50,"dexterity":55,"intelligence":70},'
                '"skills":{"spot_hidden":60,"library_use":65,"persuade":45},'
                '"equipment":["notebook","flashlight","old revolver"],'
                '"background":"A careful witness with one unanswered debt."}}'
            )
        elif "character creation prologue" in system_text:
            narrative = (
                "密斯卡托尼大学档案馆的地下室里，煤气灯把空白表格照得发黄。"
                "档案管理员推了推眼镜，说：「请坐。既然你来报到了，我们先把身份、来历和能力登记清楚。」\n\n"
                "我们会按当前规则和模组建立一名可以上路的角色：姓名、职业、能力、随身物品、过去牵挂，都会落进档案。"
                "你可以自己定一个具体人物，也可以只告诉我大概是什么样的人，剩下的空白我会按规则补全。\n\n"
                "先告诉我三件事就够了：你想让此人来自什么文化或地方，叫什么名字，"
                "以及他或她为什么会踏上这条危险的路。"
            )
        elif "v4_hidden_memory_test" in last_user:
            narrative = (
                "你掀开203房间的床垫，摸到一枚边缘磨亮的银钥匙。"
                "门外的脚步声停了一下，随即远去。\n\n"
                "[STRUCTURED_EVENTS]{\"events\":["
                "{\"event_id\":\"v4_visible_silver_key\",\"type\":\"clue\","
                "\"actor_id\":\"pc\",\"content\":\"玩家发现203房间床垫下藏着一枚银钥匙。\","
                "\"payload\":{\"clue_id\":\"silver_key_under_203_mattress\","
                "\"points_to\":[\"locked_archive_room\"]},"
                "\"visibility\":{\"player_visible\":true,\"gm_visible\":true}},"
                "{\"event_id\":\"v4_secret_butler_cultist\",\"type\":\"clue\","
                "\"actor_id\":\"gm\",\"content\":\"管家其实是湖畔教团的内应。\","
                "\"payload\":{\"clue_id\":\"butler_is_cultist_agent\","
                "\"points_to\":[\"lakeside_cult\"]},"
                "\"visibility\":{\"player_visible\":false,\"gm_visible\":true}}"
                "]}[/STRUCTURED_EVENTS]"
            )
        else:
            snippet = last_user.split("\n")[-1][:120].strip() or "(no input)"
            narrative = (
                f"The world shifts in response to your action: {snippet} "
                "Smoke curls through the air. A figure in the corner looks up — "
                "you've been noticed. Roll for stealth.\n\n"
                "[ROLL kind=d20 reason=\"stealth check\"]\n"
                "[SET_SCENE id=\"speakeasy_main\" type=\"dialogue\"]\n"
                "[CREATE_NPC name=\"Mysterious Patron\" role=\"observer\"]\n"
            )
        for word in narrative.split(" "):
            await asyncio.sleep(0.02)
            yield StreamChunk(delta=word + " ")
        yield StreamChunk(delta="", finish_reason="stop")

    async def stream_chat_cached(
        self,
        prompt: CachedPrompt,
        *,
        temperature: float = 0.7,
        extra: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """No real cache — flatten to stream_chat for mock parity."""
        flat: list[ChatMessage] = []
        sys_text = "\n\n".join(p for p in (
            prompt.stable_prefix, prompt.semi_stable_context, prompt.variable_suffix,
        ) if p)
        if sys_text:
            flat.append(ChatMessage(role="system", content=sys_text))
        for m in prompt.history:
            if m.role in ("user", "assistant") and m.content:
                flat.append(ChatMessage(role=m.role, content=m.content))
        if prompt.user_message:
            flat.append(ChatMessage(role="user", content=prompt.user_message))
        async for chunk in self.stream_chat(flat, temperature=temperature, extra=extra):
            yield chunk
