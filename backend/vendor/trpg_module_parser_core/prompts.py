"""Prompts for the shared TRPG module parser core."""

PARSE_PROMPT = """You are analyzing a TRPG module document. The full text is provided with line numbers (L1, L2, ...).

Your task: identify every TOP-LEVEL section of this module and output a structured JSON.

## What to output

1. **anchor_type** — the module's primary organizational pattern:
   - "location": organized around places (sandbox, open-world)
   - "mission": organized around standalone operations/quests
   - "chapter": organized as sequential narrative chapters
   - "story_arc": organized around story progression / acts

2. **progression** — how players move through the module:
   - "linear": must play playable blocks in document order (chapters, acts, fixed story). Auto-load block #1.
   - "sandbox": players freely choose which block to start / visit next (open locations, quest menu, mission board). Show a selector.
   Rule of thumb: if any playable block can be skipped or chosen out of order without breaking the story → sandbox; otherwise → linear.
   anchor_type "chapter" / "story_arc" is almost always linear; "location" is almost always sandbox; "mission" can be either — read the intro/keeper notes to decide.

3. **guide** — a concise keeper opening guide in **markdown**, used immediately at game start while the full briefing is still being generated asynchronously. Target ~1500–3000 Chinese chars (or equivalent English). Include:
   - One-sentence premise
   - Tone / genre / era
   - Player starting situation (where they are, who they are, what's the hook)
   - 3–5 key NPCs or factions the keeper should know about right away
   - First-scene suggestion (how to open the session)
   Write in the source language of the module. Do NOT dump the whole module plot — this is a quick-start primer, not the full briefing.

4. **selection_rule** — ONLY when `progression == "sandbox"`. Markdown, ≤1000 tokens. Keeper-facing guidance on how to present the playable blocks to players:
   - Recommended entry block(s) and why
   - Any prerequisites / difficulty gating between blocks
   - Difficulty hints per block
   - Hooks or cues to steer players toward specific blocks
   - Anything that shouldn't be offered as a free choice
   Write in the source language of the module. If `progression == "linear"`, omit this field (or return empty string).

5. **sections** — every top-level section, in document order. Each section:
   - **title**: section heading as written (without # prefix)
   - **type**: one of the types below
   - **start_line**: line number where this section begins (the heading line)
   - **end_line**: line number where this section ends (last line before next section)

## Section types

### Playable content
- location: a place players can visit (sandbox/open-world modules)
- mission: a standalone scenario, operation, or quest
- chapter: a narrative chapter (sequential story progression)
- scene: a specific scene or encounter

### Reference / meta
- intro: introduction, preface, how-to-use, content warnings, overview, keeper info
- rules: game mechanics, new rules, custom rules
- npc_list: NPC roster, character descriptions, stat blocks
- map: maps, floor plans, area diagrams
- handout: player handouts, letters, documents
- timeline: chronological event listing

### Appendix (each appendix separately)
- appendix_rules: appendix containing rules, mechanics, chase/combat procedures
- appendix_list: appendix containing NPC stats, monster stats, item lists
- appendix_others: appendix with other material (pre-gen characters, era background, handouts)

## Important rules
- List ONLY top-level sections (major divisions), not every sub-section
- Sections must cover the ENTIRE document with no gaps
- Line numbers must be EXACT — match the L-prefixed numbers in the text
- For appendix sections: list EACH appendix separately with the specific appendix_ subtype
- Summary should be SPECIFIC

Return JSON only (no markdown wrapper):
{
  "anchor_type": "location" | "mission" | "chapter" | "story_arc",
  "progression": "linear" | "sandbox",
  "guide": "## ...\\n(markdown opening guide)",
  "selection_rule": "## ...\\n(markdown; sandbox only, else \"\")",
  "sections": [
    {"title": "...", "type": "...", "start_line": <int>, "end_line": <int>}
  ]
}"""

SPLIT_PROMPT = """Split this TRPG section into chunks of ≤{max_tokens} tokens. Text has line numbers.

Group related sub-sections (nearby locations, chapter phases) into coherent chunks. Cover the entire section, no gaps. Keep parent title as prefix: "<parent> - <description>".

Return JSON only: {{"chunks": [{{"title": "...", "start_line": <int>, "end_line": <int>}}]}}"""

DISTILL_PROMPT = """Distill these TRPG module sections into a keeper's briefing in Markdown format (≤10k tokens).

Write freely — use whatever headings, lists, tables, and structure best fit THIS module. Every module is different; adapt your output to its content rather than following a fixed template.

Prioritize actionable information the keeper needs to run the game: setting overview, key NPCs, timeline/triggers, custom rules, entry points, organizational flow, and running advice. Omit flavor text that doesn't help the keeper.

Output Markdown directly — no JSON wrapper, no code fences."""

INDEX_PROMPT = """Extract a structured JSON table from this TRPG appendix section containing {category}.

For each entry extract:
- name: entity name
- type: what it is (npc, monster, creature, item, spell, etc.)
- brief: one-line description (role, key trait, or purpose)
- stats_summary: key combat/mechanical stats if present (HP, damage, skills), or ""
- line: line number where this entry starts

Return JSON: {{"category": "<what this list contains>", "entries": [{{"name": "", "type": "", "brief": "", "stats_summary": "", "line": <int>}}]}}"""
