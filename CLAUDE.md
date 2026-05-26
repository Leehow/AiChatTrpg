# CLAUDE.md

This file provides guidance to Claude Code when working in the AiChatTrpg repository.

## Project Vision

AiChatTrpg is an **open-source LLM-GM-based TRPG system** — both an **engine** that other developers can embed in their own products, and a **complete out-of-the-box application** so players can install it and start a session immediately.

- **Path**: `<repo-root>`
- **License**: Apache-2.0
- **Status**: Pre-alpha, active development.
- **Origin**: The TRPG game-loop pattern was originally prototyped inside the closed-source ChatLab project. AiChatTrpg is the clean-room reimplementation, now an **independent project**. ChatLab maintains its own fork; there is no sync relationship.

### Target audience

- **Solo players** — install, point at a ruleset PDF, start playing.
- **TRPG community** — share rulesets, modules, and characters; co-develop house rules.
- **TRPG developers** — embed the engine (pipeline + dice IR + check engines + ruleset parser) into their own apps via Python imports or HTTP API.

## MVP Scope (V1)

In scope:

- ✅ **Single-player local** — one user runs the whole stack on their own machine.
- ✅ **Built-in ruleset parser** — PDF → structured v6 JSON. No "bring your own JSON" assumption.
- ✅ **Built-in module parser** — PDF/markdown adventure modules → playable structure.
- ✅ **Multi-LLM provider** — GPT (OpenAI), Claude (Anthropic), Gemini (Google), and a configurable local-LLM endpoint (any OpenAI-compatible server).
- ✅ **Multimedia** — TTS, character portraits, scene illustrations, BGM. Provider-pluggable, but at least one working default for each.
- ✅ **Dice IR + check engines** — the deterministic rule resolution layer (CoC d100, BRP d100, d20-vs-DC, PBTA 2d6, pool-count, custom-LLM) is a hard requirement, never bypassable.
- ✅ **In-game pipeline** — three-phase turn loop (preprocess → generate → postprocess), markers (`[ROLL]`, `[SET_SCENE]`, `[UPDATE_MEMORY]`, `[CREATE_NPC]`, `[SEARCH_MODULE]`, …), structured + narrative memory, scene-aware retrieval.

Out of scope for V1:

- ❌ Multi-user rooms / GM-as-AI with multiple human players
- ❌ Cloud-hosted SaaS deployment
- ❌ Auth / OAuth / invitation codes — just `SINGLE_USER_ID` from env
- ❌ Mobile apps

These are not architectural ceilings — they're MVP boundaries. The engine layer should not preclude later multi-user expansion.

## Architecture

### Engine vs. App

- **Engine layer** (`backend/agents/trpg/`, `backend/services/<engine>/`) — pure game logic, depends only on adapter protocols. No FastAPI imports, no DB ORM imports, no React. Importable as a Python library.
- **App layer** (`backend/routes/`, `backend/orm/`, `backend/main.py`, `frontend/`) — wraps the engine in a FastAPI + React shell with persistence, file uploads, an admin panel, and a chat UI.

The two layers ship in the same repo for now; the engine may move to its own package later.

### Adapter pattern (for providers, not for licensing)

The engine talks to the outside world through `typing.Protocol` adapters. Different deployments can swap implementations:

- `LLMAdapter` — chat + streaming. Implementations: OpenAI, Anthropic, Google GenAI, generic OpenAI-compatible.
- `TTSAdapter` — speech synthesis. Implementations: Gemini TTS, MiniMax, OpenAI TTS, none.
- `ImageAdapter` — portrait + scene illustration. Implementations: tuzi-relay, OpenAI, Gemini image, none.
- `RulesetParser` / `ModuleParser` — PDF → structured. Default implementation lives in chatrpg (MinerU + LLM staged pipeline). Embedders can replace with their own.
- `Storage` — local filesystem default; embedders can swap for S3/OSS.
- `Clock` — for testability.

Adapter protocols live in `backend/agents/trpg/framework/adapters/protocols.py`. Real implementations register at startup via `backend/core/registry.py`. Swapping a provider should mean changing one wiring line, not the engine.

## Tech Stack (subject to change beyond the pillars)

