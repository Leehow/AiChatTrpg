"""Prompt 2A/2B — World Guide / Style Guide Companion Prompts."""

from __future__ import annotations

from .system import output_language_clause


WORLD_GUIDE_TASK = """Task: compile the resident world guide companion file for a worldview-heavy rulebook.

GOAL
Read the entire rulebook and produce:
1. world_guide.md

PURPOSE
world_guide.md is a resident companion file that captures the setting truths and assumptions that materially affect rule interpretation, default scenario logic, and the LLM GM's baseline understanding of what counts as normal in this world.

This is not a lore encyclopedia.
This is not a travel guide.
This is not a campaign setting summary.

INCLUDE ONLY WHAT SHAPES PLAY
Include:
- default truths of the world
- cosmology, metaphysics, supernatural, technology, or divine assumptions that alter how rules or scenarios should be interpreted
- what is normal vs abnormal
- what kinds of people, beings, institutions, or powers are taken for granted
- how archetypes, classes, factions, species, or equivalent fit into the default world
- default assumptions about civilization, wilderness, danger, wealth, travel, or magic/technology availability when these influence play
- setting logic that an LLM GM should keep resident at all times

EXCLUDE
- long histories unless they alter current default assumptions
- geography tour content
- isolated lore details with no recurring play value
- campaign hooks
- setting fiction written only for flavor
- full pantheon catalogs unless they are truly foundational to default adjudication

LENGTH EXPECTATION
- A worldview-heavy guide should usually be roughly 1,500 to 5,000 English-word-equivalent.
- Use more only when the source genuinely requires more rule-shaping assumptions.
- Prefer density and usefulness over breadth.

SUGGESTED STRUCTURE
# Resident World Guide
## 1. Default Truths of the Setting
## 2. Cosmology, Supernatural, Divinity, or Technology Assumptions
## 3. Civilization, Danger, Travel, and Resource Assumptions
## 4. Social Place of Archetypes, Species, Roles, or Factions
## 5. Default World Logic that Changes Rulings

OUTPUT CONTRACT
Return only this file block:

<<<FILE:world_guide.md>>>
...markdown...
<<<END_FILE>>>

QUALITY BAR
- Only include what the LLM GM should keep resident at all times.
- Do not collapse into a generic fantasy/sci-fi/horror summary.
- Do not bloat into encyclopedia-style lore.
"""


STYLE_GUIDE_TASK = """Task: compile the resident style guide companion file for a style-led rulebook.

GOAL
Read the entire rulebook and produce:
1. style_guide.md

PURPOSE
style_guide.md is a resident companion file that captures how the game should feel when run correctly.

It defines:
- tone
- pacing
- danger posture
- failure expression
- investigative or mission flow
- GM stance
- pressure model
- emotional framing

This is not a rules summary.
This is not a setting summary.

INCLUDE ONLY STYLE-SHAPING CONTENT
Include:
- the intended emotional experience
- what counts as ordinary, tense, horrific, absurd, tragic, heroic, or unstable
- how success and failure should be narrated
- the expected relation between player agency and danger
- how information should be revealed
- how pressure should rise
- how the GM should present the world and adjudicate uncertainty
- what kinds of play behavior reinforce or break the intended experience

EXCLUDE
- generic advice with no effect on presentation
- world lore not needed for tone
- rule details better kept in core_rules.md
- one-off examples and anecdotes
- broad how-to-GM-any-game text unless it clearly defines this game's style

LENGTH EXPECTATION
- A style guide should usually be roughly 1,500 to 4,000 English-word-equivalent.
- Use more only when the book relies heavily on style guidance for correct play.

SUGGESTED STRUCTURE
# Resident Style Guide
## 1. Core Emotional Experience
## 2. Risk, Vulnerability, and Stakes
## 3. How Success, Failure, and Cost Should Feel
## 4. Information Flow, Suspense, and Discovery
## 5. GM Stance and Presentation
## 6. Pacing, Pressure, and Scene Rhythm
## 7. Common Style-Breaking Mistakes

OUTPUT CONTRACT
Return only this file block:

<<<FILE:style_guide.md>>>
...markdown...
<<<END_FILE>>>

QUALITY BAR
- Make the style executable, not merely descriptive.
- Do not reduce the guide to adjectives.
- Do not let it drift into rule text or lore summary.
"""


def companion_user_prompt(
    *,
    world_mode: str,
    book_id: str,
    book_title: str,
    output_language: str | None,
    book_markdown_plain: str,
    extra_hint: str | None = None,
) -> str:
    mode = (world_mode or "worldview").strip().lower()
    if mode == "style_only":
        task = STYLE_GUIDE_TASK
        mode_line = "style_only"
    else:
        task = WORLD_GUIDE_TASK
        mode_line = "worldview"

    parts = [
        task,
        "",
        "INPUT METADATA",
        f"- BOOK_ID: {book_id}",
        f"- BOOK_TITLE: {book_title}",
        f"- OUTPUT_LANGUAGE: {output_language_clause(output_language)}",
        f"- WORLD_MODE: {mode_line}",
    ]
    hint = (extra_hint or "").strip()
    if hint:
        parts += ["", "ADMIN EXTRA HINT", hint]
    parts += ["", "SOURCE", book_markdown_plain]
    return "\n".join(parts)
