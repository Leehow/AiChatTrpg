"""Atomic primitive catalog for the character-UI compiler.

The previous version defined 13 domain widgets (statGrid, skillTable,
relationshipList, etc.) and asked the LLM to pick from a fixed list. That
locked the renderer into a CoC/D&D-shaped worldview and made every new
ruleset feel cramped.

This version flips it: the LLM gets a small set of compositional atoms
and assembles them itself. Same safety guarantees (no code generation,
typed schema, server-side validation) but the layout space is open —
PBTA playbook moves, BitD action ratings, Lancer hex maps all fit
without backend changes.

Path scoping: paths are resolved relative to the current "scope". The
root scope is the character card. The `list` primitive iterates a path
and pushes each item as a new scope for its item_template subtree.
"""

from __future__ import annotations

from typing import Any


# Each entry: name + description + supported props + example. Folded into
# the system prompt so the LLM can compose layouts without us providing
# domain-specific templates.
PRIMITIVE_CATALOG: list[dict[str, Any]] = [
    {
        "type": "section",
        "description": (
            "Labeled vertical container. Use for top-level groupings "
            "(Vitals, Attributes, Skills, Inventory, Notes). Avoid "
            "nesting sections inside sections — promote nested groups to "
            "siblings instead."
        ),
        "props": {
            "title": "string? — small uppercase heading above children",
            "children": "Primitive[] — stacked vertically",
        },
        "example": {
            "type": "section",
            "title": "Vitals",
            "children": [
                {
                    "type": "bar",
                    "label": "HP",
                    "current_path": "resources.hp.current",
                    "max_path": "resources.hp.max",
                    "color": "red",
                },
            ],
        },
    },
    {
        "type": "text",
        "description": (
            "Display a value or literal string. Either bind to the card "
            "via `value_path`, or hard-code a literal via `text`. Use a "
            "small `label` to caption the value. Empty/missing paths "
            "render nothing — safe to use for optional fields."
        ),
        "props": {
            "value_path": "string? — dot path to a string/number",
            "text": "string? — literal text (no path resolution)",
            "label": "string? — small caption shown before/above the value",
            "size": "string? — 'xs' | 'sm' | 'md' | 'lg' (default 'md')",
            "emphasis": (
                "string? — 'normal' | 'bold' | 'muted' | 'accent' "
                "(default 'normal')"
            ),
            "inline": "boolean? — render inline rather than block (default false)",
        },
        "example": {
            "type": "text",
            "value_path": "identity.name",
            "size": "lg",
            "emphasis": "bold",
        },
    },
    {
        "type": "bar",
        "description": (
            "Single labelled resource bar with current/max readout. "
            "Stack multiple in a section for vitals (HP/MP/Sanity)."
        ),
        "props": {
            "label": "string — short label like 'HP', 'Sanity', 'Stress'",
            "current_path": "string — dot path to current value (number)",
            "max_path": "string — dot path to max value (number)",
            "color": (
                "string? — 'red' | 'blue' | 'green' | 'amber' | 'purple' "
                "| 'teal' (default uses theme accent)"
            ),
        },
        "example": {
            "type": "bar",
            "label": "Sanity",
            "current_path": "resources.sanity.current",
            "max_path": "resources.sanity.max",
            "color": "blue",
        },
    },
    {
        "type": "grid",
        "description": (
            "N-column grid of children. Use for attribute boxes "
            "(STR/DEX/CON in 3 cols), inventory pages, etc. Children "
            "are usually `card` or `text` primitives."
        ),
        "props": {
            "columns": "number — 1 to 4",
            "gap": "string? — 'tight' | 'normal' | 'loose' (default 'normal')",
            "children": "Primitive[]",
        },
        "example": {
            "type": "grid",
            "columns": 3,
            "children": [
                {
                    "type": "card",
                    "tone": "subtle",
                    "children": [
                        {"type": "text", "text": "STR", "size": "xs", "emphasis": "muted"},
                        {"type": "text", "value_path": "attributes.STR", "size": "md", "emphasis": "bold"},
                    ],
                },
            ],
        },
    },
    {
        "type": "list",
        "description": (
            "Iterating list. Resolves `source_path` to an array or "
            "object, then renders `item_template` once per entry with "
            "the entry pushed as the path-resolution scope. Inside the "
            "template, paths are RELATIVE to the item — e.g. for an "
            "array of {name, value, category} entries, use `name` not "
            "`skills.0.name`. When the source resolves to an object (key "
            "→ value), the special path `__key__` resolves to the entry "
            "key inside the template."
        ),
        "props": {
            "source_path": "string — dot path to array or object",
            "item_template": "Primitive — rendered once per entry",
            "group_by": "string? — RELATIVE field to group by (array-only)",
            "sort_by": (
                "string? — RELATIVE field to sort by; use '__key__' for "
                "object sources"
            ),
            "sort_order": "string? — 'asc' | 'desc' (default 'asc')",
            "empty_text": "string? — fallback rendered when source is empty",
        },
        "example": {
            "type": "list",
            "source_path": "skills",
            "group_by": "category",
            "sort_by": "name",
            "item_template": {
                "type": "text",
                "label_path": "name",
                "value_path": "value",
                "size": "sm",
                "inline": True,
            },
        },
    },
    {
        "type": "card",
        "description": (
            "Surface-coloured box wrapping children. Use sparingly: "
            "good for individual attribute boxes inside a grid; bad as "
            "the outer wrapper of every section (the renderer already "
            "wraps the panel)."
        ),
        "props": {
            "tone": "string? — 'default' | 'subtle' (default 'default')",
            "children": "Primitive[]",
        },
        "example": {
            "type": "card",
            "tone": "subtle",
            "children": [
                {"type": "text", "text": "INT", "size": "xs", "emphasis": "muted"},
                {"type": "text", "value_path": "attributes.INT", "size": "md", "emphasis": "bold"},
            ],
        },
    },
    {
        "type": "image",
        "description": (
            "Image element with placeholder fallback when path is empty. "
            "Use once near the top for a portrait, or inside list "
            "templates for per-item icons/avatars."
        ),
        "props": {
            "src_path": "string — dot path to image URL",
            "alt_path": "string? — dot path to alt text",
            "aspect": (
                "string? — 'square' | 'portrait' | 'landscape' "
                "(default 'square')"
            ),
        },
        "example": {
            "type": "image",
            "src_path": "identity.portrait_url",
            "aspect": "portrait",
        },
    },
    {
        "type": "tags",
        "description": (
            "Inline chip list. The source_path must resolve to a "
            "string[]; non-string entries are coerced. Useful for "
            "traits, tags, conditions, languages."
        ),
        "props": {
            "source_path": "string — dot path to a string[]",
        },
        "example": {
            "type": "tags",
            "source_path": "identity.traits",
        },
    },
]


