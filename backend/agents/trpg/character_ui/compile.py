"""Character UI schema compiler entrypoint.

Reads a v6 ruleset's `character_sheet.template_json`, asks the LLM to
compose a primitive-tree layout following the conventions in prompt.py,
validates the tree, and returns an artifact envelope mirroring the
dice_ir compiler's shape (so the same compiling/failed/success stub
pattern works on the frontend).

Schema v2 differs from v1 by replacing `widgets[]` (flat list of
opinionated widgets) with a recursive `tree` of compositional
primitives. The frontend rejects v1 artifacts and prompts a recompile.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from agents.trpg.llm_json import (
    call_llm_json_task,
    extract_json_object,
)

from .prompt import build_system_prompt, build_user_prompt
from .widgets import PRIMITIVE_TYPES

logger = logging.getLogger("chatrpg.character_ui_compiler")

ARTIFACT_SCHEMA_VERSION = "ruleset_character_ui_compiler_artifact_v3"

# Hard cap on tree depth to bound rendering work and reject runaway
# recursion in malformed model output.
MAX_TREE_DEPTH = 12


class CharacterUICompilerError(Exception):
    """Raised when the LLM returns an unusable schema or the template is
    missing. The caller wraps this into a `status=failed` stub.
    """


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_template(parsed_v6: dict[str, Any]) -> tuple[dict[str, Any], str]:
    cs = parsed_v6.get("character_sheet") if isinstance(parsed_v6, dict) else None
    if not isinstance(cs, dict):
        raise CharacterUICompilerError(
            "ruleset has no character_sheet section; nothing to compile",
        )
    tjson = cs.get("template_json")
    if not isinstance(tjson, dict) or not tjson:
        raise CharacterUICompilerError(
            "character_sheet.template_json is missing or empty",
        )
    tmd = ""
    if isinstance(cs.get("template_content"), str):
        tmd = cs["template_content"]
    return tjson, tmd


def _validate_node(node: Any, depth: int, path: str) -> dict[str, Any]:
    """Recurse over the primitive tree, ensuring every node has a known
    type. Children/templates are walked as well. Returns the node with
    keys preserved (the renderer is the source of truth for prop
    semantics — we don't strip extras since the LLM may emit forward-
    compatible hints we don't recognise yet).
    """
    if depth > MAX_TREE_DEPTH:
        raise CharacterUICompilerError(
            f"primitive tree too deep at {path} (max {MAX_TREE_DEPTH})",
        )
    if not isinstance(node, dict):
        raise CharacterUICompilerError(
            f"primitive at {path} is not a JSON object: {type(node).__name__}",
        )
    ntype = node.get("type")
    if ntype not in PRIMITIVE_TYPES:
        raise CharacterUICompilerError(
            f"primitive at {path} has unknown type: {ntype!r}",
        )

    children = node.get("children")
    if children is not None:
        if not isinstance(children, list):
            raise CharacterUICompilerError(
                f"{path}.children must be an array",
            )
        for i, child in enumerate(children):
            _validate_node(child, depth + 1, f"{path}.children[{i}]")

    template = node.get("item_template")
    if template is not None:
        _validate_node(template, depth + 1, f"{path}.item_template")

    return node


def _validate_schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        raise CharacterUICompilerError(
            f"LLM returned non-object schema: {type(schema).__name__}",
        )
    tree = schema.get("tree")
    if tree is None:
        # Backwards courtesy: if the model emitted v1 `widgets[]`, treat
        # that as a single section with the widgets as children — saves
        # one round of retries on the LLM's quirks.
        widgets = schema.get("widgets")
        if isinstance(widgets, list) and widgets:
            tree = {"type": "section", "children": widgets}
        else:
            raise CharacterUICompilerError(
                "schema.tree is missing (and no `widgets` fallback)",
            )

    _validate_node(tree, 0, "tree")

    out: dict[str, Any] = {
        "system": str(schema.get("system") or "generic"),
        "title_path": schema.get("title_path"),
        "subtitle_path": schema.get("subtitle_path"),
        "tree": tree,
    }
    if not isinstance(out["title_path"], (str, type(None))):
        out["title_path"] = None
    if not isinstance(out["subtitle_path"], (str, type(None))):
        out["subtitle_path"] = None
    return out


async def compile_character_ui(
    parsed_v6: dict[str, Any],
    *,
    book_title: str,
    model: str,
    base_url: str,
    api_key: str,
    output_language: str | None = None,
) -> dict[str, Any]:
    """Compile a v6 artifact's character template into a primitive-tree
    UI schema. ``output_language`` controls the language of all section
    titles and field labels (defaults to the artifact's
    ``output_language`` field, then falls back to English).
    """
    template_json, template_md = _extract_template(parsed_v6)

    if not output_language:
        output_language = str(parsed_v6.get("output_language") or "en")

    system_prompt = build_system_prompt(output_language=output_language)
    user_prompt = build_user_prompt(
        book_title=book_title,
        template_json=template_json,
        template_md=template_md,
    )

    raw = await call_llm_json_task(
        stage="character_ui",
        model=model,
        base_url=base_url,
        api_key=api_key,
        system_prefix=system_prompt,
        user_message=user_prompt,
        stream=False,
    )

    try:
        parsed = extract_json_object(raw)
    except Exception as exc:
        raise CharacterUICompilerError(
            f"LLM returned unparseable JSON: {exc}",
        ) from exc

    schema = _validate_schema(parsed)

    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "saved_at": _now_iso(),
        "model": model,
        "output_language": output_language,
        "package": schema,
        "auto_compiled": True,
    }


def build_compiling_stub(*, model: str) -> dict[str, Any]:
    return {
        "status": "compiling",
        "started_at": _now_iso(),
        "model": model,
        "auto_compiled": True,
    }


def build_failed_stub(*, model: str, error: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "failed_at": _now_iso(),
        "model": model,
        "error": error[:500],
        "auto_compiled": True,
    }


def is_compiled_artifact(artifact: dict[str, Any] | None) -> bool:
    """True only for v2 artifacts with a non-empty `tree`. v1 artifacts
    (`widgets[]`) are deliberately rejected so the UI prompts a recompile.
    """
    if not isinstance(artifact, dict):
        return False
    if str(artifact.get("status") or "") in {"compiling", "failed"}:
        return False
    if artifact.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        return False
    package = artifact.get("package")
    if not isinstance(package, dict):
        return False
    tree = package.get("tree")
    return isinstance(tree, dict) and bool(tree.get("type"))
