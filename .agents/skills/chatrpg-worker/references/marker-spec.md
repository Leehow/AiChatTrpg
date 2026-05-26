# Marker header specification

The activation marker for the AiChatTrpg worker skill is a fenced header block at
the top of the worker prompt. The marker has two parts: a single-token
activation tag, and a structured key-value header.

## Activation tag

```
[CHATRPG_TEAM_LEAD_WORKER_V1]
```

This token must be present on its own line at the top of the worker prompt. If
it is missing, this skill does not apply — fall back to default Claude Code
behavior.

The `_V1` suffix exists so future contract changes can bump to `_V2` without
ambiguity. Workers should accept only the version they were trained on; Codex
should not silently mix versions in the same dispatch.

## Structured header

Immediately after the activation tag, the prompt carries a key-value block in
this shape (one key per line, `key: value`):

```text
[CHATRPG_TEAM_LEAD_WORKER_V1]
task_id:        <slug, e.g. trpg-runtime-marker-fix>
work_id:        <ledger work_id, optional; omit if not ledger-backed>
mode:           implementation | investigation | review | revision | verification | test_design | adversarial_review | browser_verification
scope_own:      <paths or modules the worker may edit>
scope_off:      <paths the worker must not touch; "none" allowed but required>
risk_budget:    read-only | edit-bounded | execute-tests | execute-anything
deadline:       <relative time budget, or "none">
parent_task:    <parent task_id, or "none">
backend:        tty | cc-background | cc-agent-view | cc-internal-subagents
subagent_policy: research_only | implementation_allowed
observability:  full | final_only
escalation:     .tmp/team-lead/questions-<task_id>.md
handoff:        .tmp/team-lead/worker-<task_id>-<timestamp>.md
```

After the header, free-form `Goal:`, `Acceptance:`, and `Context:` sections
follow. Those are prose; the worker reads them but does not parse them.

## Required fields

A worker must fail-fast if any of these are missing or empty:

- `task_id`
- `mode`
- `scope_own`
- `scope_off`
- `handoff`

"Empty" includes `<TBD>`, `none` (for `scope_own`/`scope_off` use literal
"none" only when truly nothing is in/out of scope, never as a placeholder),
or any value that looks like an unfilled template.

When a required field is missing:

1. Do not proceed.
2. Write a single-block escalation to
   `.tmp/team-lead/questions-<task_id-or-unknown>.md` describing which field
   is missing.
3. Tell Codex in the final terminal response that you stopped at activation.

Do not infer defaults for required fields. The trip-wire exists so a
half-formed prompt cannot cause silent damage.

## Recommended-but-optional fields

These have skill-defined defaults if absent. The worker should still echo the
chosen default in the handoff:

| Field | Default if absent |
|---|---|
| `work_id` | `none` (task is not ledger-backed) |
| `risk_budget` | `edit-bounded` |
| `deadline` | `none` |
| `parent_task` | `none` |
| `backend` | `tty` |
| `subagent_policy` | `research_only` |
| `observability` | `full` |
| `escalation` | `.tmp/team-lead/questions-<task_id>.md` |

## Field semantics

### `work_id`

Recommended-but-optional. Identifies the Active Plan Ledger entry this
dispatch continues, when one exists.

- Kebab-case slug, e.g. `auth-middleware-rewrite`.
- Matches the filename `docs/active-plans/<work_id>.md`.
- Typically reused as a prefix in `task_id`, handoff filenames, and
  validation notes for the same initiative.
- Omit `work_id` when the task is not ledger-backed; do not invent a value.
- When present, the worker reads `docs/active-plans/<work_id>.md` as
  context, but only edits it if the dispatch explicitly places that path in
  `scope_own`. The Codex lead serializes ledger updates after handoff
  review.

See `AGENTS.md` §"组长模式 Persistent Active Plan Ledger" for the full rule
body, status terms, and ownership default.

