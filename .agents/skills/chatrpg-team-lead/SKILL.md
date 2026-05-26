---
name: chatrpg-team-lead
description: Coordinate ChatRPG work in 组长模式/team-lead mode. Use when the user selects or asks for 组长模式, team lead mode, worker orchestration, Claude Code delegation, multi-agent implementation, parallel task breakdown, review-and-revision loops, or coordinated validation in the <repo-root> repository.
---

# ChatRPG Team Lead

## Overview

Use this skill as the operating playbook for ChatRPG 组长模式. It helps Codex
break work into owned tasks, brief workers, review their output, and verify the
final result while preserving the repository-level hard gates in `AGENTS.md`.

This skill complements `AGENTS.md`; it never relaxes the rule that Codex must
not directly mutate code-affecting files in 组长模式 unless the user explicitly
grants a narrow exception in the current turn. It also preserves the opposite
boundary: research, discussion, doc writing/editing, process design, final
reports, and single-lane validation are lead-owned by default and should not be
delegated just to perform the ritual of delegation.

Within this skill, "worker", "小兵", "subagent", "delegate", "parallel agent",
and "跟你的小兵讨论" mean Claude Code workers using the selected worker backend.
The default backend is `runclaude` in a TTY. Approved low-observability Claude
Code backends may be used when the criteria in `AGENTS.md` are met. Do not call
Codex `spawn_agent` or use Codex subagents as ChatRPG 组长模式 workers unless the
user explicitly requests that exception in the current turn and Codex states
that it is outside normal worker routing.

When entering 组长模式 in a fresh session, output the activation notice defined
in `AGENTS.md` before planning, dispatching, or calling any delegation tool, so
that "小兵" cannot be misread as a Codex subagent request. If the mode is
already active, use the short reminder from `AGENTS.md` when useful.

## Lead Workflow

1. Confirm the mode and scope.
   Read `AGENTS.md` and `CLAUDE.md`, confirm the task is in
   `<repo-root>`, and check whether the user requested
   analysis-only work or actual changes.

2. Classify the work.
   First decide whether this is lead-owned non-code work, code-affecting work,
   or multi-lane validation. For research, discussion, doc writing/editing,
   process design, final reports, and one focused validation check, do the work
   directly as the lead. For code-affecting implementation, debugging,
   configuration, or test-file edits, keep direct Codex edits off the table
   unless the user explicitly allowed them in the current turn.

3. Establish the native plan/goal layer for long-running work.
   For non-trivial or long-running 组长模式 tasks, discuss the final product
   shape, acceptance criteria, non-goals, worker/session lanes, lead-owned
   lanes, validation lanes, blockers, risks, and decision points with the user
   before dispatch. Prefer Codex `/plan` for the reviewable plan and `/goal`
   when available for long-horizon continuity. For multi-turn initiatives that
   need durable Done / Not Done memory across handoffs, also open or update an
   Active Plan Ledger entry under `docs/active-plans/<work_id>.md` before
   dispatching the next worker; if a `work_id` is already in play, read that
   file first and pass the `work_id` into the worker marker. For approved
   epics, use the lightweight four-document pattern under
   `docs/epics/<epic_id>/` when it helps: `Prompt.md`, `Plan.md`,
   `Implement.md`, and `Documentation.md`.
   Small tasks, pure discussion, research-only work, doc-only updates, and one
   focused validation check can use a short inline goal summary instead.
   Treat `/goal` as a Claude Code completion condition that starts a turn
   immediately, not as a passive note. Because the completion evaluator only
   sees evidence displayed in the conversation, goal text should require the
   worker to surface handoff paths, validation outcomes, blockers, and scope
   status explicitly. Include a stop limit for uncertain long work.

