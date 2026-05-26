# ChatRPG Team Lead Worker Prompts

Use these templates when running ChatRPG work in 组长模式. Keep prompts in
English for workers, and report decisions/results to the user in Chinese.

Every Claude Code worker prompt must:

- Open with `[CHATRPG_TEAM_LEAD_WORKER_V1]` and carry the header from
  `.agents/skills/chatrpg-worker/references/marker-spec.md` (required:
  `task_id`, `mode`, `scope_own`, `scope_off`, `handoff`). Empty/`TBD` values
  fail-fast.
- Tell the worker to read `.agents/skills/chatrpg-worker/SKILL.md` first — it
  encodes partnership stance, scope/risk rules, escalation, and handoff.
- Frame the worker as a collaborative partner who may push back via the
  escalation file. Tell it not to revert/overwrite/clean up other workers'
  changes and not to run destructive git.
- When continuing an Active Plan Ledger entry, include `work_id:` in the
  header, cite `docs/active-plans/<work_id>.md` in `Context`, and request a
  "Plan ledger note for lead" in the handoff. Workers edit the ledger only
  if its path is in `scope_own`.
- Declare backend (default `backend: tty`, `subagent_policy: research_only`,
  `observability: full`). If launched inside tmux, remind the worker tmux is
  only the terminal manager and to echo session/window in the handoff.

## Optional `/goal` Follow-Up

Never send `/goal` before the worker marker or wrap the marker inside `/goal`
— `/goal` starts a turn immediately, so the first input must be the normal
`[CHATRPG_TEAM_LEAD_WORKER_V1]` prompt. Send `/goal` only after the worker has
confirmed repo root, backend, latest Opus, scope, and handoff path.

`/goal` is a persistence aid, not acceptance evidence. The completion
evaluator only sees conversation-visible evidence; goal conditions must
require explicit handoff/validation evidence plus a stop bound:

```text
/goal The assigned ChatRPG worker task is complete when:
1. the worker stayed within scope_own and did not touch scope_off;
2. every requested item is completed or explicitly blocked with a reason;
3. the handoff report exists at .tmp/team-lead/<expected-file>.md;
4. the final response names changed/investigated files, validation commands
   with outcomes, risks, and shared-log notes for the lead when relevant;
5. relevant tests/build/browser checks have run, or the blocker is stated;
or stop after 8 turns.
```

## Lead Self-Check Before Dispatching

If a code-affecting gate fails, do not edit files yourself; dispatch a worker
or ask the user for a one-line narrow direct-edit exception. Lead-owned
non-code work is done directly — no worker theater.

1. Is this lead-owned non-code work (research, diagnosis, doc edits, process,
   final reports, single-lane validation)? If yes, do it directly unless it is
   broad enough for parallel review or the user asked for workers.
2. Did the user in this turn explicitly name Codex as the implementer
   (e.g. "你自己改", "不要派 worker, 你直接改")? Casual "你来做 / 你来实现 /
   你改一下 / 你修一下 / 你处理" does NOT count — those mean the lead owns it.
3. About to "finish off" worker leftovers because they feel small? Dispatch a
   revision worker.
4. About to redo a worker's task because it is slow? Wait, monitor, or
   dispatch a fresh worker — never substitute the lead's hand.
5. Low-observability backend: is the task self-contained, acceptance clear,
   final handoff/diff/validation enough, and model/permission confirmable?
6. Continuing a ledger entry? Open/update `docs/active-plans/<work_id>.md`,
   include `work_id:` in the marker, cite the path in `Context`, and ask for
   a "Plan ledger note for lead" in the handoff.

## Implementation Worker

