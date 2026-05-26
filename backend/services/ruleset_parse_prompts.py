"""Prompt templates for the markdown-to-v6 ruleset workflow."""

SYSTEM_PROMPT = """You are a tabletop RPG rulebook compiler.

Convert a complete rulebook into runtime artifacts for an LLM Game Master.
Use only the supplied rulebook text. Preserve procedures, formulas, limits,
thresholds, exceptions, timing order, resource changes, and exact values.
Do not invent missing rules. Prefer dense executable runtime text over summary.

When asked for file output, return only:
<<<FILE:filename>>>
contents
<<<END_FILE>>>

When asked for JSON, the file contents must be strict JSON: no comments, no
trailing commas, double-quoted keys/strings only.
"""

CORE_PROMPT = """Compile the resident core runtime rules.

Output one file block named core_rules.md. The core must be a dense operating
manual that lets an LLM GM run ordinary play. Include universal resolution,
action/time structure, character baselines, resources, advancement, combat,
exploration/investigation, social rules, ability use, recovery, downtime, and
cross-cutting exceptions when supported by the source. Use explicit "Lookup
required: ..." hooks for exact catalogs, tables, powers, equipment, options,
or other parameter-heavy details that should stay on demand.

OUTPUT_LANGUAGE: {language}
BOOK_TITLE: {title}

SOURCE:
{markdown}
"""

COMPANION_PROMPT = """Compile a resident world/style companion.

Output one file block named world_guide.md. Include only setting truths, tone,
GM stance, genre assumptions, default world logic, and presentation guidance
that materially affect running the game. Keep rules in core_rules.md.

OUTPUT_LANGUAGE: {language}
BOOK_TITLE: {title}

SOURCE:
{markdown}
"""

DISCOVERY_PROMPT = """Discover the on-demand v6 artifact plan.

Read the source plus the current core/companion. Output exactly one
knowledge_manifest.json file block. Keep the package set small and useful.
Every package/family/character descriptor must include line_hints as
1-based inclusive ranges into the line-numbered source.

Use this JSON shape:
{{
  "book_id": "{book_id}",
  "book_title": "{title}",
  "world_mode": "fiction",
  "resident": {{"core_file": "core_rules.md", "companion_file": "world_guide.md"}},
  "detailed_rule_packages": [
    {{
      "package_id": "combat",
      "title": "",
      "resident_presence": "kernel",
      "summary": "",
      "load_when": [],
      "contains": [],
      "source_cues": [],
      "line_hints": [[1, 10]],
      "file": "rule_packages/combat.md"
    }}
  ],
  "parameter_families": [
    {{
      "family_id": "weapon",
      "title": "",
      "summary": "",
      "entry_definition": "",
      "family_specific_fields": [],
      "source_cues": [],
      "line_hints": [[1, 10]],
      "file": "parameters/weapon.json"
    }}
  ],
  "character_sheet_package": {{
    "present": true,
    "summary": "",
    "source_cues": [],
    "line_hints": [[1, 10]],
    "template_file": "character_sheet/character_sheet_template.json",
    "guide_file": "character_sheet/character_creation_guide.md"
  }},
  "aliases": []
}}

Limits: at most 8 detailed_rule_packages and 12 parameter_families.
OUTPUT_LANGUAGE: {language}

CURRENT CORE:
{core}

CURRENT COMPANION:
{companion}

SOURCE WITH LINE NUMBERS:
{lined}
"""

PACKAGE_PROMPT = """Extract one detailed rule package.

Output one file block named rule_packages/{package_id}.md. Do not repeat the
resident core at the same abstraction level; add details, edge cases, optional
branches, heavy tables, and exact procedures that are useful only on demand.
Preserve timing, formulas, thresholds, costs, and exceptions.

OUTPUT_LANGUAGE: {language}
BOOK_TITLE: {title}
PACKAGE_DESCRIPTOR:
{descriptor}

CURRENT CORE:
{core}

SOURCE EXCERPT:
{excerpt}
"""

FAMILY_PROMPT = """Extract one parameter family as strict JSON.

Output one file block named parameters/{family_id}.json. Use one object per
entry. Preserve exact values, costs, requirements, tags, durations, notes,
aliases, and rule context. If the material is too small, unstable, or
procedure-dependent for JSON, set should_remain_markdown=true and explain in
summary; still emit valid JSON.

Required outer shape:
{{
  "book_id": "{book_id}",
  "family_id": "{family_id}",
  "title": "",
  "should_remain_markdown": false,
  "schema_used": {{"common_shell_fields": ["id","name","aliases","family","summary","tags","rule_context"], "family_specific_fields": []}},
  "entries": []
}}

OUTPUT_LANGUAGE: {language}
BOOK_TITLE: {title}
FAMILY_DESCRIPTOR:
{descriptor}

SOURCE EXCERPT:
{excerpt}
"""

CHARACTER_PROMPT = """Extract the character sheet package.

Output exactly two file blocks:
1. character_sheet/character_sheet_template.json
2. character_sheet/character_creation_guide.md

The template must be strict JSON and complete enough for character creation
and runtime tracking. Include identity, attributes, derived values, resources,
skills, features, abilities/spells, equipment, currency/progression, statuses,
and notes when supported by the source. The guide must be procedural.

OUTPUT_LANGUAGE: {language}
BOOK_TITLE: {title}
DESCRIPTOR:
{descriptor}

CURRENT CORE:
{core}

SOURCE EXCERPT:
{excerpt}
"""
