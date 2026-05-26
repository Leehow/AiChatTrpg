---
name: chatrpg-rule-editor-testing
description: "Design, review, or run human-style long-flow tests for AiChatTrpg rule editor workflows: rule design agent, ruleset drafting, dice/check editor, character-field alignment, save/publish/versioning, target-rule repair, browser E2E evidence, and feedback collection. Use when the user asks for rule editor testing, ruleset workflow validation, natural-language rule creation tests, dice editor tests, or long-flow human simulation around rule authoring."
---

# AiChatTrpg Rule Editor Testing

## Overview

Use this skill to design or assess realistic long-flow tests for the AiChatTrpg
rule editor. The goal is to prove that a normal user can create, repair, save,
and reuse a playable ruleset through vague natural language, not that one
engineered prompt can pass.

In 组长模式, test plans, rubrics, reports, and feedback synthesis are lead-owned
non-code work. Creating or editing executable tests, app code, fixtures,
generated contracts, or configuration remains code-affecting work and must go
through the worker gate unless the user explicitly grants a direct-edit
exception.

## Core Protocol

1. Separate `player_script` from `oracle`.
   The script contains only ordinary user language. The oracle contains hidden
   expected behavior, state checks, debug endpoints, DB/API evidence, and
   pass/fail rules.

2. Keep user prompts human.
   Use short, vague, incomplete, and sometimes hesitant sentences. Do not put
   internal words such as `parsed_v6`, `dice_ir`, `check_spec`,
   `procedure_id`, marker names, JSON field paths, code, or exact schema
   instructions into the user prompt unless testing explicit expert/debug mode.

3. Require continuity, not a single example.
   A serious rule-editor long-flow should cover initial vague concept,
   incomplete draft detection, user revision, dice/check design, character
   template alignment, save/publish, target-rule edit, repair, and reuse.

4. Validate with dual evidence.
   Human-visible UI must make sense, and machine-side evidence must confirm the
   behavior. A polished assistant reply is not proof that the ruleset is
   complete or executable.

5. Collect UX feedback.
   Record where a normal user would repeat themselves, get stuck, misunderstand
   a save state, distrust the rule output, or need unnatural wording.

## Minimum Rule-Editor Flow

Use this as the default shape unless the user narrows scope:

- Create a fresh draft from a vague premise.
- Ask for a simpler or more specific design using normal language.
- Detect and fix placeholders or missing required rule sections.
- Design dice/check behavior through natural language.
- Verify character-visible fields align with check inputs.
- Save or publish the ruleset and record version identity.
- Create or open a target ruleset edit draft.
- Introduce or discover a rule defect during use.
- Repair the defect through natural language.
- Save over or publish the repair and prove the target now uses the repaired
  version.
- Confirm rule chat, dice chat, draft state, and final ruleset state persist
  across reload/navigation.

## Audit Gates

Fail the plan or mark it incomplete if any gate is missing:

- Natural input gate: main user prompts are ordinary language and do not leak
  internal implementation terms.
- Completeness gate: the final ruleset includes playable loop, character
  creation, fields, check mechanics, combat/danger, recovery, GM guidance, and
  at least minimal NPC/enemy guidance when the target genre needs it.
- Dice execution gate: every claimed check can run through the deterministic
  check engine with inputs, roll trace, outcome, and no silent LLM bypass.
- Field alignment gate: character sheet fields match dice/check inputs; text
  labels such as "trained" or "ordinary" are either mapped explicitly or fail
  loudly.
- Version gate: initial save, repaired save, and target-rule usage have
  traceable version identity, timestamp, hash, or export diff.
- Persistence gate: rule chat, dice chat, draft state, and saved rules survive
  reload/navigation.
- Feedback gate: the report names human friction, ambiguous UI states,
  repeated prompts, and unnatural wording required to make progress.

## Evidence Pack

Require the final report or test artifact to include:

- Test asset names and IDs.
- Browser URL/ports and visible UI checkpoints.
- The human `player_script` actually sent.
- Ruleset export or before/after diff.
- Dice/check evidence: check identity, inputs, roll, outcome, warnings.
- Character-field-to-check-input comparison.
- Rule version evidence before and after repair.
- Persistence/reload observations.
- Qualitative feedback and severity-ranked bugs.

## References

Read `references/rule-editor-long-flow.md` when drafting a full canonical
scenario, oracle table, or feedback rubric.
