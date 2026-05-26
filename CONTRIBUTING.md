# Contributing To ChatRPG

Thanks for taking a look. ChatRPG is pre-alpha and moving quickly, so small,
focused contributions are easiest to review.

## Project Shape

ChatRPG is local-first by default. The hosted `test.aichattrpg.com` deployment
is an invite-only test platform, not a managed SaaS product.

The repo currently contains both:

- a FastAPI/PostgreSQL backend under `backend/`;
- a Vite/React frontend under `frontend/`.

Read `README.md`, `CLAUDE.md`, and `AGENTS.md` before larger changes.

## Before You Open An Issue Or PR

- Search existing issues first.
- Keep bug reports reproducible with the smallest ruleset/module sample that
  demonstrates the issue.
- Do not upload copyrighted TRPG books, private campaign notes, or real
  provider keys.
- Do not paste secrets, invite codes, JWTs, database URLs with passwords, or
  private server details.

Security issues should follow `SECURITY.md`, not a public issue.

## Local Setup

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../auth.example.json ../auth.json
python run.py
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

The default dev ports are backend `8013` and frontend `3013`.

## Validation

For backend-only changes, run focused Python tests or compile checks for the
touched area. For frontend changes, run:

```bash
cd frontend
npm run build
```

When API schemas change, regenerate and commit the contracts/client:

```bash
python scripts/compile_api/export_spec.py
cd frontend
npm run gen:api
```

## Style Notes

- Keep code and prompts in English; localized UI text belongs in i18n files.
- Do not set fixed `max_tokens` on LLM calls.
- Do not hardcode model temperature; make it configurable.
- Use POST for update-style API calls because some proxies block PATCH.
- Keep the engine/app boundary clear when touching TRPG runtime logic.

## Licensing

ChatRPG is Apache-2.0. Contributions submitted through issues, pull requests,
or repository discussions are accepted under the same license unless explicitly
marked otherwise.

The default PDF extraction dependency, PyMuPDF, is AGPL-3.0. Closed-source
commercial users should replace that adapter; see the README dependency note.
