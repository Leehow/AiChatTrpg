"""Grep-based retrieval agent (faithful port of chatlab's
`agents/grep_retrieval_agent.py`).

The agent runs a small ReAct loop over caller-provided text sources:
    grep_search(keyword) → optional read_source(source_id) → JSON output

Use `GrepRetrievalAgent` with a runtime (build_client + apply_request_defaults
+ extract_json) and a prompt spec. For chatrpg's OpenAI-compat providers,
import the standard runtime helpers from `runtime_openai`.
"""

from .agent import (
    GrepRetrievalAgent,
    run_grep_retrieval_agent,
)
from .core import (
    GrepRetrievalAgentConfig,
    GrepRetrievalPromptSpec,
    GrepRetrievalRuntime,
    SourceLike,
    build_source_map,
    build_system_prompt,
    build_user_prompt,
    format_grep_results,
    format_retrieval_context,
    grep_sources,
    infer_source_type_options,
    read_source,
)

__all__ = [
    "GrepRetrievalAgent",
    "GrepRetrievalAgentConfig",
    "GrepRetrievalPromptSpec",
    "GrepRetrievalRuntime",
    "SourceLike",
    "build_source_map",
    "build_system_prompt",
    "build_user_prompt",
    "format_grep_results",
    "format_retrieval_context",
    "grep_sources",
    "infer_source_type_options",
    "read_source",
    "run_grep_retrieval_agent",
]
