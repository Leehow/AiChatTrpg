# ChatRPG Memory Runtime E2E

Browser-level memory runtime checks live here. The AI/browser agent may operate
the page like a player, but the pass/fail decision comes from API/runtime
artifacts:

- latest turn trace
- public memory view
- raw memory rows
- canonical state changes
- world-state snapshot

## Run

Install Playwright in this frontend workspace if it is not already available:

```bash
npm install -D @playwright/test
npx playwright install chromium
```

Then run against an existing test session:

```bash
export CHATRPG_BASE_URL=http://localhost:3013
export CHATRPG_API_URL=http://localhost:8013
export CHATRPG_SESSION_ID=<session-id>
export CHATRPG_TEST_TOKEN=<bearer-token>
npx playwright test frontend/e2e/memory-runtime.spec.ts
```

Optional:

```bash
export CHATRPG_SECRET_TERMS="管家其实是邪教徒,butler_cultist"
```

Artifacts are written to:

```txt
artifacts/e2e/memory-runtime/<scenario>/
```

## Expectations

The target session should already be set up with a ruleset, module, and
character. The spec intentionally does not create accounts, upload files, or
change sharing settings; it only opens the existing local session, sends normal
player turns, and reads debug endpoints.
