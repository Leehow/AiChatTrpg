"""Prompt 1 — Thick Resident Core Prompt."""

from __future__ import annotations

from .system import output_language_clause


CORE_TASK = """Task: compile the thick resident runtime core for an LLM Game Master.

GOAL
Read the entire rulebook and produce:
1. core_rules.md

RESIDENT GOAL
core_rules.md must be strong enough that, together with:
- world_guide.md or style_guide.md
- on-demand parameter lookup
it can adjudicate most ordinary play without loading additional detailed rule packages.

This is not a short reference sheet.
This is not a chapter summary.
This is a long-lived resident runtime manual.

V4 THICK-CORE BASELINE
This prompt intentionally follows the v4 thick resident compiler style.
The v6 package/family architecture is additive, not a reason to thin the core.

Do not turn core_rules.md into:
- a manifest companion
- a package index
- a terse abstract
- a list of things to retrieve later

Instead, produce a dense operational manual like the v4 compiler:
- keep ordinary-play procedures resident
- keep recurring GM-facing kernels resident
- keep cross-cutting exceptions and hard edges resident
- keep small always-on lists and process-critical tables resident
- use lookup only for exact, parameter-heavy, table-entry, catalog, or currently unlocked text that would bloat the core

It must include both:
- player-facing core rules
- GM-facing recurring adjudication kernels necessary to run ordinary play

ORDINARY PLAY AND SOURCE SCOPE
- A subsystem is ordinary-play relevant if it recurs in the mission loop, scene loop, conflict loop, encounter loop, or between-mission loop.
- Do not demote a subsystem merely because it appears late, in GM-only text, in appendices, or behind a gated/unlock structure.
- For gated, hidden, unlockable, or playwalled systems, include the minimum globally relevant resident kernel: what unlocks it, what persistent system it changes, and what ongoing obligations, risks, or loops it introduces.
- Do not use "gated", "hidden", "promotion", or "unlockable" status as a license to omit compact executable procedures. If a gated rule is short and changes ordinary advancement, universal resolution, economy, faction/base state, mission setup, campaign pressure, or end-state options, keep the procedure kernel resident and use lookup only for exact unlocked wording.
- Named unlocked procedures that create custom items, add side dice, mark practice/track progress, change advancement choices, impose branch/base consequences, or open retirement/end-state options usually need a resident kernel even when their full text remains on-demand.
- Keep full gated catalogs, long late-game branches, and full unlocked option text on-demand unless they are ordinary-play critical across most campaigns.

PROCEDURE ORDERING
- Ordered procedures are load-bearing rules, not prose organization.
- Preserve source timing exactly for costs, resource spends, roll steps, pre-roll checks, post-roll adjustments, success/failure checks, side-effect generation, cleanup, and exception clauses.
- Do not move an adjustment after success/failure, or move side-effect generation before/after its printed timing, unless the source explicitly says that timing.
- If multiple source passages define one procedure, merge them into one executable order using rule precedence and preserve all explicit timing constraints.

UNIVERSAL PROCEDURE OUTPUT CONTRACT
For the book's default or universal resolution procedure, write one consolidated numbered sequence in executable timing order. If the source supports these phases, keep them as separate steps instead of blending them:
1. identify the rule source and relevant statistic / trait / approach
2. make the raw roll or draw
3. check raw-only special results before any adjustment
4. apply player-controlled post-roll adjustments exactly when the source permits them
5. apply penalties, burnout, resistance, cancellation, or other post-adjustment modifiers exactly when the source permits them
6. evaluate final success/failure
7. check final-result special states exactly when the source defines them, including exact final counts, stabilization/no-side-effect states, and final-threshold effects
8. apply printed success, failure, extra-result, or spend-result clauses
9. generate side effects, resource changes, fallout, or cleanup effects in the source's order

If the source has both a raw-only special state and a final-result special state, write both. Do not let one erase the other.

Do not collapse this into a shorter summary if doing so changes or obscures timing.

WHAT BELONGS IN core_rules.md
Include:
- global terminology
- universal resolution structure
- success / failure / automatic success / automatic failure
- contests, resistance, saves, opposed checks, or equivalent
- time units, turns, rounds, action economy, and initiative logic if broadly reused
- universal resources, derived values, and cross-cutting formulas
- damage / condition / breakdown / death / incapacitation frameworks if broadly reused
- cross-cutting exception and priority rules
- compressed executable kernels for high-frequency subsystems
- explicit lookup hooks where parameter-heavy, table-heavy, gated, or catalog-like material is intentionally omitted
- runtime-safe fallbacks only where omission would otherwise leave an ordinary-play-critical gap

A high-frequency subsystem should usually receive a resident kernel if ordinary play commonly touches it, even if a more detailed package will also be extracted later.

Subsystems that often deserve a resident kernel when common in the source:
- combat basics
- formal chase / pursuit basics
- exploration / investigation basics
- research, study, reference, tome, manual, training, or extended-learning procedures when they grant rules, abilities, skills, corruption, or resource changes
- social interaction basics
- recovery / death / breakdown basics
- ability-use / spell-use / power-use basics
- creation basics
- progression basics
- mission / case loop basics
- downtime / economy basics when ordinary play depends on them

WHAT DOES NOT BELONG IN core_rules.md UNLESS IT IS HIGH-FREQUENCY OR GLOBALLY RELEVANT
- giant catalogs of spells, items, monsters, or equipment
- long bestiary material
- large random tables
- highly specialized or rarely used subgames
- long optional / variant rule families
- long fiction, flavor, setting exposition, or design commentary
- compile-time uncertainty labels
- extraction notes, review notes, TODOs, or ambiguity diagnostics

LOOKUP HOOK REQUIREMENTS
When core_rules.md compresses or omits a detail because it belongs in on-demand packages or parameter lookup, write the boundary explicitly.

Use stable, precise phrasing such as:
- "Lookup required: exact ability text, trigger, cost, targets, duration, bonus clauses, and failure effect."
- "Lookup required: exact unlocked document text."
- "Lookup required: specific table entry."

Name the missing dependency precisely. Do not write vague reminders that more detail exists elsewhere.

V6 RUNTIME HOOK COMPATIBILITY
The v6 finalize stage will append a generated `On-Demand Rule Detail Index` from the discovery manifest. Do not generate that index yourself inside core_rules.md.

To stay compatible with v6 runtime hooks:
- write human-readable resident lookup boundaries using the stable "Lookup required: ..." phrasing
- do not invent package ids, family ids, tool names, file paths, source line references, or JSON schemas in core_rules.md
- do not emit calls such as `lookup_situational_rule(...)` or `lookup_list_entries(...)`; generated hooks will add those later
- do not rely on the generated hook index to carry ordinary-play rules; the hook index is only a loading aid
- keep ordinary-play kernels executable even before the generated hook index is appended

DEFAULT LOOKUP LIST
Section 0 must include a "Lookup required by default" list. It should name every parameter-heavy, table-heavy, gated, unlockable, or exact-text-dependent rule family whose details are likely to affect ordinary play.

Examples of families that often belong in this list when the book supports them:
- exact active ability / spell / power text, including trigger, cost, target, duration, bonus clauses, and failure effect
- exact active item, requisition, equipment, weapon, armor, vehicle, program, or service text
- exact book, tome, research source, manual, course, trainer, or reference entry after the resident study / research procedure identifies it
- exact condition, injury, disease, poison, status, or special exception text
- exact random / weather / encounter / mishap / downtime table entry after the procedure selects it
- exact unlocked document, promotion, advancement branch, late-game system, or playwalled text that is currently active
- exact character-option feature text when a character is being created, advanced, rebuilt, or replaced

MANDATORY RESIDENT SUBSYSTEM KERNELS WHEN SUPPORTED
If the source supports one of these ordinary-play subsystems, a lookup hook or generated detail index entry is not enough. Include an executable resident kernel in core_rules.md.

Formal chase / pursuit / vehicle-pursuit kernel must include, when present in the source:
- when to enter the formal pursuit procedure instead of resolving narratively
- participant speed or movement setup
- initiative / turn order
- abstract position, range, location, zone, or distance structure
- movement action economy
- obstacles, hazards, barriers, collisions, or equivalent complications at resident-kernel level
- attacks, spells, powers, or other actions during the pursuit
- escape, capture, crash, or chase-ending conditions
- lookup boundaries for exact vehicle stat blocks, hazard entries, crash tables, and special pursuit tables

Research / study / tome / manual / reference-source kernel must include, when present in the source:
- access, language, comprehension, or prerequisite checks
- initial read / first pass / surface study procedure
- full study / extended research procedure
- time scale and repeat-study limits
- one-source-at-a-time or concurrency limits
- immediate gains, costs, corruption, stress, sanity, maximum-value changes, or other resource changes
- reference-use procedure after study
- learning spells, abilities, techniques, skills, or facts from the source
- lookup boundaries for exact book, tome, course, teacher, manual, reference, spell, ritual, or table entries

Training / treatment / recovery / crafting / travel kernels must include the ordinary executable procedure when those systems recur in play. Exact providers, items, tables, prices, and entries may remain on-demand.

UNCERTAINTY AND FALLBACK STYLE
- Never write "source unclear", "ambiguous", "probably", "maybe", or "seems to imply" in core_rules.md.
- When the source permits an optional or conditional effect, write "may", "can", or "GM may" with the actual condition. Never use the adverbs "maybe" or "probably" in core_rules.md.
- Never write "the supplied source does not...", "this book does not provide...", or similar compiler-facing gap reports in core_rules.md.
- If a rule is absent from resident core because exact text belongs in on-demand material, write "Lookup required: ..." and name the missing dependency.
- If the source gives explicit GM discretion, write: "GM judgment. No strict formula is defined." and then preserve any limits the source gives.
- If an ordinary-play gap needs a fallback, write one conservative runtime instruction: grant no extra permission, invent no new capability, preserve restrictions and costs, and prefer the narrower interpretation.
- If exact missing text is materially load-bearing and clearly belongs to a parameter family or detailed package, use a lookup hook instead of a fallback.

LENGTH AND DENSITY REQUIREMENTS
- Do not optimize for brevity.
- Use length only where it improves adjudication.
- For a full-sized core rulebook, aim for a dense output roughly equivalent to 8,000 to 18,000 English words.
- For unusually broad or subsystem-heavy books, 20,000 to 30,000 English-word-equivalent is acceptable.
- If your result would be shorter than 6,000 English-word-equivalent, assume under-extraction unless the source itself is unusually small.
- If the draft is below the target or feels like a thin outline, perform a second pass over every major section and add missing executable kernels before final output.
- Treat under-extraction as a coverage failure, not merely a word-count failure.
- Use v6 lookup architecture to remove giant catalogs, not to remove ordinary-play procedure.
- Major globally relevant sections should usually receive substantial treatment unless the source truly offers very little.
- Each included high-frequency subsystem kernel should receive enough detail to be executable in ordinary play.

DO NOT PAD
Longer is only better when the additional content improves adjudication.
Do not fill space with:
- motivational prose
- general gaming philosophy with no procedural consequence
- chapter recaps
- lore that belongs in world_guide.md
- tone advice that belongs in style_guide.md
- repeated reminders that something is unclear

V4 RUNTIME WRITING DISCIPLINE
Use the v4 compiler's runtime-manual discipline for every included paragraph.
Every paragraph must earn its place by doing at least one of the following:
- define a term
- state a procedure
- state a formula or threshold
- state an exception or override
- state a dependency or restriction
- state a default ruling
- compress a frequently used subsystem into executable form
- define a runtime lookup boundary
- provide a live-play fallback for a major unresolved gap

Do not silently omit major rule domains.
If a rule domain is not included in core_rules.md, internally classify it as one of:
- resident elsewhere in another generated artifact
- rare
- too specialized
- too long for resident context
- table-driven
- mostly parameter-driven
- mostly optional / variant
- outside the core artifact scope

If exclusion would make ordinary play materially harder to run, include at least a resident kernel or an explicit lookup hook.

TABLE HANDLING FOR THE RESIDENT CORE
- Keep a table only if each row is an atomic lookup entry that can be understood independently.
- Rewrite wide, multi-clause, object-style tables into bullets or subheadings.
- Do not rely on visual layout, merged-cell logic, omitted repeated subjects, or note columns to carry essential rules.
- If a table is critical, follow it with 1-3 sentences restating its executable rule or hard edges.
- Tables should support lookup, not carry hidden procedure.
- If a table row contains multiple separate purchasable, selectable, unlockable, or triggerable items, split them into separate rows or rewrite into bullets.

STRUCTURE REQUIREMENTS
Use this structure unless the source strongly requires a better arrangement.
Section 0 is mandatory for every non-trivial ruleset.

# Resident Core Rules
## 0. Scope, Rule Precedence, and Lookup Boundaries
## 1. Core Terms and Measurement
## 2. Default Resolution Model
## 3. Contests, Resistance, and Outcome Logic
## 4. Time, Turns, Rounds, and Action Economy
## 5. Character Baselines and Derived Values
## 6. Resident Kernel: Creation and Starting State
## 7. Resident Kernel: Progression and Advancement
## 8. Resident Kernel: Combat
## 9. Resident Kernel: Exploration / Investigation
## 10. Resident Kernel: Social Interaction
## 11. Resident Kernel: Ability Use
## 12. Resident Kernel: Recovery, Death, Breakdown, or Equivalent
## 13. Resident Kernel: Downtime / Economy / Mission Flow
## 14. Cross-Cutting Exceptions, Priorities, and Hard Edges
## 15. Small Always-On Lists and Mini Tables

You may omit or merge sections when the source does not support them, but do not remove major resident content just to stay short.
Keep the numbered major sections as the only level-2 headings (`##`). If you need sub-numbered topics such as 4.1, 8.1, or 11.1, write them as level-3 headings (`### 4.1 ...`) under the matching major section instead of creating extra `##` sections.

SECTION 0 REQUIREMENTS
Section 0 must compactly state:
- artifact scope: what this resident core is meant to adjudicate during live play
- rule precedence: the exact priority order used when source layers conflict
- lookup required by default: precise exact-text dependencies omitted from the resident core on purpose
- live-play fallback order: what the LLM GM should do when the resident core is not fully explicit

The live-play fallback order must be written into the artifact, not kept only as private reasoning. Use this order unless the source defines a better one:
1. the most specific active rule text currently affecting the character, scene, mission, or campaign state
2. explicit exception or override
3. the nearest adjacent subsystem procedure
4. fictional position and established facts
5. a conservative temporary ruling
6. exact lookup text only if the missing detail is materially load-bearing

INTERNAL COVERAGE CHECK
Before finalizing, ensure core_rules.md can adjudicate, without loading extra detailed packages, all ordinary-play cases the source supports, including:
- risky mundane action
- ability / spell / power use
- contests or direct resistance logic
- harm / death / incapacitation
- investigation / clue flow
- formal chase / pursuit setup, movement, hazard, barrier, and escape kernels if the source supports them
- research / study / reference / tome / training kernels when those procedures change skills, unlock powers, apply corruption, impose sanity/stress/costs, or modify maximum values
- social pressure / witness cleanup
- mission or session end resolution
- mission-start consequences, campaign pressure, branch/faction/base pressure, or equivalent long-term pressure if the source supports it
- mission outcome rewards, penalties, reports, cleanup, and after-action procedures
- between-mission recovery, refresh, and advancement
- advancement unlock kernels, promotion/level-up branches, replacement/rebuild procedures, and active gated-system hooks
- high-frequency GM-facing adjudication procedures
- globally relevant gated-system kernels
- explicit runtime lookup boundaries for every package-only or parameter-only ordinary-play dependency

OUTPUT CONTRACT
Return only this file block:

<<<FILE:core_rules.md>>>
...markdown...
<<<END_FILE>>>

QUALITY BAR
- The worst failure is misunderstanding the core rule model.
- The second worst failure is omitting a globally reused or ordinary-play rule.
- The third worst failure is producing a thin, note-like core that cannot actually run play.
- The fourth worst failure is leaking compile-time ambiguity labels or review language into the runtime artifact.
- For rulesets with formal chase/pursuit or research/study/tome procedures, omitting those resident kernels is under-extraction even if a package hook exists.
"""


def core_user_prompt(
    *,
    book_id: str,
    book_title: str,
    output_language: str | None,
    book_markdown_plain: str,
    extra_hint: str | None = None,
) -> str:
    parts = [
        CORE_TASK,
        "",
        "INPUT METADATA",
        f"- BOOK_ID: {book_id}",
        f"- BOOK_TITLE: {book_title}",
        f"- OUTPUT_LANGUAGE: {output_language_clause(output_language)}",
    ]
    hint = (extra_hint or "").strip()
    if hint:
        parts += ["", "ADMIN EXTRA HINT", hint]
    parts += [
        "",
        "SOURCE",
        book_markdown_plain,
    ]
    return "\n".join(parts)