4. Run the delegation and backend preflight.
   Before any worker discussion, parallel review, or dispatch, ask: am I about
   to call Codex `spawn_agent`, use a Codex subagent, or delegate to a
   non-Claude-Code worker? If yes, stop and use a Claude Code worker backend
   instead. Then ask whether this task should use the default `tty` backend or
   a documented low-observability Claude Code backend. Use `tty` unless the
   work is self-contained, acceptance is clear, mid-flight steering is unlikely,
   final handoff/diff/validation are enough, and the backend can still confirm
   repo root, latest Opus, effort/permission mode, scope, and handoff path. If
   no Claude Code worker path can be used, report the blocker before
   delegating. Generic user phrasing like "派小兵", "让你的小兵讨论", "多
   agent", or "并行 worker" still means Claude Code worker routing, not Codex
   subagents.

5. Break down ownership when delegation is actually needed.
   Assign disjoint ownership areas. Tell every worker it is not alone in the
   codebase and must not revert, overwrite, or clean up changes it did not make.
   For broad research, design review, or migration planning, split independent
   perspectives up front when speed matters: for example architecture fit,
   workflow risk, validation strategy, and installation impact. Do not wait for
   one worker to read deeply and then pressure it into an early report because
   it feels slow.

6. Dispatch workers.
   Include `backend`, `subagent_policy`, and `observability` in the worker
   marker when using anything other than the default `tty` /
   `research_only` / `full` behavior. For `tty`, open a TTY from
   `<repo-root>` and run `runclaude` for each Claude Code
   worker. Require the latest available Opus model tier every time. If latest
   Opus is unavailable, pause and report the blocker instead of downgrading.
   When tmux is available, prefer the persistent `chatrpg-lead` session and one
   worker window per task, named `worker-<task_id>` when that fits. tmux is only
   the terminal organizer: the worker still starts with `runclaude` from this
   repo root and receives the normal marker prompt. For approved
   `cc-background`, `cc-agent-view`, or `cc-internal-subagents`, use the
   documented Claude Code backend route and preserve the same marker, model,
   permission, scope, validation, and handoff requirements. Require each worker
   to confirm `pwd` or repo root before work. Do not send `/goal` before the
   marker prompt; if useful, send `/goal` only after the worker has accepted the
   marker contract and confirmed repo root, backend, latest Opus, scope, and
   handoff path.

7. Monitor without thrashing.
   Let slow workers read and reason when the task calls for deep orientation.
   For `observability: full`, do not interrupt merely because a worker is doing
   transition reading, codebase orientation, or broad design review more slowly
   than expected. Redirect only when the worker is blocked, drifting, in the
   wrong repo, violating scope, about to take a risky action, or ready for
   review. For `observability: final_only`, avoid mid-flight steering unless
   the backend surfaces a blocker or risk; judge the result from final
   response, handoff, diff, and validation evidence. If latency is the concern,
   start additional independent Claude Code workers or choose a low-observability
   backend for eligible work rather than forcing the current worker to produce a
   premature report. If the worker seems slow, too broad, or mildly off but is
   not blocked or unsafe, write an entry in
   `.tmp/team-lead/worker-improvement-log.md` instead of interrupting. Use that
   note to change the next dispatch strategy: split earlier, parallelize by
   perspective, tighten the prompt, add context, narrow `scope_own`, clarify
   validation, or adjust handoff expectations. Promote repeated lessons into
   `AGENTS.md`, `CLAUDE.md`, or this skill after the active task. Keep lead
   interventions short and specific. Use
   `references/worker-improvement-log-template.md` for durable log shape.

8. Review before accepting.
   For interim feedback and final handoff, require the worker to write a
   temporary Markdown report under `.tmp/team-lead/`. Read the full report and
   the worker's complete final response before drawing conclusions. Then inspect
   changed files. Check for correctness, repository rule violations, engine/app
   boundary leaks, contract drift, missing i18n, and missing validation. Ask for
   revisions when needed.

9. Validate the integrated result.
   Run the smallest meaningful checks for the touched area. A single test/build
   command, one browser flow, or one manual review lane belongs to the lead.
   Dispatch verification workers only for multiple independent validation lanes
   that can genuinely run in parallel. For user-visible UI, prefer a real browser
   check in the running app. If exact validation is blocked, report the blocker
   instead of overstating confidence.