### `mode`

| Mode | Worker may edit code? | Typical scope |
|---|---|---|
| `implementation` | Yes, within `scope_own` | Bounded patch |
| `investigation` | No (analysis only) | Read-only diagnosis |
| `review` | No (read + report) | Diff review or design review |
| `revision` | Yes, within `scope_own` | Narrowed re-do of a previous worker change |
| `verification` | No, validation only | Independent re-check of another worker's change |
| `test_design` | No, unless explicitly scoped to test files | Validation plan, fixture map, acceptance-to-validation matrix |
| `adversarial_review` | No (read + report) | Find failure modes, regressions, scope gaps, shallow validation |
| `browser_verification` | No source edits; may use browser/test tooling | Real UI journey evidence for user-visible behavior |

`mode` controls whether the worker may edit tracked source files.
`investigation`, `review`, `verification`, `adversarial_review`, and
`browser_verification` are non-editing modes — the worker must not edit tracked
source files in those modes, regardless of what `risk_budget` says.
`test_design` is non-editing by default; it may edit test-design docs or test
files only when the lead explicitly puts those paths in `scope_own`.
`risk_budget` is orthogonal: it controls which commands and checks may run (see
below). A `verification` or `browser_verification` task may carry
`risk_budget: execute-tests` so the verifier can run tests/builds/browser
checks, but that does not grant any source-edit permission.

### `scope_own`

A list of paths or modules the worker may edit. Globs are allowed. Examples:

- `backend/agents/trpg/check_engines.py`
- `backend/agents/trpg/check_ir/**`
- `frontend/src/features/character/**; frontend/src/api/generated/**`
- `.agents/skills/chatrpg-worker/**`

If the worker discovers it needs to edit something not in `scope_own`,
escalate. Do not silently extend.

### `scope_off`

A list of paths or modules the worker must not touch. Special values:

- `none` — only valid if `scope_own` is exhaustive and nothing else is
  off-limits. Rare.
- `all generated files` — a common shorthand; worker treats `frontend/src/api/generated/**` and `contracts/**` as off-limits unless `scope_own` explicitly includes them.
- `unrelated existing changes` — the dirty working tree may already contain
  other workers' or the user's edits. Do not revert them.

`scope_off` is enforced in two places: the worker before each edit, and the
verification step in the handoff (scope ledger).

### `risk_budget`

| Value | What is allowed |
|---|---|
| `read-only` | No file mutation. May read, grep, search, run analysis tools. |
| `edit-bounded` | Source edits within `scope_own` (only when `mode` permits edits). Run tests/builds for the touched area. No deploys, no destructive git, no schema migrations. |
| `execute-tests` | Run broader test/build tasks across the repo. Normal transient test/build/cache artifacts are expected. Does not by itself grant source-edit permission — source edits still require an editing `mode` and a path inside `scope_own`. No deploys, no destructive git, no schema migrations. |
| `execute-anything` | Reserved. Requires an explicit per-task confirmation in the prompt. Worker should still escalate on irreversible actions. |

`mode` and `risk_budget` are orthogonal: `mode` answers "may I edit source?",
`risk_budget` answers "what may I run?". Edit permission is the intersection
of an editing `mode` and a path in `scope_own`; `risk_budget` never widens
it.

### `deadline`

A relative time budget. Workers do not enforce deadlines automatically — this
is informational so Codex can decide when to check in. Honest "no" beats fake
"yes" if a deadline can't be met; escalate rather than rush.

### `parent_task`

The `task_id` of the dispatch this task descends from. Lets Codex grep across
`.tmp/team-lead/` for the full lineage of a multi-worker job.

### `backend`

The Claude Code worker backend selected by the lead.

| Value | Meaning |
|---|---|
| `tty` | Default. The worker runs through `runclaude` in a TTY. |
| `cc-background` | A documented Claude Code background worker/session route. |
| `cc-agent-view` | A documented Claude Code Agent View worker/session route. |
| `cc-internal-subagents` | A parent Claude Code worker remains accountable and may use Claude Code subagents internally. |

