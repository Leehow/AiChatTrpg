"""Setup-time character creation — public facade.

The implementation is split across `character_creator_state`,
`character_creator_context`, `character_creator_prompts`,
`character_creator_llm`, `character_creator_flows_chat`,
`character_creator_flows_card`, and `character_creator_flows_draft`.
This module re-exports the names other parts of the codebase already
import from `services.character_creator`.
"""

from __future__ import annotations

from services.character_creator_context import (
    _build_context,
    _build_context_packet,
    _ruleset_template_json,
    _thinking_events,
)
from services.character_creator_flows_card import (
    generate_character_card,
    stream_generate_character_card,
)
from services.character_creator_flows_chat import (
    chat_character_creation,
    start_character_creation,
    stream_character_creation_chat,
    stream_character_creation_start,
)
from services.character_creator_flows_draft import (
    clear_character_draft,
    confirm_character_card,
    import_character_draft,
)
from services.character_creator_llm import (
    _call_llm,
    _character_output_language,
    _character_summary,
    _extract_json_object,
    _framework_guide_output,
    _language_name,
    _looks_like_card,
    _looks_like_character_ready_summary,
    _provider_default_base_url,
    _provider_default_key,
    _resolve_model,
    _stream_reply_events,
    _strip_ready_marker,
)
from services.character_creator_prompts import (
    _chat_stream_system_prompt,
    _chat_system_prompt,
    _generate_system_prompt,
    _opening_stream_prompt,
    _opening_system_prompt,
)
from services.character_creator_state import (
    CARD_KEY,
    CHAT_KEY,
    POOL_KEY,
    READY_KEY,
    CharacterContext,
    _build_bp_snapshot,
    _chat_messages,
    _copy_setup_state,
    _count_messages,
    _draft_message,
    _format_transcript,
    _load_chat_history,
    _migrate_chat_if_needed,
    _normalize_chat,
    _save_chat_message,
    character_snapshot,
    utc_iso,
)

__all__ = [
    "CARD_KEY",
    "CHAT_KEY",
    "POOL_KEY",
    "READY_KEY",
    "CharacterContext",
    "character_snapshot",
    "chat_character_creation",
    "clear_character_draft",
    "confirm_character_card",
    "generate_character_card",
    "import_character_draft",
    "start_character_creation",
    "stream_character_creation_chat",
    "stream_character_creation_start",
    "stream_generate_character_card",
    "utc_iso",
]
