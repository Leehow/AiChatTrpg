<p align="center">
  <img src="frontend/public/logo/chatrpg-logo-warm-transparent.png" alt="AiChatTrpg octopus logo" width="160" />
</p>

<h1 align="center">AiChatTrpg</h1>

<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-Hans.md">简体中文</a>
</p>

An open-source AI Game Master for tabletop RPGs. Bring your own LLM, point at a
ruleset PDF and an adventure module, and play.

> **Status**: Pre-alpha. Active development. Local-first self-hosting is the
> default; invited-account hosted test deployments are experimental.

## What it is

AiChatTrpg runs a structured TRPG session driven by an LLM acting as Game Master. It implements:

- **Three-phase pipeline** (preprocess → generate → postprocess) with streaming output
- **Zero function calling** — game state mutations via text markers parsed at end of turn
- **Dual memory** — structured JSON state (scenes, NPCs, plot threads) + LLM-compressed narrative for older turns
- **Pre-rolled dice pools** with deterministic outcome IR for fair, auditable checks
- **Scene-aware context** — current scene drives which rules and module sections are loaded into prompt
- **Multi-provider LLM** — OpenAI-compatible (OpenAI / DeepSeek / Kimi / GLM / Doubao / Qwen / Grok), Gemini, Claude

## What it isn't

- **Not a marketplace**: V1 ships with a "download from community URL" button. The community itself is just a list of JSON files hosted somewhere (GitHub Releases works fine).
- **Not a public SaaS yet**: V1 is local-first. Hosted deployments are a test
  mode, not a managed product.
- **Not open registration by default**: local installs bootstrap admins from
  `auth.json`; hosted tests can enable invite-only registration.

## Hosted test platform

An invite-only public test deployment is available at
[`test.aichattrpg.com`](https://test.aichattrpg.com/). It is meant for
early evaluation of registration, login, private rooms, and the current
single-player game flow.

The hosted platform is experimental. Do not upload sensitive personal data,
private campaign archives, API keys, or copyrighted books.

## Tech stack

**Backend**: Python 3.11+, FastAPI, SQLAlchemy, PostgreSQL, pgvector not required.

**Frontend**: Vite 8, React 19, TypeScript 5.7+, Tailwind CSS 4, TanStack Query, `@microsoft/fetch-event-source` for SSE-with-POST, `marked` + KaTeX for markdown/math, `react-virtuoso` for chat virtualization, `@3d-dice/dice-box` for dice visuals, `@hey-api/openapi-ts` + `@hey-api/client-fetch` for API client codegen.

**Sync**: API contracts compiled from FastAPI OpenAPI spec to a typed TypeScript client for the React frontend in this repo.

## Quick start

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://chatrpg:chatrpg@127.0.0.1:54318/chatrpg
cp ../auth.example.json ../auth.json
python run.py                       # http://localhost:8013

# Frontend
cd frontend
npm install
npm run dev                          # http://localhost:3013
```

## Authentication

Local installs use `auth.json` as the bootstrap admin source. On every backend
start, those accounts are synced into the database as admins so operators can
recover access by editing `auth.json` and restarting.

Hosted test deployments can enable invited player registration with env vars:

```bash
REGISTRATION_ENABLED=true
REGISTRATION_INVITE_REQUIRED=true
REGISTRATION_INVITE_CODES=alpha-test-code
REGISTRATION_INVITE_MAX_USES=1
JWT_SECRET=<long-random-secret>
```

New DB-created users are stored with PBKDF2-SHA256 password hashes. The
plaintext `auth.json` path is kept only for local bootstrap compatibility.

## Team Lead Mode (for contributors)

AiChatTrpg uses **Codex 组长模式 / Team Lead Mode** for non-trivial work: Codex
plans, dispatches Claude Code workers (`runclaude` TTY, latest Opus), reviews
diffs, validates, and reports. Workers operate under the marker
`[CHATRPG_TEAM_LEAD_WORKER_V1]` and a structured scope/handoff contract.

For multi-turn initiatives that need durable Done / Not Done memory across
worker handoffs, the lead keeps an **Active Plan Ledger** on disk under
`docs/active-plans/<work_id>.md` (indexed by `docs/active-plans/README.md`).
It sits between an inline chat summary and the full
`docs/epics/<epic_id>/` charter. Workers do not edit the ledger by default;
they contribute a "Plan ledger note for lead" in their handoff and the lead
serializes the update after review.

For the full protocol, read:

- `AGENTS.md` and `CLAUDE.md` (repo-level rules and the worker bridge).
- `.agents/skills/chatrpg-team-lead/` (lead playbook + references).
- `.agents/skills/chatrpg-worker/` (worker contract + marker / handoff specs).
- `docs/team-lead-mode-playbook.zh.md` (long-form Chinese write-up).

## Contributing and security

Contributions are welcome, with a bias toward small, reviewable changes while
the project is pre-alpha. Read `CONTRIBUTING.md` before opening a PR.

Report vulnerabilities privately as described in `SECURITY.md`. Do not paste
provider keys, invite codes, JWTs, private server details, copyrighted TRPG
books, or private campaign content into public issues.

## License

Apache License 2.0. AiChatTrpg is free to use, modify, and distribute,
including for commercial purposes, as long as redistribution follows the
Apache-2.0 license terms. In particular, Apache-2.0 includes an explicit
patent license and terminates that patent license for a party that files
patent litigation claiming the work infringes.

### A note on dependencies for commercial use

The default PDF text-extraction backend in `requirements.txt` (PyMuPDF) is **AGPL-3.0**, which is incompatible with closed-source commercial use. If you plan to ship AiChatTrpg commercially without releasing your modifications, swap PyMuPDF for one of these:

- **[MinerU](https://github.com/opendatalab/MinerU)** — Apache 2.0 + additional terms. Free for commercial use unless your MAU > 100M or monthly revenue > USD 20M. If you offer it as an online service, you must visibly attribute MinerU.
- **[pypdf](https://github.com/py-pdf/pypdf)** — BSD-3-Clause, no strings attached.
- **[pdfplumber](https://github.com/jsvine/pdfplumber)** — MIT.

The default ruleset/module parser is built into the backend; commercial deployments can swap the PDF text-extraction backend by configuring a different `RulesetParser` / `ModuleParser` adapter implementation.
