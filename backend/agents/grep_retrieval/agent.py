"""ReAct loop driver for the grep retrieval agent.

Faithful port of chatlab's `agents/grep_retrieval_agent.py` lines 300-511:
- _build_tools (OpenAI function-calling schema for grep_search / read_source)
- run_grep_retrieval_agent (the actual ReAct loop)
- GrepRetrievalAgent (instance with packaged runtime + prompt spec)

The runtime is provider-agnostic: callers supply `build_client`,
`apply_request_defaults`, `extract_json`. For chatrpg's OpenAI-compat
providers, `runtime_openai.py` provides the standard wiring.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

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


def _build_tools(source_type_options: Tuple[str, ...]) -> List[Dict[str, Any]]:
    normalized = tuple(dict.fromkeys(source_type_options or ("any",)))
    if "any" not in normalized:
        normalized = ("any",) + normalized

    return [
        {
            "type": "function",
            "function": {
                "name": "grep_search",
                "description": (
                    "Search the provided source scope by keyword or short "
                    "regex. Start here to find relevant rules, sections, "
                    "options, or entries."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {
                            "type": "string",
                            "description": (
                                "Keyword, phrase, or short regex to search for."
                            ),
                        },
                        "source_type": {
                            "type": "string",
                            "enum": list(normalized),
                            "description": "Optional source-type filter.",
                        },
                    },
                    "required": ["keyword"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_source",
                "description": (
                    "Read the full text of one source returned by "
                    "grep_search. Use it to confirm exact wording before "
                    "finalizing excerpts."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_id": {
                            "type": "string",
                            "description": (
                                "Exact source_id from grep_search results."
                            ),
                        },
                    },
                    "required": ["source_id"],
                },
            },
        },
    ]


async def run_grep_retrieval_agent(
    *,
    sources: Sequence[SourceLike],
    model: str,
    base_url: str,
    api_key: str,
    runtime: GrepRetrievalRuntime,
    config: GrepRetrievalAgentConfig,
) -> Dict[str, Any] | None:
    client = runtime.build_client(base_url=base_url, api_key=api_key)
    source_map = build_source_map(sources)
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": config.system_prompt},
        {"role": "user", "content": config.user_prompt},
    ]
    tools = _build_tools(config.source_type_options)

    for iteration in range(config.max_iterations):
        if iteration == config.force_output_at:
            messages.append({
                "role": "user",
                "content": (
                    "You have searched enough. Return the final JSON now. "
                    "Do not call more tools."
                ),
            })
        tool_choice = "none" if iteration >= config.force_output_at else "auto"
        kwargs = runtime.apply_request_defaults({
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
        })
        resp = await client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message

        if not msg.tool_calls:
            data = runtime.extract_json((msg.content or "").strip())
            return data if isinstance(data, dict) else None

        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        })

        for tc in msg.tool_calls:
            try:
                args = runtime.extract_json(tc.function.arguments or "") or {}
            except Exception:
                args = {}

            if tc.function.name == "grep_search":
                keyword = str(args.get("keyword") or "").strip()
                source_type = str(args.get("source_type") or "any").strip() or "any"
                if keyword:
                    result = format_grep_results(
                        keyword,
                        grep_sources(
                            sources,
                            keyword,
                            source_type=source_type,
                            max_grep_hits=config.max_grep_hits,
                            max_snippet_chars=config.max_snippet_chars,
                        ),
                    )
                else:
                    result = "Error: empty keyword"
            elif tc.function.name == "read_source":
                source_id = str(args.get("source_id") or "").strip()
                result = (
                    read_source(
                        source_map,
                        source_id,
                        max_source_chars=config.max_source_chars,
                    )
                    if source_id
                    else "Error: empty source_id"
                )
            else:
                result = f"Unknown tool: {tc.function.name}"

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    return None


class GrepRetrievalAgent:
    """Reusable grep-search ReAct agent with packaged runtime + prompts."""

    def __init__(
        self,
        *,
        runtime: GrepRetrievalRuntime,
        prompt_spec: GrepRetrievalPromptSpec,
    ) -> None:
        self.runtime = runtime
        self.prompt_spec = prompt_spec

    async def retrieve(
        self,
        *,
        message: str,
        recent_context: str,
        sources: Sequence[SourceLike],
        model: str,
        base_url: str,
        api_key: str,
        seed_terms: str = "",
        scope_hints: Sequence[str] = (),
        extra_sections: Sequence[Tuple[str, str]] = (),
        source_type_options: Tuple[str, ...] | None = None,
        override_system_prompt: str | None = None,
        override_user_prompt: str | None = None,
    ) -> Dict[str, Any] | None:
        config = GrepRetrievalAgentConfig(
            system_prompt=override_system_prompt or build_system_prompt(self.prompt_spec),
            user_prompt=override_user_prompt or build_user_prompt(
                message=message,
                recent_context=recent_context,
                sources=sources,
                seed_terms=seed_terms,
                scope_hints=scope_hints,
                extra_sections=extra_sections,
            ),
            source_type_options=source_type_options or infer_source_type_options(sources),
        )
        return await run_grep_retrieval_agent(
            sources=sources,
            model=model,
            base_url=base_url,
            api_key=api_key,
            runtime=self.runtime,
            config=config,
        )

    def format_context(
        self,
        payload: Dict[str, Any] | None,
        *,
        sources: Sequence[SourceLike] | None = None,
        source_map: Dict[str, Dict[str, Any]] | None = None,
        heading: str | None = None,
        max_sources: int | None = None,
    ) -> str:
        resolved_map = source_map or build_source_map(sources or [])
        return format_retrieval_context(
            payload,
            resolved_map,
            heading=heading or self.prompt_spec.result_heading,
            max_sources=max_sources or self.prompt_spec.max_result_sources,
        )
