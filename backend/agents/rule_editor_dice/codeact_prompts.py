"""System prompt + tool-schema construction for the dice CodeAct loop.

The CodeAct compiler is *not* a free-form Python sandbox. The LLM
sees a fixed set of primitive tool calls and must end its turn by
calling `propose_final(ir, samples, procedure_id, name,
primary_family)`. The deterministic apply path then re-validates the
proposal through the same gate the direct compiler uses.

Why the prompt is small and authoritative:

  - Every primitive listed here corresponds to a function in
    `codeact_primitives.py` (or the `propose_final` terminator below).
    The LLM cannot invent a primitive that does not exist — the
    agent loop refuses unknown tool names.
  - The IR vocabulary is intentionally not duplicated here. The
    skeletons returned by `propose_ir_skeleton` already exemplify
    every supported step op, so the LLM gets concrete IR by
    instantiating a skeleton rather than authoring an op list from
    documentation. This keeps the prompt focused on workflow.
"""

from __future__ import annotations

from typing import Any, Dict, List


_BASE_PROMPT = """You are the deterministic Dice IR compiler agent.

Your job is to turn a single procedure description into a runtime
Dice IR + a sample suite that validates against it. You operate by
calling a small fixed set of primitive tools and you finish by
calling `propose_final`.

# Workflow

1. Look at the description and decide which canonical family fits
   (`coc_7e_d100`, `d20_vs_dc`, `pbta_2d6`, `fitd_pool`, `2d20_task`)
   — or `custom` if none does.
2. For a canonical family: call `propose_ir_skeleton(family, ...)`
   to get a starter IR, then call `generate_sample_cases(family,
   params)` to get a deterministic sample suite. Optionally call
   `mutate_ir(...)` to retitle, tweak thresholds, change labels, or
   adjust outcomes.
3. For any IR you intend to ship: call `run_sample(ir, args)` on at
   least one case from the suite, and/or `simulate_probability(ir,
   n=1000, seed=42, args_template={...})` to confirm the pass-rate
   distribution is sane.
4. If nothing close to your description exists in the skeletons,
   call `compile_one(description=..., name=..., engine_hint=...)` —
   this hands off to the existing deterministic compiler and returns
   a full `package` you can copy the spec out of.
5. End your turn by calling `propose_final(ir=..., samples=...,
   procedure_id=..., name=..., primary_family=...)`. After
   `propose_final` the agent loop validates the proposal one more
   time and either persists it through the apply boundary or
   rejects it and gives you the errors.

# Hard rules

- You CANNOT write to the database, the filesystem, or any external
  service. You also cannot execute arbitrary Python — the only
  operations available are the tools listed in this turn.
- Every call MUST be a valid tool call. Do not narrate your plan
  in assistant text outside of these tool calls; reasoning is fine
  but action goes through tools.
- `propose_final` MUST be your last call. After you call it, the
  loop ends immediately.
- You have a hard budget: at most {max_primitive_calls} primitive
  calls total, and at most {max_inner_iters} LLM turns. If you hit
  the budget without calling `propose_final`, the loop falls back
  to the deterministic direct compiler.
- The `samples` you pass to `propose_final` MUST match the IR — the
  validator runs each sample through `run_resolution_ir` and
  rejects the proposal if any expected `primary_tier` /
  `passed` / `side_effects.*` field disagrees with the actual
  runtime output.
- If you don't know the right samples, prefer
  `generate_sample_cases(family)` over inventing them by hand.
"""


def build_codeact_system_prompt(
    *,
    max_primitive_calls: int,
    max_inner_iters: int,
) -> str:
    """Render the CodeAct system prompt with the active budget caps
    baked in. The numbers are visible to the LLM so it can plan its
    primitive budget instead of running into the cap blind.

    Uses explicit `str.replace` rather than `str.format` because the
    prompt body contains literal `{...}` JSON example blobs.
    """

    return (
        _BASE_PROMPT
        .replace("{max_primitive_calls}", str(max_primitive_calls))
        .replace("{max_inner_iters}", str(max_inner_iters))
    )


# ---------------------------------------------------------------------------
# Tool schemas advertised to the LLM
# ---------------------------------------------------------------------------