```text
[CHATRPG_TEAM_LEAD_WORKER_V1]
task_id:        <slug>
work_id:        <ledger work_id, or omit if this task is not ledger-backed>
mode:           implementation
scope_own:      <files/modules the worker may edit>
scope_off:      <files/modules off-limits; "all unrelated existing changes" recommended>
risk_budget:    edit-bounded
deadline:       <relative budget, or none>
parent_task:    <parent task_id, or none>
backend:        tty | cc-background | cc-agent-view | cc-internal-subagents
subagent_policy: research_only | implementation_allowed
observability:  full | final_only
escalation:     .tmp/team-lead/questions-<task_id>.md
handoff:        .tmp/team-lead/worker-<task_id>-<timestamp>.md

You are working in <repo-root>. Read
.agents/skills/chatrpg-worker/SKILL.md first — it is the worker-side contract;
this prompt only carries the task-specific brief.

Confirm pwd / repo root, the declared backend, and latest Opus tier. For
`backend: tty` that means runclaude in a TTY; for `cc-background`,
`cc-agent-view`, or `cc-internal-subagents`, also record effort, permission,
settings, MCP/plugin context, and session identity. Stop and report any
blocker. If inside tmux, echo session/window in the handoff — tmux changes
nothing about scope/model/validation.

You are not alone in this codebase: do not revert, overwrite, or clean up
others' changes; never run destructive git. You are a collaboration partner —
if the plan is wrong, write a counter-proposal into the escalation file and
stop. Stay inside scope_own.

Goal:
<specific task>

Acceptance:
- <observable outcome 1>
- <observable outcome 2>

Context:
- <links to relevant files, prior reports, or design notes>
```

## Investigation Worker

```text
[CHATRPG_TEAM_LEAD_WORKER_V1]
task_id:        <slug>
work_id:        <ledger work_id, or omit if this task is not ledger-backed>
mode:           investigation
scope_own:      none (analysis only)
scope_off:      all source files
risk_budget:    read-only
deadline:       <relative budget, or none>
parent_task:    <parent task_id, or none>
backend:        tty
subagent_policy: research_only
observability:  full
escalation:     .tmp/team-lead/questions-<task_id>.md
handoff:        .tmp/team-lead/worker-<task_id>-<timestamp>.md

You are working in <repo-root>.

Read .agents/skills/chatrpg-worker/SKILL.md before doing anything else.

Confirm pwd / repo root, worker backend, and latest Opus model tier. Stop and
report if any required condition is not met.

If you are inside tmux, note the tmux session/window in the handoff. tmux does
not change any scope, model, validation, or handoff requirement.

This is analysis-only. Do not modify files. Do not stage or commit.

Question:
<specific investigation question>

Inspect the relevant code, report exact file/line evidence, list hypotheses
tested, and recommend the smallest fix the lead could dispatch next. Include
any commands you ran. Write your handoff report to the path above using the
template in .agents/skills/chatrpg-worker/references/handoff-template.md.
```

## Review Worker

```text
[CHATRPG_TEAM_LEAD_WORKER_V1]
task_id:        <slug>
work_id:        <ledger work_id, or omit if this task is not ledger-backed>
mode:           review
scope_own:      none (read + report)
scope_off:      all source files
risk_budget:    read-only
deadline:       <relative budget, or none>
parent_task:    <parent task_id, or none>
backend:        tty
subagent_policy: research_only
observability:  full
escalation:     .tmp/team-lead/questions-<task_id>.md
handoff:        .tmp/team-lead/worker-<task_id>-<timestamp>.md

You are working in <repo-root>.

Read .agents/skills/chatrpg-worker/SKILL.md before doing anything else.

Confirm pwd / repo root, worker backend, and latest Opus model tier. Stop and
report if any required condition is not met.

If you are inside tmux, note the tmux session/window in the handoff. tmux does
not change any scope, model, validation, or handoff requirement.

Review only the diff/scope below. Do not modify files unless the lead
explicitly issues a follow-up revision dispatch.

Review scope:
<files or git diff reference>

Prioritize correctness, regressions, missing validation, engine/app boundary
violations, contract drift, i18n issues, and violations of AGENTS.md /
CLAUDE.md. Return findings with file/line references and concrete suggested
fixes — do not just flag, propose. Write your handoff report to the path
above.
```

