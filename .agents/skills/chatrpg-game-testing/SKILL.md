---
name: chatrpg-game-testing
description: "Design, review, or run human-style long-flow gameplay tests for ChatRPG sessions: browser chat, natural player actions, streamed GM replies, dice/check runtime, scene changes, memory, NPC/state updates, HP/stress/condition changes, reload recovery, chapter completion, evidence packs, and gameplay feedback collection. Use when the user asks for game testing, gameplay E2E, human-like player simulation, long campaign/session testing, or TRPG runtime validation."
---

# ChatRPG Game Testing

## Overview

Use this skill to design or assess realistic long-flow gameplay tests for
ChatRPG. The goal is to prove that a normal player can play through meaningful
session continuity with vague actions and human habits, not that one scripted
turn works.

In 组长模式, gameplay test plans, rubrics, reports, and feedback synthesis are
lead-owned non-code work. Creating or editing executable tests, app code,
fixtures, generated contracts, or configuration remains code-affecting work and
must go through the worker gate unless the user explicitly grants a direct-edit
exception.

## Core Protocol

1. Separate `player_script` from `oracle`.
   The script contains only player-facing actions. The oracle contains expected
   scene, state, memory, check-log, network, reload, and debug evidence.

2. Simulate a real player.
   Use short, fuzzy, partial, emotional, and context-dependent actions. Include
   pronouns and references like "that person", "the thing", and "what just
   happened". Do not write procedure, marker, schema, or code into player text.

3. Require a long arc.
   A serious gameplay flow should contain at least opening, social contact,
   investigation, first check, fear/pressure, danger, conflict or chase,
   injury/status change, recovery, clue summary, and next hook. Prefer 30-80
   player turns for full confidence unless the user intentionally scopes down.

4. Use browser-first evidence.
   Operate through the UI when possible. API, DB, logs, and debug endpoints are
   oracle evidence after the user-visible path, not a replacement for it.

5. Prove side effects.
   GM narration is not enough. Checks, markers, memory, scene, NPCs, HP,
   stress, wounds, inventory, clues, and time must have machine-side evidence
   when they are part of the expected behavior.

6. Collect playability feedback.
   Record not only bugs, but also where the GM felt unnatural, overexplained,
   ignored obvious player intent, failed to move the session, or required
   unnatural phrasing.

## Minimum Gameplay Flow

Use this as the default shape unless the user narrows scope:

- Start from a fresh room/session and a known ruleset.
- Create or select a normal-person PC using natural language.
- Enter a chapter with a clear hook.
- Socially question an NPC without exact commands.
- Investigate a location using fuzzy actions.
- Trigger at least one real check and one failure or costly success.
- Trigger fear, stress, sanity, or equivalent pressure.
- Encounter danger, combat, chase, or forced escape.
- Change PC HP, wound, stress, condition, clue, item, or another visible state.
- Change NPC state or location.
- Advance scene and in-world time.
- Refresh or navigate away during or after a streamed GM response.
- Recover or rest.
- Ask for a clue/status recap and verify it matches machine state.
- End the chapter with a next hook.

## Audit Gates

Fail the plan or mark it incomplete if any gate is missing:

- Human input gate: player text is ordinary, vague, and does not leak internals.
- Browser gate: user-visible chat/session behavior is checked in the running
  app when available.
- Dice/check gate: checks have engine evidence: identity, input values, roll,
  outcome, and warnings.
- Marker side-effect gate: internal control markers do not leak to players and
  produce actual side effects.
- State gate: HP/stress/wounds/items/clues/NPC/scene/time changes are visible
  or queryable after the turn.
- Memory gate: important facts persist and are retrieved later without name or
  identity drift.
- Stream/reload gate: refresh or navigation during/after streaming does not
  duplicate messages, lose user input, double-apply state, or leave permanent
  half messages without retry.
- Feedback gate: the report captures naturalness, trust, confusion, pacing, and
  repeated-player-input risk.

## Evidence Pack

Require the final report or test artifact to include:

- Test session/ruleset/character names and IDs.
- Browser URL/ports, steps, screenshots or DOM excerpts.
- The human `player_script` actually sent.
- Message counts before/after refresh or navigation.
- SSE/network summary for streamed turns when relevant.
- Check logs for every real check.
- State diffs for PC, NPC, scene, memory, time, clues, and inventory when
  relevant.
- Public/private memory visibility checks when sensitive GM-only state exists.
- Qualitative playability feedback and severity-ranked bugs.

## References

Read `references/gameplay-long-flow.md` when drafting a full canonical chapter,
player script, oracle table, or feedback rubric.
