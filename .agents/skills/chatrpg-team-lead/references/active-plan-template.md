# Active Plan Template

Use this template when opening a new entry under
`docs/active-plans/<work_id>.md`. Keep it short; the plan is a memory aid,
not a report. See `AGENTS.md` §"组长模式 Persistent Active Plan Ledger"
for the authoritative rule body and ownership default.

Copy the structure below, replace placeholders, and update incrementally as
work lands. Do not paste secrets, credentials, tokens, or raw worker logs.
Reference handoff paths under `.tmp/team-lead/` for evidence instead.

---

```markdown
# <Human-readable plan title>

Work ID: `<work_id>`
Status: `Done | In Progress | Not Done | Partial | Blocked | Deferred`
Last updated: `YYYY-MM-DD`

## Goal

<One short paragraph describing the current user-facing goal. If the goal
evolves, edit this section in place; do not append a new goal.>

## Decisions

- <Product, architecture, or process decision already made and not up for
  re-litigation.>
- <Decision 2.>

## Items

| Item | Status | Note |
|---|---|---|
| <agreed deliverable 1> | Not Done | <one-line context> |
| <agreed deliverable 2> | In Progress | <owner / dispatch / handoff path> |
| <agreed deliverable 3> | Done | <evidence path> |
| <agreed deliverable 4> | Deferred | <reason> |

Use the six status terms: `Done`, `In Progress`, `Not Done`, `Partial`,
`Blocked`, `Deferred`.

## Validation evidence

- <Command, browser flow, file path, or handoff report under
  `.tmp/team-lead/` that backs a `Done` or `Partial` item.>
- <Another piece of evidence, or "none yet".>

"Looks correct" is not validation. For UI / chat / SSE / upload / provider
/ runtime-visible behavior, V3 browser evidence is required unless the user
explicitly defers it.

## Blockers

- <Current blocker with one-line reason, or `none`.>

## Next action

<The single most important next step, concrete enough that a fresh AiChatTrpg
worker prompt (`[CHATRPG_TEAM_LEAD_WORKER_V1]`) can be drafted from it.>
```

---

## Optional sections

Add only when they pay for themselves. Do not bloat the plan.

- **Acceptance criteria** — observable conditions for declaring the
  initiative `Done`, ideally mapped to the V0–V4 vocabulary in
  `validation-matrix.md`.
- **Execution lanes** — used when multiple workers are coordinated; one row
  per lane with owner and current status.
- **Worker handoff index** — table of handoff paths under
  `.tmp/team-lead/` keyed by `task_id`.
- **Notes / risks** — open risks and trade-offs that do not fit the
  Decisions list.

## Hard prohibitions

- No secrets, credentials, tokens, or environment values.
- No raw worker logs or long terminal output.
- No second living copy when the initiative has been promoted to an epic
  under `docs/epics/<epic_id>/`.
- No worker edits to this file unless the dispatch marker explicitly places
  this path in `scope_own`.

## How workers interact with this file

By default, workers read this file as context and do not edit it. They
contribute a concise "Plan ledger note for lead" in their handoff that
names the `work_id` and any items whose status should change. The Codex
lead serializes the update after review and validation, mirroring the
changelog / shared-log serialization pattern.

If a dispatch is specifically scoped to revise an active plan, the marker
must include this path in `scope_own` and the worker must keep the change
within the items the lead approved.
