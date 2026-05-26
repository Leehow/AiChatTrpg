"""chatrpg-side wiring for the portable TRPG framework.

This module is **chatrpg-private** — not part of the framework→chatrpg sync.
It is the stable import facade for chatrpg's wiring of the framework adapter
protocols. The actual implementation is split across same-prefix helper
modules for file-size hygiene:

  * ``trpg_framework_adapter_converters`` — ORM ↔ framework dataclass
    converters (chatrpg's GameSession row → SessionState; chatrpg's Ruleset
    row → RulesetData; module dict → ModuleData) plus the inline base64
    scrubber.
  * ``trpg_framework_adapter_ic_prompt`` — long IC-mode GM system prompt and
    mode-dispatch helper.
  * ``trpg_framework_adapter_guide_nudge`` — guide-phase culture / name
    variety nudge text.
  * ``trpg_framework_adapter_manifest`` — companion / chargen / manifest
    index slicing of ``parsed_v6``.

Public surface:

  * ``to_session_state``, ``to_ruleset_data``, ``to_module_data`` — ORM
    converters re-exported for debug scripts.
  * ``ChatrpgRulesetAdapter`` — implements the framework's RulesetAdapter
    Protocol by slicing parsed_v6 directly (no distilled fields like chatlab).
  * ``make_chatrpg_services`` — assembles a TrpgServices bundle for one turn.
  * ``make_chatrpg_inputs`` — assembles TurnInputs from ORM rows.

Compared to chatlab's adapter, chatrpg:
  * Has no resident_prompt / scene_guide / character_creation_pack distillates
    on the session row — everything comes from ruleset.parsed_v6
  * Uses session.character as a single dict (no characters.pc / .npcs split)
  * Has no IC pipeline yet, so most IcContext fields are unused
"""

from __future__ import annotations

from typing import Any

from agents.trpg.framework.adapters import (
    NoOpMultimediaAdapter,
    NoOpRetrievalAdapter,
    SystemClock,
)
from agents.trpg.framework.models import (
    CharacterTemplate,
    FeatureFlags,
    Message,
    ModelConfig,
    RulesetData,
    SessionState,
    StableText,
    TrpgServices,
    TurnInputs,
)

from services.trpg_framework_adapter_converters import (
    to_module_data,
    to_ruleset_data,
    to_session_state,
)
from services.trpg_framework_adapter_guide_nudge import (
    _build_guide_name_variety_text,
)
from services.trpg_framework_adapter_ic_prompt import _resident_prompt_for_mode
from services.trpg_framework_adapter_manifest import (
    _build_manifest_index,
    _companion_content,
    _compose_chargen,
)

__all__ = [
    "ChatrpgRulesetAdapter",
    "make_chatrpg_inputs",
    "make_chatrpg_services",
    "to_module_data",
    "to_ruleset_data",
    "to_session_state",
]


class ChatrpgRulesetAdapter:
    """Slices parsed_v6 directly — no distilled fields to read off the session
    row (chatrpg has none). Output: same StableText shape chatlab produces, so
    the framework BP1 renderer is interchangeable."""

    def get_stable_text(
        self, ruleset: RulesetData, state: SessionState, mode: Any,
    ) -> StableText:
        raw = ruleset.parsed_v6 or {}
        return StableText(
            resident_prompt=_resident_prompt_for_mode(mode),
            # 场景指南 = v6 parser Stage 2 companion block (world_guide.md
            # under worldview, style_guide.md under style_only).
            scene_guide=_companion_content(raw),
            chargen_pack=_compose_chargen(raw),
            # Knowledge manifest INDEX (not full content). The framework
            # renders this under "## Parameter Families"; we intentionally
            # repurpose the slot as a directory of `package_id` and
            # `family_id` so the GM knows what to look up via
            # `[SEARCH_RULES]`. Full bodies stay out of BP1 — they're paged
            # in on demand by `services/trpg_ruleset_search` at marker
            # resolution time. Mirrors chatlab's `Knowledge Manifest Index`
            # block in `build_v6_resident_prompt`.
            parameter_families=_build_manifest_index(raw),
            core_rules_excerpt=str(raw.get("core_rules") or ""),
        )

    def get_chargen_pack(
        self, ruleset: RulesetData, state: SessionState,
    ) -> str:
        return _compose_chargen(ruleset.parsed_v6 or {})

    def get_character_template(
        self, ruleset: RulesetData, state: SessionState,
    ) -> CharacterTemplate:
        raw = ruleset.parsed_v6 or {}
        sheet = raw.get("character_sheet") if isinstance(raw.get("character_sheet"), dict) else {}
        fields = sheet.get("template_json") if isinstance(sheet.get("template_json"), dict) else {}
        if isinstance(fields, dict) and isinstance(fields.get("fields"), list):
            return CharacterTemplate(
                fields=list(fields["fields"]),
                raw_text=str(sheet.get("template_content") or ""),
            )
        return CharacterTemplate(raw_text=str(sheet.get("template_content") or ""))

    def get_guide_variable_text(
        self,
        ruleset: RulesetData,
        state: SessionState,
        *,
        message: str | None,
        recent_history: list[Message],
    ) -> str:
        # Guide-only, conditional nudge: when the player has not manually
        # committed to a name, or explicitly asks the guide to recommend/fill
        # one, provide multicultural naming/background variety. Final JSON
        # generation receives no second naming-policy injection.
        if state.character_ready:
            return ""
        return _build_guide_name_variety_text(
            message=message or "",
            recent_history=recent_history,
            target_language=str(
                (state.setup_state or {}).get("_guide_language") or "",
            ),
        )


def make_chatrpg_services(
    *,
    llm: Any,
) -> TrpgServices:
    """Assemble services for a chatrpg turn. Caller must inject a real
    LlmAdapter; multimedia / retrieval default to NoOp (chatrpg has no
    multimedia subsystem yet)."""
    return TrpgServices(
        llm=llm,
        ruleset=ChatrpgRulesetAdapter(),
        retrieval=NoOpRetrievalAdapter(),
        multimedia=NoOpMultimediaAdapter(),
        clock=SystemClock(),
    )


def make_chatrpg_inputs(
    *,
    orm_session: Any,
    orm_ruleset: Any,
    parsed_module: Any | None,
    user_message: str | None,
    model: ModelConfig,
    chat_history: list[dict[str, Any]] | None = None,
    flags: FeatureFlags | None = None,
    ic_context: Any | None = None,
) -> TurnInputs:
    return TurnInputs(
        session_state=to_session_state(orm_session, chat_history),
        ruleset=to_ruleset_data(orm_ruleset),
        module=to_module_data(parsed_module),
        user_message=user_message,
        model=model,
        flags=flags or FeatureFlags(enable_multimedia=False),
        ic_context=ic_context,
    )
