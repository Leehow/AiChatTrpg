# Lightweight Epic Docs Template

Use these four files only after the user confirms a non-trivial long-running
scope. They are product-level memory for `/plan` and `/goal`, not a replacement
for worker handoffs or validation evidence.

## `docs/epics/<epic_id>/Prompt.md`

```markdown
# Prompt — <epic_id>

## Goal

<User-visible outcome.>

## Non-Goals

- <Explicitly deferred or forbidden work.>

## Constraints

- <Repo rules, product boundaries, ports, providers, secrets, dependencies.>

## Deliverables

- <What should exist or behave differently when done.>

## Done When

- <Observable acceptance item.>
```

## `docs/epics/<epic_id>/Plan.md`

```markdown
# Plan — <epic_id>

| Milestone | Owner lane | Acceptance | Validation | Status |
|---|---|---|---|---|
| <M1> | lead / worker:<mode> | <observable result> | V0/V1/V2/V3/V4 | Todo |

## Repair Rules

- Failed required validation returns to revision before the next milestone.
- Items outside Prompt.md require user confirmation before entering scope.
```

## `docs/epics/<epic_id>/Implement.md`

```markdown
# Implement — <epic_id>

## Runbook

1. Confirm the current milestone and owner lane.
2. Dispatch Claude Code workers via `runclaude` only when code-affecting or
   multi-lane work requires delegation.
3. Read full worker handoffs before review or revision.
4. Run lead-owned single-lane validation directly.
5. Update Documentation.md with status and evidence.

## Stop Conditions

- Latest Opus/runclaude unavailable.
- Scope expands outside Prompt.md.
- Destructive git, secrets, new paid/external service, or irreversible
  migration is needed.
- A user question requires an answer before edits.
- Required validation is blocked and cannot be resolved inside current scope.
```

## `docs/epics/<epic_id>/Documentation.md`

```markdown
# Documentation — <epic_id>

## Status

<Todo / In Progress / Partial / Blocked / Done.>

## Decisions

| Time | Decision | Reason |
|---|---|---|

## Evidence

| Acceptance item | Evidence | Result |
|---|---|---|

## Residual Risk

- <Risk or deferred item.>
```
