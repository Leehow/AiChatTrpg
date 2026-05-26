"""v6 prompt package — one file per v2.0 spec stage.

Prompts are transcribed from doc/模组解析/llm_trpg_rulebook_compiler_spec_and_prompts_v2.md
with one v6-specific extension: discovery.py requires line_hints on
every descriptor so Stage 4-6 can slice narrow excerpts.
"""

from .character import character_user_prompt
from .companion import companion_user_prompt
from .core import core_user_prompt
from .discovery import discovery_user_prompt
from .family import family_user_prompt
from .final import final_user_prompt
from .package import package_user_prompt
from .system import SHARED_SYSTEM, output_language_clause

__all__ = [
    "SHARED_SYSTEM",
    "output_language_clause",
    "core_user_prompt",
    "companion_user_prompt",
    "discovery_user_prompt",
    "package_user_prompt",
    "family_user_prompt",
    "character_user_prompt",
    "final_user_prompt",
]
