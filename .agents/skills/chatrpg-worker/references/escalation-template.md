# Escalation block template

Append one block to `.tmp/team-lead/questions-<task_id>.md` per question. The
file is append-only — do not truncate previous blocks even if they have been
answered. Codex reviews the full thread.

## When to escalate

See `SKILL.md` → "Escalation protocol" for triggers. Short list:

- Required marker field missing or empty.
- Task restatement materially disagrees with the brief.
- Two interpretations both fit the brief and produce different changes.
- The intended change crosses `scope_off`.
- The intended action is beyond `risk_budget` or is irreversible.
- A check failed and you cannot localize the cause.
- You believe the plan is wrong.

## Block format

```markdown
## Q<n> — <one-line summary, ≤80 chars>

- Status: blocking | non-blocking
- Raised: <YYYY-MM-DD HH:MM>
- Context: <file:line evidence, or brief context>
- Ambiguity: <the specific decision point, one or two sentences>
- Candidates considered:
  1. <interpretation A> — pros / cons
  2. <interpretation B> — pros / cons
  (add more if needed; do not invent options to pad)
- Worker's lean: <which one and why, or "no clear winner">
- Default action absent input:
    - if blocking: BLOCKED — exiting cleanly until lead responds
    - if non-blocking: <what the worker will do, in one sentence>
- Risk if wrong: <one sentence on what breaks if Codex picks the other option>
```

## Examples

### Example 1 — blocking, scope_off conflict

```markdown
## Q1 — Fix requires editing backend/services/character_creator.py, which is in scope_off

- Status: blocking
- Raised: 2026-05-05 16:14
- Context: backend/agents/trpg/check_engines.py:142 calls into `character_creator.resolve_skill_target`, which is where the actual bug lives.
- Ambiguity: The brief named `check_engines.py` as scope_own and `services/**` as scope_off, but the failing path crosses both modules.
- Candidates considered:
  1. Patch only `check_engines.py` with a workaround that masks the upstream bug. Cons: leaves the real bug; will break again.
  2. Expand scope to include `character_creator.py`. Pros: fixes the root cause. Cons: violates scope_off without lead approval.
- Worker's lean: option 2, but only with explicit lead approval to extend scope_own.
- Default action absent input: BLOCKED — exiting cleanly.
- Risk if wrong: option 1 ships a workaround that hides the real defect; option 2 without approval breaks the scope contract.
```

### Example 2 — non-blocking, ambiguous default value

```markdown
## Q2 — Truncation limit for memory snapshot field is unspecified

- Status: non-blocking
- Raised: 2026-05-05 16:31
- Context: backend/services/trpg_npc/assets.py:88 — new field `summary_text`. CLAUDE.md says "ASK, DON'T ASSUME DEFAULTS" but this is a non-user-facing internal cap.
- Ambiguity: How many characters before truncate? 500? 2000? Unbounded?
- Candidates considered:
  1. Cap at 1000 chars (matches existing `description` field).
  2. No cap — let downstream handle.
- Worker's lean: option 1; consistent with adjacent field.
- Default action absent input: I am proceeding with option 1 and surfacing this in the handoff. If Codex prefers otherwise, the change is one line.
- Risk if wrong: trivial — single-line revert.
```

### Example 3 — blocking, plan disagreement

```markdown
## Q3 — I believe the proposed approach is wrong

- Status: blocking
- Raised: 2026-05-05 16:44
- Context: brief proposes adding a retry-with-backoff wrapper around the LLM call in backend/llm/mock.py:212.
- Ambiguity: The brief assumes the failure is transient. Reading the code, the failure is deterministic — the mock returns an error string when prompt length exceeds 4096 chars, which the caller does not check. Retrying will hit the same error every time.
- Candidates considered:
  1. Implement the brief — adds a retry wrapper. Will not fix the bug.
  2. Counter-proposal — fix the caller in backend/services/trpg_ic_runner.py:91 to validate prompt length and chunk before calling. Smaller change, fixes the actual cause.
- Worker's lean: option 2 strongly. Option 1 will close this ticket and reopen the same bug next session.
- Default action absent input: BLOCKED — exiting cleanly. Will not implement option 1 silently.
- Risk if wrong: option 1 ships dead code (retry that never succeeds) and the bug remains.
```

## Style discipline

- One block per question. Do not concatenate.
- Cite files and line numbers.
- No padding. If the choice is one-versus-other, two candidates is enough.
- The "Risk if wrong" line is mandatory — it forces you to articulate the
  cost of a wrong choice, which is the information Codex needs.
- Do not announce escalations in the handoff report; reference the file path
  and the Q-number.

## After Codex responds

Codex may answer in the chat, in the file, or by issuing a `revision` worker
prompt. If Codex answers in the file, leave the original block intact and add
the response below it under a `### Lead response` subsection. Do not edit your
original block — append.