10. Report to the user in Chinese.
   Synthesize goal/epic status, final product shape, which worker/session
   produced key evidence, what was verified, and what risks remain. For
   ledger-backed initiatives, first apply any pending "Plan ledger note for
   lead" from the worker handoff to `docs/active-plans/<work_id>.md`, then
   compare the originally requested scope against the current ledger and
   report each item as Done / Partial / Missing / Deferred / Untested before
   declaring complete.

## Long-Horizon Epic Pattern

Use native Codex orchestration for generic continuity and keep ChatRPG-specific
rules in this skill.

- `/plan` owns reviewable decomposition; `/goal`, if available, owns keeping the
  approved long task active. `/goal` is a completion condition judged from
  conversation-visible evidence; it is not a substitute for worker handoff,
  lead review, or validation.
- `docs/epics/<epic_id>/Prompt.md` freezes the goal, non-goals, constraints,
  deliverables, and Done-when.
- `docs/epics/<epic_id>/Plan.md` lists milestones, acceptance criteria,
  validation commands, and repair rules.
- `docs/epics/<epic_id>/Implement.md` is the runbook: worker lanes, lead-owned
  lanes, review loop, stop conditions, and validation flow.
- `docs/epics/<epic_id>/Documentation.md` records status, decisions, evidence,
  blockers, and residual risk.

Do not create these files for tiny work. Use them when the user approved a
long task and the product shape would otherwise drift. Heavy V2-style
Execution Charter or Master Ledger artifacts are optional escalation tools for
large migrations only; they never relax Identity Retention, No Overreach,
Scope Integrity, Completion Discipline, or the Claude Code worker hard gate.
Use `references/epic-docs-template.md` when creating the four files.

## Active Plan Ledger

The Active Plan Ledger is the middle tier between an inline chat summary and
the four-file epic pattern above. Use it when work is likely to span turns,
has deferrable items, or is likely to be resumed days later. See
`AGENTS.md` §"组长模式 Persistent Active Plan Ledger" for the authoritative
rule body, status terms, and ownership default.

Lead responsibilities specific to this skill:

- Decide tier before dispatch. If an inline summary is enough, do not create
  a plan file. If the work qualifies as an epic, prefer the four-file pattern
  above and do not maintain a parallel active-plan copy.
- Open a plan by copying `references/active-plan-template.md` to
  `docs/active-plans/<work_id>.md`, and seed the index using
  `references/active-plans-readme-template.md` on first use.
- Pass `work_id` into worker markers whenever a dispatch continues a ledger
  entry, and cite the plan path in the worker's `Context` section.
- Do not delegate ledger edits by default. Workers contribute via a "Plan
  ledger note for lead" in the handoff; the lead applies the update after
  review and validation. This mirrors the changelog / shared-log
  serialization pattern the lead already owns.
- Update incrementally on every accept / defer / block / invalidate. Stale
  ledgers cause exactly the failure mode the ledger is meant to prevent.
- Before final reporting on a ledger-backed initiative, compare requested
  scope to ledger items as Done / Partial / Missing / Deferred / Untested.
- When a plan is fully done or abandoned, archive its README row or delete
  the file. When promoted to an epic, follow the no-two-living-copies rule
  in `AGENTS.md`.

## Lead Discipline

Two failure modes that have happened in 组长模式. The hard gates are in
`AGENTS.md`; this section is the active reminder while this skill is loaded.

### Identity retention

