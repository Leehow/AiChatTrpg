# AiChatTrpg Validation Matrix V0-V4

Every acceptance item should map to evidence. Use this as a shared vocabulary
for lead plans, worker prompts, handoffs, and final reports.

| Level | Name | Required when | Evidence |
|---:|---|---|---|
| V0 | Static guard | Any code-affecting change | Rule scan, grep, boundary check, generated-file awareness |
| V1 | Deterministic check | Engine/runtime/parser/memory/check logic | Unit, golden, fixture, or fake-provider check with expected output |
| V2 | API/contract/build | Routes, schemas, generated clients, frontend compile | OpenAPI/SSE export, generated client, build/test output |
| V3 | Browser user journey | User-visible frontend/chat/session/upload/provider/runtime behavior | Real browser steps, visible state, correct ports, console/network evidence |
| V4 | Adversarial/regression | Non-trivial behavior, bug fix, stateful flow | Invalid input, empty state, reload, provider failure, stream interruption, visibility boundary |

## Hard Rules

- UI-visible behavior is not Done without V3 evidence unless explicitly
  deferred by the user.
- `npm run build` is V2, not V3.
- "The page loads" is not a user journey.
- Reading code is not validation.
- If required validation is blocked, status is Partial or Blocked, not Done.

## Acceptance-To-Validation Table

Use this shape in plans or handoffs when the task has multiple acceptance
items:

| Acceptance item | Required level | Command or browser step | Outcome | Evidence |
|---|---:|---|---|---|
| <user can send a chat message and see streamed GM answer> | V3 | Open app, select session, send message, observe stream | pass/fail | URL, screenshot/DOM text, network status |

## Browser Evidence Minimum

- Frontend URL and port.
- Backend URL and port.
- Database/test target if relevant.
- Seed data or fixture.
- Exact user steps.
- Expected visible result.
- Actual visible result.
- Console errors or explicit absence.
- Failed network requests or explicit absence.
- Screenshot path or DOM/text evidence.
- Refresh/persistence result when state should persist.
