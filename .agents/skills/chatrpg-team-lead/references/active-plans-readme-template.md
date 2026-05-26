# Active Plans README Template

Use this template to seed `docs/active-plans/README.md` on first use. The
README is the index of active plan files in that directory. See `AGENTS.md`
§"组长模式 Persistent Active Plan Ledger" for the authoritative rule body
and when-to-use criteria.

Copy the structure below, replace placeholders, and let the Codex lead edit
the tables incrementally as plans open, change status, or archive.

---

```markdown
# Active Plans Ledger

This directory holds durable Markdown ledgers for multi-turn AiChatTrpg 组长模式
initiatives that need on-disk Done / Not Done memory. Each plan lives in
`docs/active-plans/<work_id>.md` and is created from
`.agents/skills/chatrpg-team-lead/references/active-plan-template.md`.

The ledger is memory and accountability only. It does not authorize Codex
to directly edit code-affecting files, does not replace
`.tmp/team-lead/` worker handoffs, does not replace `/plan` or `/goal`,
and does not weaken validation. The Codex lead owns updates by default.
See `AGENTS.md` for the full rule body.

## Work IDs

- Kebab-case, e.g. `auth-middleware-rewrite`.
- Match the plan filename: `docs/active-plans/<work_id>.md`.
- Reused as the slug or prefix for worker `task_id`, handoff filenames, and
  validation notes for the same initiative.
- Carried in the worker marker as the optional `work_id:` field whenever a
  dispatch (`[CHATRPG_TEAM_LEAD_WORKER_V1]`) continues a ledger entry.

## Status Terms

- `Done` — implemented or decided, backed by evidence.
- `In Progress` — currently owned by the lead or a named worker.
- `Not Done` — agreed work, not yet started.
- `Partial` — some evidence exists, intended behavior incomplete.
- `Blocked` — cannot proceed without a dependency or user decision.
- `Deferred` — intentionally postponed, with a stated reason.

## When To Open A Plan

Open a plan when at least one of the following is true:

- The work is likely to span multiple turns or worker dispatches.
- At least one deliverable is expected to be deferred, blocked, or staged.
- The user resumed an earlier thread or named a `work_id`.

Do not open a plan for one-turn fixes, single-file refactors with no
deferrable items, pure analysis-only requests, or routine work that fits in
an inline chat summary.

## Active Plans

| Work ID | Plan | Status | Last Updated | Next Action |
|---|---|---|---:|---|
| <work-id> | [<title>](<work-id>.md) | `In Progress` | `YYYY-MM-DD` | <one-line next action> |

## Archived

| Work ID | Plan | Closed | Outcome |
|---|---|---:|---|
| <work-id> | [<title>](<work-id>.md) | `YYYY-MM-DD` | `Done | Abandoned | Promoted to epic` |
```

---

## Maintenance notes

- Move a plan row from `## Active Plans` to `## Archived` when the
  initiative is fully `Done` or explicitly abandoned, or delete the file
  outright when no future reader will benefit from it.
- When an active plan is promoted to an epic under
  `docs/epics/<epic_id>/`, either delete the plan file and let the README
  row point at the epic, or shrink the plan to a one-paragraph pointer to
  `docs/epics/<epic_id>/Documentation.md`. Do not maintain two living
  copies.
- Sweep abandoned entries when the user resumes work on a different
  `work_id` so the ledger does not accumulate stale plans.
