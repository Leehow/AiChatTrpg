"""Strict template-driven character card filter.

After the LLM generates a character card, we walk the card against the
ruleset's `template_json` and drop any keys / skill entries that don't
appear in the template. The motivation: when a CoC-style template lists
10 skills, we don't want the LLM to hallucinate 12 extra ones from its
generic CoC training data — that produces "skills the rules never
intended" and confuses the GM later.

Design:
- Top-level dict keys: only those present in the template are kept.
- Nested dicts (e.g. `attributes`, `derived`, `background`): only template
  keys are kept; LLM-invented siblings are dropped.
- Leaf objects (e.g. `attributes.STR`): NOT filtered. Any sub-field is
  preserved so mechanical_seed runtime fields (`value`, `half`, `fifth`)
  survive even when the template only declared `default`.
- Skills array: only entries whose `name` matches a template-listed name.
- Other arrays (equipment.weapons, equipment.items): kept verbatim.
  Equipment is highly contextual (era / occupation) and the rules-of-
  the-table aren't going to enumerate every possible item up front.

The function returns a tuple `(filtered_card, dropped)` where `dropped`
is an audit list of `{path, reason, value}` entries the caller can log
or surface for debugging.
"""

from __future__ import annotations

from typing import Any


def filter_card_by_template(
    card: dict[str, Any],
    template: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Drop card fields not declared in `template`.

    Pure function — `card` is not mutated. Returns a fresh copy plus an
    audit log of dropped paths.
    """
    if not isinstance(template, dict) or not template:
        # No template — nothing to enforce. Pass card through unchanged.
        return card, []
    dropped: list[dict[str, Any]] = []
    filtered = _filter_dict(card, template, path="", dropped=dropped)
    return filtered, dropped


def _filter_dict(
    card: dict[str, Any],
    template: dict[str, Any],
    *,
    path: str,
    dropped: list[dict[str, Any]],
) -> dict[str, Any]:
    """Filter a card dict against a template dict at the given path.

    Card keys not present in template are dropped. Card keys present in
    template recurse into _filter_value with the matching template node.
    """
    if not isinstance(card, dict):
        return card
    out: dict[str, Any] = {}
    template_keys = set(template.keys())
    for key, value in card.items():
        if key not in template_keys:
            dropped.append({
                "path": f"{path}.{key}" if path else key,
                "reason": "key_not_in_template",
                "value": _summarize_value(value),
            })
            continue
        sub_path = f"{path}.{key}" if path else key
        out[key] = _filter_value(value, template[key], sub_path, dropped)
    return out


def _filter_value(
    value: Any,
    template_node: Any,
    path: str,
    dropped: list[dict[str, Any]],
) -> Any:
    """Filter one value-node pair recursively.

    The dispatch:
    - both dict → recurse via _filter_dict
    - list of objects + template list with shape entries (skills) →
      filter by `name` whitelist
    - everything else → pass through (leaf objects, scalars, mixed
      shapes that we shouldn't try to over-filter)
    """
    # Special case: skills array (or any array of {name: ...} objects
    # where the template lists named entries). We treat the template
    # list's name field as the whitelist.
    if (
        isinstance(value, list)
        and isinstance(template_node, list)
        and _is_named_entry_list(template_node)
    ):
        return _filter_named_array(value, template_node, path, dropped)

    if isinstance(value, dict) and isinstance(template_node, dict):
        # Leaf-object guard: when the template node has typed scalar
        # leaves (e.g. {value: null, derive: "..."}) we don't recurse.
        # Otherwise mechanical_seed-injected sibling fields like
        # `half` / `fifth` would be dropped. Treat as leaf-object iff
        # all template values are scalars (str/int/null).
        if _is_leaf_object_template(template_node):
            return value
        return _filter_dict(value, template_node, path=path, dropped=dropped)

    return value


def _is_leaf_object_template(node: dict[str, Any]) -> bool:
    """A leaf-object template has only scalar / None values.

    Such nodes describe a single field's shape (e.g. `{value: null,
    derive: "POW × 5"}`) and we don't want to enforce its sub-keys —
    runtime numeric helpers (`half`, `fifth`) need to flow through.
    """
    if not node:
        return True
    for v in node.values():
        if isinstance(v, (dict, list)):
            return False
    return True


def _is_named_entry_list(template_list: list[Any]) -> bool:
    """True iff every template entry is a dict with a `name` key.

    That signals the template is enumerating allowed entries (skills,
    spells, etc.). Heterogeneous lists / lists without name fields are
    not whitelisted — we leave them alone.
    """
    if not template_list:
        return False
    for entry in template_list:
        if not isinstance(entry, dict) or "name" not in entry:
            return False
    return True


def _filter_named_array(
    card_list: list[Any],
    template_list: list[dict[str, Any]],
    path: str,
    dropped: list[dict[str, Any]],
) -> list[Any]:
    """Keep only card entries whose `name` is in template's name set."""
    allowed = {
        str(entry.get("name") or "").strip()
        for entry in template_list
        if isinstance(entry, dict) and entry.get("name")
    }
    out: list[Any] = []
    for entry in card_list:
        if not isinstance(entry, dict):
            out.append(entry)
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            # Unnamed entry — keep, can't whitelist
            out.append(entry)
            continue
        if name in allowed:
            out.append(entry)
        else:
            dropped.append({
                "path": f"{path}[name={name!r}]",
                "reason": "name_not_in_template_list",
                "value": _summarize_value(entry),
            })
    return out


def _summarize_value(value: Any, *, max_len: int = 80) -> str:
    """Render a value compactly for the audit log."""
    if isinstance(value, dict):
        keys = list(value.keys())[:6]
        return f"dict({len(value)} keys: {keys})"
    if isinstance(value, list):
        return f"list({len(value)} items)"
    s = str(value)
    return s if len(s) <= max_len else s[:max_len] + "..."


def render_template_schema_hint(template: dict[str, Any]) -> str:
    """Compact textual summary of the template's allowed keys.

    Injected into the LLM prompt so the model knows exactly which
    fields it may fill. Format is intentionally minimal so it fits in
    a system prompt without dominating it.
    """
    if not isinstance(template, dict) or not template:
        return ""
    lines: list[str] = ["## Template field allowlist (CRITICAL)"]
    lines.append(
        "Fill ONLY these fields. Any key you invent outside this list "
        "will be dropped before the card is saved. If you don't have "
        "data for a field, leave it null or empty rather than "
        "fabricating one from generic genre knowledge.",
    )
    for top_key, value in template.items():
        if isinstance(value, dict):
            sub = ", ".join(sorted(value.keys()))
            lines.append(f"- `{top_key}` (object): {sub or '(empty)'}")
        elif isinstance(value, list):
            if _is_named_entry_list(value):
                names = [
                    str(e.get("name", "")) for e in value
                    if isinstance(e, dict)
                ]
                lines.append(
                    f"- `{top_key}` (list, allowed names): "
                    f"{', '.join(filter(None, names)) or '(none)'}",
                )
            else:
                lines.append(f"- `{top_key}` (list)")
        else:
            lines.append(f"- `{top_key}` (scalar)")
    return "\n".join(lines)
