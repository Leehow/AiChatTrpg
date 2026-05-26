# ChatRPG Validation Recipes

Use these recipes to choose validation levels. They are project-specific
acceptance guidance; they do not override `AGENTS.md`, `CLAUDE.md`, or the
team-lead hard gates.

## Dice IR / Check Engines

Required: V0 no LLM adjudication bypass, V1 deterministic golden cases, and V4
invalid formula or boundary values.

## Runtime Markers / Turn Pipeline

Required: V1 preprocess -> generate -> postprocess golden turn, V4 malformed
or repeated marker, and V3 if visible in UI. Check that `[ROLL]`,
`[SET_SCENE]`, `[UPDATE_MEMORY]`, `[CREATE_NPC]`, and `[SEARCH_MODULE]` are
consumed or rendered by design, not leaked accidentally.

## Memory / Retrieval / Context

Required: V1 write/read/idempotency and V4 visibility isolation for player vs
GM vs NPC-private state. Include duplicate update in the same turn when
relevant.

## Provider Adapters

Required: V0 no `max_tokens`, configurable temperature, V1/V2 fake or mock
provider path, and V4 timeout/error/malformed response. Do not rely on real LLM
randomness as the only proof.

## Backend Routes / Schemas / Contracts

Required: V2 route/API smoke, `python scripts/compile_api/export_spec.py`, and
`npm run gen:api` when generated clients are committed. Frontend build follows
generated-client changes. No PATCH update routes.

## Frontend Chat / Session / Runtime UI

Required: V2 build, V3 browser user journey, and V4 reload/persistence or
negative path when relevant.

Example journey: open frontend on 3013, confirm backend 8013, open or create a
session, send a player action, observe user message and streamed GM response,
verify dice UI instead of raw marker when a roll occurs, refresh, and check
console/network evidence.

## Ruleset / Module Parser

Required: V1 fixture PDF/Markdown parse to schema, V4 empty/corrupt file, and
V2/V3 if upload UI is touched.

## Process / Skill Updates

Required: V0 no secrets and no contradiction with `AGENTS.md` or `CLAUDE.md`.
Use adversarial review when autonomy, edit authority, worker identity, or
validation standards change.