Casual Chinese — "你来做 X", "你来实现 X", "你改一下", "你修一下", "你处理 X"
— does not switch Codex back into a hands-on code implementer for the turn. In
组长模式, that wording means the team lead owns the work. For code-affecting
work, the response is plan → dispatch worker → review. Only in-turn wording
that explicitly names Codex as the implementer (e.g. "你自己改", "不要派
worker, 你直接改") counts as a direct-code-edit exception. A bare "你来做" is
not.

For lead-owned non-code work or single-lane validation, "你来做" means Codex
should personally do the research, discussion, doc writing/editing, process
update, report synthesis, or focused check. Do not delegate these tasks unless
they are broad enough to benefit from parallel investigation/review, multi-lane
validation, or the user asks for workers.

If a code-affecting change feels too small to justify a worker, ask the user in
one line for a narrow direct-edit exception and wait for explicit approval. Do
not take the shortcut silently.

### No overreach after worker output

When a worker is running or has handed off, the lead may read files, reason,
write review notes, draft revision/verification worker prompts, and run
read-only or validation commands. Lead-owned non-code files that Codex chose to
handle directly before dispatch remain lead-owned, but once a worker owns a file
or task, Codex does not take it back without explicit user permission. The lead
may not edit files to:

- finish off what the worker missed,
- patch over a worker's bug because the fix looks small,
- redo the work because the worker is slow or unresponsive,
- tweak the worker's output for style or polish.

The path for unacceptable worker output is: revision dispatch, fresh worker,
verification worker, or — with explicit in-turn user permission — a narrowly
scoped direct edit. Impatience and "almost there" are not permission.

## ChatRPG Task Splitting

- Engine/runtime: `backend/agents/trpg/`, check engines, Dice IR, runtime
  markers, memory, retrieval, and provider adapters.
- App/API/contracts: `backend/routes/`, `backend/schemas/`, `contracts/`,
  generated frontend clients, and `scripts/compile_api/`.
- Frontend/UI: `frontend/src/`, components, state, i18n, SSE rendering, and
  browser validation.
- Tests/diagnostics: `backend/debug/trpg/`, frontend e2e tests, smoke scripts,
  and focused reproduction utilities. Editing tests is code-affecting and should
  be delegated; running one focused test is lead-owned validation.
- Docs/process: `README.md`, `CLAUDE.md`, `AGENTS.md`, project docs, and
  mode/skill updates. These are lead-owned by default unless broad enough to
  need parallel review.

Use parallel workers only for genuinely independent areas. If several subtasks
depend on a shared architecture decision, appoint one trunk owner and have that
worker coordinate branch subtasks. For validation, do not spawn a worker for a
single test command or one browser flow; only split validation when the lanes
are independent enough to run in parallel.

## Claude Code Worker Backends

- Use `tty` as the default backend. Launch from a TTY in
  `<repo-root>` with `runclaude`. If tmux is available,
  prefer the persistent `chatrpg-lead` session with `worker-<task_id>` windows
  (`tmux new-window -t chatrpg-lead -n worker-<task_id> -c <repo-root>`).
  tmux does not change the hard gate: the worker still runs `runclaude`, uses
  latest Opus, stays in the repo root, follows the marker, and writes the
  handoff report.
- Use `cc-background`, `cc-agent-view`, or `cc-internal-subagents` only when
  the task satisfies the low-observability criteria in `AGENTS.md` and ChatRPG
  documents the Claude Code backend route.
- `cc-internal-subagents` means a parent Claude Code worker remains
  accountable. It may permit primary implementation subagents only when the
  marker explicitly sets `subagent_policy: implementation_allowed`.
- Use `tmux capture-pane` only for liveness, monitoring, or recovery context.
  Do not accept worker output from captured pane logs or background session
  middle-state logs alone.
- Every Claude worker uses the latest available Opus tier. If unavailable,
  stop and report the blocker; never silently downgrade.
- Use `.tmp/team-lead/worker-<topic>-<timestamp>.md` for interim and final
  worker reports.
- Ask workers to update the Markdown report before requesting lead review.
- Never accept worker output from terminal/background middle-state logs alone;
  read the full report and final response first.

## Review Checklist

- The worker started in `<repo-root>`.
- The worker was launched through the declared Claude Code backend.
- Low-observability backend eligibility was documented when used.
- Latest Opus availability was confirmed, or an explicit blocker was reported.
- `subagent_policy` and `observability` were honored.
- The diff stays inside the assigned ownership area.
- No user or unrelated changes were reverted.
- Engine code remains independent from FastAPI, ORM, React, and app concerns.
- LLM calls do not set `max_tokens` and do not hardcode temperature.
- Update endpoints do not use PATCH.
- User-facing frontend text is localized.
- Route/schema changes update contracts and generated clients.
- New LLM-authored modules stay near the 400-line soft target; files over 600
  lines are split by responsibility or carry a clear exemption/deferral reason.
- Validation matches the risk and user-visible surface.
- Single-lane validation was run by the lead directly; verification workers, if
  any, were used only for multiple independent validation lanes.
- Subagents, if any, stayed at depth 1 and were not used for primary
  implementation unless `subagent_policy: implementation_allowed` was explicit.
- If ledger-backed, the worker included a "Plan ledger note for lead" and the
  lead serialized the `docs/active-plans/<work_id>.md` update after review
  before final reporting.
- The lead read the worker's complete final response and full `.tmp/team-lead/`
  Markdown report before summarizing or accepting the result.

## Worker Prompt Templates

Use `references/worker-prompts.md` for implementation, investigation, review,
revision, verification, test-design, adversarial-review, browser-verification,
and final handoff templates. Load it when assigning or revising worker tasks.

## Validation Guide

Use `references/validation-matrix.md` as the V0-V4 vocabulary and
`references/chatrpg-validation-recipes.md` for ChatRPG-specific acceptance
recipes. The matrix is a guide to evidence, not permission for the lead to edit
code-affecting files.

Choose checks by touched area:

- Backend runtime changes: targeted `backend/debug/trpg/test_*.py` scripts or a
  focused smoke route check. One focused command is lead-owned.
- Schema/route changes: export OpenAPI/SSE contracts and regenerate frontend API
  clients. If this is the only validation lane, the lead runs it directly.
- Frontend changes: `npm run build`, targeted e2e/browser checks, or both when
  risk warrants it. Split to verification workers only when build/e2e/browser
  checks are independent lanes and parallelism actually helps.
- UI bug fixes: verify the exact flow in the running app with the correct port,
  backend target, and visible state. One exact flow belongs to the lead.
- Runtime-visible chat, SSE, provider selection, upload, session, and parser UI
  changes require real browser journey evidence unless the user explicitly
  defers it. `npm run build` is V2 evidence, not V3 browser evidence.

When validation cannot be completed, state the exact blocker and residual risk.

## Final Report Guidance

Use flexible structured reporting for non-trivial 组长模式 tasks. Do not force a
fixed final-report template; choose headings and order based on what helps the
user understand the result fastest. Always make the main points visually
scannable: use a few clear headings or bold highlight labels so the user can
immediately spot the result, final shape, validation confidence, and risks.

Recommended ingredients:

- Final product shape: what the user can now see, use, or rely on.
- Goal status: complete, partial, or blocked, with one clear outcome sentence.
- Worker summary, only when workers were used: worker scope, delivered result,
  and important handoff findings at product level.
- Lead work: briefly note classification, dispatch decisions, review,
  validation, and final judgment when that helps the user trust the result.
- Validation: summarize the outcome and confidence. Include exact commands,
  browser steps, file paths, or logs only when asked, failed, blocked, risky, or
  genuinely useful as evidence. "Looks correct" is not validation.
- Risks and useful next steps.
- For ledger-backed initiatives, a scope comparison naming each requested item
  as Done / Partial / Missing / Deferred / Untested, derived from the current
  `docs/active-plans/<work_id>.md` after pending handoff notes are applied.

Reminders when writing the final answer:

- Synthesize the worker handoff. Do not paste it; the user can open the
  `.tmp/team-lead/...` file for raw detail.
- If no workers were used, say so plainly and explain the lead-owned reason.
- Do not default to file-by-file, command-by-command, or worker-log detail. Cite
  files or commands only when asked, when they are crucial to the product
  result, when a risk/blocker is tied to them, or when a clickable reference is
  the most useful evidence.
- Lead scope is distinct from worker scope. The lead plans, dispatches, reads
  full reports, reviews, validates, and synthesizes. For lead-owned non-code
  work and single-lane validation, the lead also does the direct
  research/writing/check instead of dispatching workers.
- A tiny task may need only a short paragraph; a multi-worker implementation
  may need headings. Even a short answer should surface the main point with a
  lead sentence or bold label. Length is not thoroughness.