**Pillars (won't change in V1):**

- Python 3.11+, FastAPI, async SQLAlchemy 2.x, asyncpg, PostgreSQL
- React 19 + Vite (Rolldown) + TypeScript 5.7+, Tailwind CSS 4

**Currently used (may evolve):**

- Backend: Alembic, Pydantic v2, `openai` / `google-genai` / `anthropic` SDKs
- Frontend: `@tanstack/react-query` for server state, `@microsoft/fetch-event-source` for SSE-with-POST, `marked` + `katex` for markdown/math rendering, `react-virtuoso` for chat virtualization, `@3d-dice/dice-box` for dice visuals, `@hey-api/openapi-ts` + `@hey-api/client-fetch` for API client codegen

## API Contract Compiler

Single source of truth: `backend/schemas/` (Pydantic models) + FastAPI route signatures.

```
backend/schemas/ + routes/
        │
        │  scripts/compile_api/export_spec.py   (FastAPI app → JSON)
        ▼
contracts/openapi.json + contracts/sse_events.json
        │
        │  npm run gen:api   (@hey-api/openapi-ts → @hey-api/client-fetch)
        ▼
frontend/src/api/generated/
```

Always commit `contracts/openapi.json` and `contracts/sse_events.json` so the compiler is reproducible. Generated TS clients under `frontend/src/api/generated/` are committed too.

## Critical Rules

- **QUESTIONS GET ANSWERS, NOT EDITS**: When the user asks a question (e.g. "为什么…", "什么情况", "怎么样", "可以吗", "靠谱吗"), *answer the question*. Do NOT open files, run tools, or modify code as a substitute for replying. If the answer suggests a change, propose it in words and wait for explicit confirmation before touching code. Pattern to avoid: user asks "why X?" → assistant immediately starts editing X.
- **DO LESS, NOT MORE**: When the user says "just error", "remove the limit", "don't manage that" (你别管, 我说的你别管, 报错就行) — literally remove behavior, do not add error-handling layers, custom exceptions, or fallback systems unless asked. Match the verb count of the request: "remove" means delete only, not "delete and replace".
- **ASK BEFORE CODING**: For bug fixes, feature changes, or refactoring, discuss approach first.
- **ASK, DON'T ASSUME DEFAULTS**: When the user hasn't specified a number, scope, or default value (truncation limit, retry count, batch size, etc.), ASK. Don't silently propose "a reasonable value" — that still counts as 自作主张.
- **NEVER set `max_tokens`** on any LLM call. Let the model finish naturally.
- **NEVER hardcode temperature** in LLM calls — make it configurable.
- **NEVER use PATCH method**: many CDNs / proxies block PATCH. Use POST for updates.
- **NEVER use destructive git** (`git restore`, `git reset --hard`, `git checkout --`) on uncommitted changes without explicit permission. The user commits infrequently; assume working-tree changes are precious.
- **DEFAULT-MODE TASKS END IN A COMMIT**: In normal non-worker mode, after completing a user-requested implementation, documentation, configuration, or generated-artifact task that changed repository files, validate the result, inspect `git status` and relevant diffs, stage only the files intentionally changed for that task, and create a focused commit before final handoff. Skip this for analysis/review-only tasks, explicit no-commit requests, blocked or incomplete work, and `[CHATRPG_TEAM_LEAD_WORKER_V1]` worker mode. Never commit unrelated pre-existing working-tree changes; ask which files belong if the boundary is unclear.
- **Max file size**: 400 lines is the soft target for LLM-authored modules.
  Existing files over 600 lines enter the split backlog unless they are
  generated, locale dictionaries, docs/private review packs, broad debug
  diagnostics, or otherwise carry a written deferral/exemption reason.
- **English-only**: All variable names, comments, prompt text in English. Localised values (UI strings) live in i18n files.
- **Single user (V1)**: One local user. No auth, no JWT, no invitation codes. Just `SINGLE_USER_ID` from env. The schema may carry a `user_id` column for forward compatibility, but enforcement is out of scope.

## Ports

- Backend: `8013`
- Frontend dev: `3013`

## Team-lead worker mode (Claude Code bridge)

When a prompt opens with `[CHATRPG_TEAM_LEAD_WORKER_V1]`, you are running as a
delegated worker under Codex 组长模式. Read
`.agents/skills/chatrpg-worker/SKILL.md` and follow it before editing
anything. The skill is the contract: parse the structured header (required
fields `task_id`, `mode`, `scope_own`, `scope_off`, `handoff`), confirm pwd /
repo root / declared worker backend / latest Opus model tier, restate the task,
stay inside `scope_own`, escalate via
`.tmp/team-lead/questions-<task_id>.md`, and write the handoff report to the
path the marker specifies. You are a collaboration partner —
disagree with the plan when warranted, but never silently widen scope. Do not
stage or commit.

If the brief references a long-running epic, treat `docs/epics/<epic_id>/` as
context, not as permission to expand scope. `Prompt.md` freezes the goal,
non-goals, constraints, deliverables, and Done-when; `Plan.md` maps milestones
to acceptance and validation; `Implement.md` is the runbook; and
`Documentation.md` records status and evidence. Read only the epic files cited
by the lead, follow the marker `scope_own` / `scope_off`, and update epic docs
only when the dispatch explicitly grants that path.

If the marker carries `work_id` or the brief cites
`docs/active-plans/<work_id>.md`, treat that file the same way: read it as
Active Plan Ledger context, do not edit it unless the dispatch marker
explicitly places the path in `scope_own`, and add a concise "Plan ledger
note for lead" to the handoff. The Codex lead serializes ledger updates
after review and validation.

Worker modes may include `test_design`, `adversarial_review`, and
`browser_verification` in addition to implementation, investigation, review,
revision, and verification. Browser-visible chat, session, upload, provider,
SSE, or runtime behavior requires real browser evidence when assigned; a build
alone is not enough. Use Claude Code subagents only as allowed by the worker
skill: bounded, depth 1, max 3, and never for primary implementation unless the
marker explicitly sets `subagent_policy: implementation_allowed`.

## Common Commands

```bash
# Backend
cd backend
source .venv/bin/activate
python run.py                       # dev server

# Database
alembic upgrade head
alembic revision --autogenerate -m "description"

# Frontend
cd frontend
npm install
npm run dev
npm run build

# Generate API client (runs from repo root)
python scripts/compile_api/export_spec.py    # backend → contracts/*.json
npm run gen:api                              # contracts/*.json → frontend/src/api/generated/
```