# --------------------------------------------------------------------------
# Compound primitives — opinionated, domain-aware shortcuts that handle the
# 80% case (skill lists, attribute boxes, weapons, features) with sane
# defaults. The LLM is told to prefer these over hand-composing with atoms,
# because hand-composed lists tend to dump every field as inline labels and
# produce visually noisy "data dumps".
# --------------------------------------------------------------------------

COMPOUND_CATALOG: list[dict[str, Any]] = [
    {
        "type": "attributeGrid",
        "description": (
            "Grid of attribute boxes (STR/DEX/CON/INT/WIS/CHA-style core "
            "stats). Each cell shows the attribute name and its main "
            "value, with optional modifier. Use for the 6–9 fixed core "
            "stats; never for skills (too many entries — use skillTable)."
        ),
        "props": {
            "key": "string",
            "title": "string?",
            "source_path": (
                "string — dot path to an object whose entries are the "
                "attributes (key = name, value = numeric or "
                "{value, modifier})"
            ),
            "columns": "number? — 1..4, default 3",
            "value_field": (
                "string? — when entries are objects, which subfield holds "
                "the displayed number (default 'value')"
            ),
            "modifier_field": (
                "string? — when entries are objects, optional smaller "
                "secondary number (e.g. modifier or bonus)"
            ),
        },
        "example": {
            "type": "attributeGrid",
            "key": "core_attrs",
            "title": "Attributes",
            "source_path": "attributes",
            "columns": 3,
        },
    },
    {
        "type": "skillTable",
        "description": (
            "Compact 'name : value' list for skills/proficiencies. ALWAYS "
            "use this for skill collections instead of a hand-composed "
            "list of cards — never enumerate Hard/Extreme/Half/Fifth or "
            "any other derived thresholds in a skill row, those are noise. "
            "Each row is exactly NAME (left) + VALUE (right). Optional "
            "category grouping with alphabetical sort within each group."
        ),
        "props": {
            "key": "string",
            "title": "string?",
            "source_path": (
                "string — dot path to either an array of "
                "{name, value, category?} objects, OR an object whose "
                "key→value pairs are name→value"
            ),
            "name_field": (
                "string? — for array sources, RELATIVE field holding the "
                "skill name (default 'name'; ignored for object sources "
                "where the key IS the name)"
            ),
            "value_field": (
                "string? — RELATIVE field holding the numeric value "
                "(default 'value')"
            ),
            "category_field": (
                "string? — RELATIVE field for grouping (omit for flat "
                "list); rows within each group sort alphabetically by name"
            ),
        },
        "example": {
            "type": "skillTable",
            "key": "skills",
            "title": "Skills",
            "source_path": "skills",
            "category_field": "category",
        },
    },
    {
        "type": "weaponTable",
        "description": (
            "Compact weapon list. Each row shows NAME + SKILL + DAMAGE on "
            "one line; range/attacks/ammo/notes are intentionally hidden "
            "(combat details belong in the rules tab, not the sidebar). "
            "Use this instead of hand-composing weapon cards."
        ),
        "props": {
            "key": "string",
            "title": "string?",
            "source_path": "string — dot path to an array of weapons",
            "name_field": "string? — default 'name'",
            "skill_field": "string? — default 'skill'",
            "damage_field": "string? — default 'damage'",
        },
        "example": {
            "type": "weaponTable",
            "key": "weapons",
            "title": "Weapons",
            "source_path": "equipment.weapons",
        },
    },
    {
        "type": "featureList",
        "description": (
            "Vertical list of features/talents/abilities/spells/bonds. "
            "Each entry shows NAME (bold) and a single short DESCRIPTION "
            "block underneath — no DESCRIPTION/EFFECT/SOURCE/NOTES "
            "label-soup. If you need both an effect and a description, "
            "compose them into one paragraph in description_field."
        ),
        "props": {
            "key": "string",
            "title": "string?",
            "source_path": "string — dot path to an array",
            "name_field": "string? — default 'name'",
            "description_field": "string? — default 'description'",
        },
        "example": {
            "type": "featureList",
            "key": "feats",
            "title": "Features",
            "source_path": "feats_features",
        },
    },
]


PRIMITIVE_CATALOG = PRIMITIVE_CATALOG + COMPOUND_CATALOG
PRIMITIVE_TYPES: tuple[str, ...] = tuple(p["type"] for p in PRIMITIVE_CATALOG)

# Type sets for prompt formatting — the prompt lists compounds first as
# "first choice" and atoms second as "fallback".
COMPOUND_TYPES: tuple[str, ...] = tuple(p["type"] for p in COMPOUND_CATALOG)
ATOM_TYPES: tuple[str, ...] = tuple(
    t for t in PRIMITIVE_TYPES if t not in COMPOUND_TYPES
)

WIDGET_CATALOG = PRIMITIVE_CATALOG
WIDGET_TYPES = PRIMITIVE_TYPES