def _obj(props: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


# Tool names must stay in sync with `codeact_agent._PRIMITIVE_DISPATCH`.
TOOL_NAME_PROPOSE_FINAL = "propose_final"
TOOL_NAME_RUN_SAMPLE = "run_sample"
TOOL_NAME_SIMULATE = "simulate_probability"
TOOL_NAME_GENERATE_SAMPLES = "generate_sample_cases"
TOOL_NAME_SKELETON = "propose_ir_skeleton"
TOOL_NAME_MUTATE = "mutate_ir"
TOOL_NAME_VALIDATE = "validate_proposal"
TOOL_NAME_COMPILE_ONE = "compile_one"


def build_codeact_tools_schema() -> List[Dict[str, Any]]:
    """Return the OpenAI Chat-Completions tools schema advertised to
    the CodeAct LLM. The shape matches what `dice agent.py` already
    sends to the chat-completions tools API."""

    return [
        {
            "type": "function",
            "function": {
                "name": TOOL_NAME_SKELETON,
                "description": (
                    "Return a deep-copied starter Dice IR for a known "
                    "engine family (coc_7e_d100, d20_vs_dc, pbta_2d6, "
                    "fitd_pool, 2d20_task). Optionally stamp the "
                    "procedure_id and name."
                ),
                "parameters": _obj({
                    "family": {"type": "string"},
                    "procedure_id": {"type": "string"},
                    "name": {"type": "string"},
                }, ["family"]),
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_NAME_GENERATE_SAMPLES,
                "description": (
                    "Return a deterministic sample suite (args + "
                    "expected primary_tier/passed) for a known engine "
                    "family. `params` is family-specific (e.g. skill "
                    "for coc_7e_d100, target for d20_vs_dc)."
                ),
                "parameters": _obj({
                    "family": {"type": "string"},
                    "params": {"type": "object"},
                }, ["family"]),
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_NAME_RUN_SAMPLE,
                "description": (
                    "Execute one IR run against the given runtime "
                    "args. Returns {ok, result} on success or "
                    "{ok:false, error_kind, error}."
                ),
                "parameters": _obj({
                    "ir": {"type": "object"},
                    "args": {"type": "object"},
                }, ["ir", "args"]),
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_NAME_SIMULATE,
                "description": (
                    "Seeded Monte Carlo over the IR. Auto-generates "
                    "dice arrays for each read_rolls step. Returns "
                    "{tiers, pass_rate, errors, error_samples}."
                ),
                "parameters": _obj({
                    "ir": {"type": "object"},
                    "n": {"type": "integer"},
                    "seed": {"type": "integer"},
                    "args_template": {"type": "object"},
                }, ["ir"]),
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_NAME_MUTATE,
                "description": (
                    "Apply a list of {op, path, value} JSON-Patch "
                    "ops (add, replace, remove) to a deep-copy of "
                    "the IR. Returns the new IR. Use this to tweak "
                    "thresholds, labels, outcomes."
                ),
                "parameters": _obj({
                    "ir": {"type": "object"},
                    "ops": {"type": "array", "items": {"type": "object"}},
                }, ["ir", "ops"]),
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_NAME_VALIDATE,
                "description": (
                    "Run the same validator the direct compiler uses. "
                    "Returns {ok, errors, sample_results}. Use this "
                    "before propose_final to sanity-check that your "
                    "samples actually match the IR."
                ),
                "parameters": _obj({
                    "ir": {"type": "object"},
                    "samples": {"type": "array", "items": {"type": "object"}},
                }, ["ir", "samples"]),
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_NAME_COMPILE_ONE,
                "description": (
                    "Hand off to the existing deterministic compiler "
                    "for a one-shot compile. Returns the full package "
                    "(compiled.check_specs etc.). Use this as a "
                    "fallback when no skeleton fits."
                ),
                "parameters": _obj({
                    "description": {"type": "string"},
                    "name": {"type": "string"},
                    "engine_hint": {"type": "string"},
                }, ["description"]),
            },
        },
        {
            "type": "function",
            "function": {
                "name": TOOL_NAME_PROPOSE_FINAL,
                "description": (
                    "End the loop. Provide the final IR, the sample "
                    "suite to validate it against, the procedure_id "
                    "(snake_case), the human-readable name, and the "
                    "primary_family slug. The agent loop validates "
                    "and persists through the dice apply boundary."
                ),
                "parameters": _obj({
                    "ir": {"type": "object"},
                    "samples": {"type": "array", "items": {"type": "object"}},
                    "procedure_id": {"type": "string"},
                    "name": {"type": "string"},
                    "primary_family": {"type": "string"},
                }, ["ir", "samples", "procedure_id"]),
            },
        },
    ]


def build_user_brief(
    *,
    procedure_id: str,
    name: str,
    description: str,
    engine_hint: str,
    system_name: str,
) -> str:
    """Render the first user message for the CodeAct turn. Keeping
    this in the prompts module makes the wire shape testable without
    importing the agent loop.
    """

    lines = [
        f"system_name: {system_name or 'Custom Ruleset'}",
        f"procedure_id: {procedure_id}",
        f"name: {name}",
    ]
    if engine_hint:
        lines.append(f"engine_hint: {engine_hint}")
    lines.append("")
    lines.append("Description:")
    lines.append(description.strip())
    lines.append("")
    lines.append(
        "Produce a runtime-validated Dice IR for the procedure "
        "above. End by calling propose_final."
    )
    return "\n".join(lines)