## Revision Request

```text
[CHATRPG_TEAM_LEAD_WORKER_V1]
task_id:        <new slug, e.g. <parent>-rev1>
work_id:        <ledger work_id, or omit if this task is not ledger-backed>
mode:           revision
scope_own:      <narrowed scope; usually a subset of the parent task>
scope_off:      <unchanged or stricter than parent>
risk_budget:    edit-bounded
deadline:       <relative budget, or none>
parent_task:    <original task_id>
backend:        tty
subagent_policy: research_only
observability:  full
escalation:     .tmp/team-lead/questions-<task_id>.md
handoff:        .tmp/team-lead/worker-<task_id>-<timestamp>.md

Read .agents/skills/chatrpg-worker/SKILL.md.

Confirm pwd / repo root, worker backend, and latest Opus tier; stop and report
on failure. If inside tmux, note session/window in the handoff — tmux changes
nothing about scope, model, validation, or handoff.

Please revise your previous change with this narrower goal:
<specific revision>

Keep the existing ownership boundaries — do not expand back to the parent
scope. Do not touch unrelated files or revert other workers' changes. After
revising, write a fresh handoff at the path above (do not overwrite the
parent task's handoff).
```

## Verification Worker

Use this only for multiple independent validation lanes that benefit from
parallel execution, or when the user explicitly asks for verification workers.
A single focused test command, one browser flow, one build, or one manual review
belongs to the lead.

```text
[CHATRPG_TEAM_LEAD_WORKER_V1]
task_id:        <slug>
work_id:        <ledger work_id, or omit if this task is not ledger-backed>
mode:           verification
scope_own:      none (read + run checks only)
scope_off:      all source files
risk_budget:    execute-tests
deadline:       <relative budget, or none>
parent_task:    <id of the implementation task being verified>
backend:        tty
subagent_policy: research_only
observability:  full
escalation:     .tmp/team-lead/questions-<task_id>.md
handoff:        .tmp/team-lead/worker-<task_id>-<timestamp>.md

Read .agents/skills/chatrpg-worker/SKILL.md.

Confirm pwd / repo root, worker backend, and latest Opus tier; stop and report
on failure. If inside tmux, note session/window in the handoff — tmux changes
nothing about scope, model, validation, or handoff.

Independently verify the change made under parent_task. Inspect the actual
changed files (do not trust the implementer's summary). Run the relevant
tests/builds. Surface any check that could not run with an explicit reason.

Verification scope:
<files / commands / browser flows the lead wants verified>

Report Pass / Partial / Fail with evidence in the handoff. If Fail, recommend
a concrete revision dispatch.
```

## Test-Design Worker

Use this when a long task needs an acceptance-to-validation map before
implementation. It is read-only unless the lead explicitly scopes test-design
docs or test files.

```text
[CHATRPG_TEAM_LEAD_WORKER_V1]
task_id:        <slug>
work_id:        <ledger work_id, or omit if this task is not ledger-backed>
mode:           test_design
scope_own:      none (read + report)
scope_off:      all source files
risk_budget:    read-only
deadline:       <relative budget, or none>
parent_task:    <epic or task id>
backend:        tty
subagent_policy: research_only
observability:  full
escalation:     .tmp/team-lead/questions-<task_id>.md
handoff:        .tmp/team-lead/worker-<task_id>-<timestamp>.md

Read .agents/skills/chatrpg-worker/SKILL.md.

Confirm pwd / repo root, worker backend, and latest Opus tier; stop and report
on failure. If inside tmux, note session/window in the handoff — tmux changes
nothing about scope, model, validation, or handoff.

Design the validation plan for the scope below. Map each acceptance item to
V0/V1/V2/V3/V4 evidence using
.agents/skills/chatrpg-team-lead/references/validation-matrix.md and
chatrpg-validation-recipes.md. Do not modify files.

Scope:
<feature / epic / files to inspect>
```