All backends must still confirm repo root, backend, latest Opus, scope,
permission mode where visible, and handoff path. A non-`tty` backend does not
authorize Codex subagents or non-Claude workers.

### `subagent_policy`

Controls whether Claude Code subagents may participate in the assigned work.

| Value | Meaning |
|---|---|
| `research_only` | Default. Subagents may perform bounded read-only research, review, or verification, but not primary implementation. |
| `implementation_allowed` | The lead explicitly allows Claude Code subagents to perform bounded implementation subtasks inside `scope_own`, with depth 1 and parent-worker accountability. |

Even when implementation is allowed, subagents may not expand scope, edit shared
logs unless explicitly scoped, perform risky actions, or recurse.

### `observability`

Controls how much mid-flight monitoring the lead expects.

| Value | Meaning |
|---|---|
| `full` | Default. The lead may monitor and redirect during the worker session. |
| `final_only` | The worker should expect minimal mid-flight steering; acceptance depends on final response, handoff, diff, and validation evidence. |

### `escalation` and `handoff`

File paths (not directories). The worker writes to these — never reads them as
input. If the file already exists from a previous attempt, append; do not
truncate.

## Example: implementation dispatch

```text
[CHATRPG_TEAM_LEAD_WORKER_V1]
task_id:        trpg-pbta-engine-fix
mode:           implementation
scope_own:      backend/agents/trpg/check_engines.py; backend/debug/trpg/test_pbta_engine.py
scope_off:      backend/agents/trpg/check_ir/**; frontend/**; contracts/**; all unrelated existing changes
risk_budget:    edit-bounded
deadline:       none
parent_task:    none
backend:        tty
subagent_policy: research_only
observability:  full
escalation:     .tmp/team-lead/questions-trpg-pbta-engine-fix.md
handoff:        .tmp/team-lead/worker-trpg-pbta-engine-fix-20260505-160000.md

Goal: Fix the PBTA 2d6 engine so 10+ correctly maps to "strong hit".

Acceptance: …
Context: …
```

## Example: investigation dispatch

```text
[CHATRPG_TEAM_LEAD_WORKER_V1]
task_id:        trpg-memory-runtime-survey
mode:           investigation
scope_own:      none (analysis only)
scope_off:      all source files
risk_budget:    read-only
deadline:       none
parent_task:    none
backend:        tty
subagent_policy: research_only
observability:  full
escalation:     .tmp/team-lead/questions-trpg-memory-runtime-survey.md
handoff:        .tmp/team-lead/worker-trpg-memory-runtime-survey-20260505-160000.md

Question: Which memory runtime does the postprocess step actually call into …
```

## Example: revision dispatch

A `revision` task should set `parent_task` to the original task and narrow
`scope_own` to the smallest patch surface that addresses the lead's review.
The worker must not expand back to the original scope.

## Drift checks the worker should run on the marker

Before doing work, the worker checks:

- The activation tag matches the version this skill targets (`_V1`).
- All required fields are present and non-empty.
- `mode` is one of the valid values listed above.
- `backend`, `subagent_policy`, and `observability` are valid if present.
- `risk_budget` is consistent with `mode`:
  - `mode: investigation`, `mode: review`, `mode: test_design`, and
    `mode: adversarial_review` -> `risk_budget: read-only`.
  - `mode: verification` and `mode: browser_verification` ->
    `risk_budget: read-only` or `execute-tests`.
  - `mode: implementation` and `mode: revision` → `risk_budget: edit-bounded`
    (or `execute-anything` when explicitly authorized in the brief).
- `scope_own` and `scope_off` do not overlap.
- The `handoff` path is inside `.tmp/team-lead/` (never elsewhere).

If any check fails, escalate and stop.
