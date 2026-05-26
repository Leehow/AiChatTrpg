# Worker handoff template

Write to the path given by the marker `handoff:` field, typically
`.tmp/team-lead/worker-<task_id>-<timestamp>.md`. The handoff is a review
document, not a transcript — Codex must be able to start review from this file
alone.

Copy the structure below. Keep prose short. Cite file:line whenever a claim
references specific code. No marketing language ("seamless", "robust");
evidence beats assertion.

For non-trivial tasks, start with a small YAML frontmatter block so the lead can
triage status quickly. Keep it factual; do not add secrets or raw logs. Tiny
read-only reports may omit frontmatter when it would add noise.

---

```markdown
---
task_id: <task_id>
work_id: <ledger work_id, or omit if not ledger-backed>
mode: <mode>
backend: tty | cc-background | cc-agent-view | cc-internal-subagents
subagent_policy: research_only | implementation_allowed
observability: full | final_only
status: pass | partial | fail | blocked
scope_honored: true | false
latest_opus_confirmed: true | false
required_validation_status: pass | partial | fail | not_required | blocked
browser_validation_required: true | false
browser_validation_status: pass | partial | fail | not_required | blocked
blocking_questions: []
not_done: []
---

# Worker handoff — <task_id>

## Header

- Worker: Claude Code (model id, e.g. `claude-opus-4-7`), backend `<backend>`
- Launch/context: TTY via runclaude / Claude Code background session /
  Claude Code Agent View session / parent worker with internal subagents
- Terminal manager: tmux `<session>:<window>.<pane>` / none / unknown /
  not-applicable
- Repo root confirmed: `<repo-root>`
  (`pwd` + `git rev-parse --show-toplevel` printed at activation)
- Branch: <branch>
- Timestamp: <YYYY-MM-DD HH:MM:SS>
- Marker echoed:
  - task_id:      <id>
  - work_id:      <ledger work_id, or "none" if not ledger-backed>
  - mode:         <mode>
  - scope_own:    <paths>
  - scope_off:    <paths>
  - risk_budget:  <level>
  - backend:      <backend>
  - subagent_policy: <policy>
  - observability: <full/final_only>
- Scope guardrails honored: yes / no — if no, explain in §7.
- Other workers' uncommitted changes preserved: yes / no.

---

## 1. Task restatement

<2–4 sentences in your own words. If this disagrees with the brief, you should
have already escalated — note the escalation here and STOP if blocking.>

## 2. Approach and alternatives considered

<Design note: the path you took, in 3–8 sentences.>

**Alternatives rejected:**

- <alternative A> — rejected because <reason>.
- <alternative B> — rejected because <reason>.

(If you considered no alternatives, say so honestly. That itself is a signal
the lead may want to know.)

## 3. Files changed

| Path | Why this file changed |
|---|---|
| <path:line-range> | <1–3 line rationale, not a diff dump> |

If `mode: investigation` / `review` / `verification`, replace with **Files
inspected** and add a short finding per file.

## 4. Validation

| Command | Outcome | Notes |
|---|---|---|
| `<exact command run>` | pass / fail / partial | <key output, error message, etc.> |

If a check could not run, list it here with "could not validate because X".
Do not silently skip. "I read the code and it looks correct" is **not**
validation.

For UI changes, include browser evidence (URL, port, observed state). If
browser validation was blocked, state the blocker.

When acceptance has multiple items, include this table under Validation:

| Acceptance item | Required level | Evidence | Outcome |
|---|---:|---|---|
| <item> | V0/V1/V2/V3/V4 | <command, browser step, fixture, or report path> | pass/fail/blocked |

## 5. Subagent results

| Name / type | Purpose | Finding | How you verified the claim |
|---|---|---|---|

Omit this section entirely if no subagents were used. Include subagent policy,
count, and total depth (must be ≤ 1). If any subagent performed primary
implementation, state where `subagent_policy: implementation_allowed` was
declared and how you reviewed the result.

## 6. Risks and blockers

- <Edge cases not tested.>
- <Places where behavior may shift unexpectedly.>
- <Working-tree interactions with parallel workers.>
- <Any check that was deferred and why.>

## 7. Open questions

- **Blocking** (these stop further work until Codex answers):
  - <Q-id> — see `.tmp/team-lead/questions-<task_id>.md`
- **Non-blocking** (proceeded with a documented assumption):
  - <Q-id> — assumption made: <one sentence>

If the task is `BLOCKED`, this section explains why and the handoff stops
being a deliverable — it is now a stop-state report for the lead.

## 8. Scope ledger

Every requested item must appear. No silent drops.

| Requested item | Status | Note |
|---|---|---|
| <item 1> | Done / Not Done / Deferred | <reason and follow-up if not Done> |

If the dispatch is ledger-backed (`work_id` set or the brief cited
`docs/active-plans/<work_id>.md`), make this table's rows map 1:1 to ledger
items so the lead's serialized update is mechanical.

## 9. Recommended next steps for the lead

**Plan ledger note for lead:** <1–3 bullets if the dispatch is ledger-backed:
name the `work_id`, list each ledger item whose status the lead should
change, and reference evidence by file:line or handoff path. Use
`not applicable` with reason if no `work_id` was provided. Do not edit
`docs/active-plans/<work_id>.md` directly unless this path is in
`scope_own`.>

- <concrete action 1>
- <concrete action 2>

Examples: "review diff at <files>", "dispatch verification worker for <area>",
"run `npm run gen:api` if the lead is satisfied", "merge after Q2 resolved",
"lead should flip `docs/active-plans/<work_id>.md` item X from In Progress
to Done".

## 10. Runtime confirmation

- Declared backend: tty / cc-background / cc-agent-view /
  cc-internal-subagents
- Actual backend confirmed: yes / no — explain if no.
- runclaude TTY: yes / no / not-applicable
- Background or Agent View session: id/link/name / none / not-applicable /
  unknown
- Parent-worker internal subagents: yes / no; count <n>; max depth <n>
- tmux: `<session>:<window>.<pane>` / none / unknown. If tmux was used, include
  the output of `tmux display-message -p '#S:#I.#P #{window_name}'`.
- Model tier: <model id> — latest Opus available: yes / no.
  If no, explain why work proceeded; otherwise the lead should have stopped
  the dispatch.
- Effort / permission mode / settings context: <visible runtime details, or
  not exposed>.
- Destructive git: none / list of commands and explicit user permission.
- `--no-verify` / `--force` / signing bypass used: no / explanation.
```

---

## Style discipline

- Short prose under each header. The goal is critical context, not
  autobiography.
- File:line citations whenever a claim refers to specific code.
- No marketing language. The lead is reviewing, not buying.
- Validation evidence beats assertion: "I ran X and got Y" beats "looks
  correct".
- Section 8 (scope ledger) is non-negotiable. Without it, partial completion
  looks like full completion and the lead's review is forced into archaeology.

## When to deviate from this template

You may add sections (e.g., "Migration notes", "Performance impact") if the
task warrants. You may not remove the required sections (1–10 above). If a
section is genuinely empty, write a single sentence explaining why — do not
silently delete the heading.