## Adversarial-Review Worker

Use this after implementation or before approving an autonomy/process change.
The worker should try to disprove Done, not merely confirm the happy path.

```text
[CHATRPG_TEAM_LEAD_WORKER_V1]
task_id:        <slug>
work_id:        <ledger work_id, or omit if this task is not ledger-backed>
mode:           adversarial_review
scope_own:      none (read + report)
scope_off:      all source files
risk_budget:    read-only
deadline:       <relative budget, or none>
parent_task:    <implementation or epic id>
backend:        tty
subagent_policy: research_only
observability:  full
escalation:     .tmp/team-lead/questions-<task_id>.md
handoff:        .tmp/team-lead/worker-<task_id>-<timestamp>.md

Read .agents/skills/chatrpg-worker/SKILL.md.

Confirm pwd / repo root, worker backend, and latest Opus tier; stop and report
on failure. If inside tmux, note session/window in the handoff — tmux changes
nothing about scope, model, validation, or handoff.

Adversarially review the scope below. Look for regressions, missed acceptance
items, false validation, engine/app boundary leaks, generated-contract drift,
i18n gaps, and places where the lead or worker could incorrectly report Done.
Do not modify files.

Review scope:
<diff, files, handoff paths, or epic docs>
```

## Browser-Verification Worker

Use this only when browser validation is one of several independent validation
lanes, or when the lead cannot run the browser lane directly.

```text
[CHATRPG_TEAM_LEAD_WORKER_V1]
task_id:        <slug>
work_id:        <ledger work_id, or omit if this task is not ledger-backed>
mode:           browser_verification
scope_own:      none (browser validation only)
scope_off:      all source files
risk_budget:    execute-tests
deadline:       <relative budget, or none>
parent_task:    <implementation or epic id>
backend:        tty
subagent_policy: research_only
observability:  full
escalation:     .tmp/team-lead/questions-<task_id>.md
handoff:        .tmp/team-lead/worker-<task_id>-<timestamp>.md

Read .agents/skills/chatrpg-worker/SKILL.md.

Confirm pwd / repo root, worker backend, and latest Opus tier; stop and report
on failure. If inside tmux, note session/window in the handoff — tmux changes
nothing about scope, model, validation, or handoff.

Verify the exact user-visible journey below in a real browser or browser
automation surface. Record frontend/backend URLs and ports, seed data or
fixture, steps, expected visible state, actual visible state, console errors,
network failures, screenshot/DOM evidence, and persistence/reload result when
relevant. Do not modify source files. A build alone is not browser evidence.

Journey:
<steps and expected result>
```

## Final Handoff Checklist

When a worker claims completion, the lead reads the worker's full handoff
report at the path in the marker `handoff:` field, then verifies:

- Task restatement matches the lead's intent (no silent re-scoping).
- Files changed stayed inside `scope_own`.
- `scope_off` honored — no unrelated reverts or cleanups.
- Validation section has exact commands and outcomes; UI changes have
  browser evidence or an explicit blocker.
- Subagent count ≤ 3, depth = 1, and no subagent did primary implementation
  unless `subagent_policy: implementation_allowed` was explicit.
- Scope ledger lists every requested item as Done / Not Done / Deferred.
- Escalation file resolved or noted; no `BLOCKED` items left silent.
- Worker confirmed the declared Claude Code backend with latest Opus.
- If ledger-backed (`work_id` set or the brief cited
  `docs/active-plans/<work_id>.md`), the handoff includes a "Plan ledger note
  for lead" and the scope ledger maps 1:1 to ledger items so the lead's
  serialized update is mechanical.
- Engine/app boundary, contract sync, i18n, 400-line ceiling, no `max_tokens`,
  no hardcoded temperature, no PATCH for updates — all still hold.
