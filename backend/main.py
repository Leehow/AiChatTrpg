from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from core.config import get_settings
from core.database import dispose_engine, get_engine, get_session_factory
from core.user_bootstrap import sync_auth_users, sync_registration_invites
from orm.models import Base
from routes import (
    admin,
    auth,
    character_pool,
    health,
    llm_test,
    media,
    model_pool,
    modules,
    music,
    ocr,
    ruleset_drafts,
    rulesets,
    session_audio,
    session_bond_npcs,
    session_notes,
    session_time,
    sessions,
    users,
)


# Idempotent column additions for already-deployed dev databases.
# `Base.metadata.create_all` only creates new tables -- it never adds columns
# to existing ones. Each entry is a `ALTER TABLE ADD COLUMN IF NOT EXISTS`
# statement, safe to run on every boot. New installs hit `create_all` and
# never reach these.
_FORWARD_COLUMN_MIGRATIONS: tuple[str, ...] = (
    "ALTER TABLE rulesets ADD COLUMN IF NOT EXISTS character_ui JSON",
    "ALTER TABLE rulesets ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE model_pool_entries ADD COLUMN IF NOT EXISTS is_dialogue BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE model_pool_entries ADD COLUMN IF NOT EXISTS is_avatar BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE model_pool_entries ADD COLUMN IF NOT EXISTS is_illustration BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE model_pool_entries ADD COLUMN IF NOT EXISTS is_narration BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS preferences JSON NOT NULL DEFAULT '{}'",
    "ALTER TABLE trpg_memory_items ADD COLUMN IF NOT EXISTS source_quotes_json JSON NOT NULL DEFAULT '[]'",
    "ALTER TABLE trpg_memory_items ADD COLUMN IF NOT EXISTS identity_scope VARCHAR(40) NOT NULL DEFAULT 'durable_fact'",
    "ALTER TABLE trpg_memory_items ADD COLUMN IF NOT EXISTS reinforcement_count INTEGER NOT NULL DEFAULT 0",
    (
        "CREATE INDEX IF NOT EXISTS ix_trpg_memory_items_identity_scope "
        "ON trpg_memory_items (session_id, identity_scope, status)"
    ),
    # P0.1 rule-design-agent authoring fields. Mirror the alembic
    # migration `006_ruleset_drafts_design_state.py` so existing dev
    # DBs that never ran alembic still pick up the columns on next boot.
    "ALTER TABLE ruleset_drafts ADD COLUMN IF NOT EXISTS design_state JSON NOT NULL DEFAULT '{}'",
    "ALTER TABLE ruleset_drafts ADD COLUMN IF NOT EXISTS design_phase VARCHAR(64) NOT NULL DEFAULT 'intake'",
    "ALTER TABLE ruleset_drafts ADD COLUMN IF NOT EXISTS validation_report JSON NOT NULL DEFAULT '{}'",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in _FORWARD_COLUMN_MIGRATIONS:
            await conn.execute(text(stmt))

    settings = get_settings()
    factory = get_session_factory()
    async with factory() as db:
        await sync_auth_users(db, settings)
        await sync_registration_invites(db, settings)

    yield

    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ChatRPG",
        description="Open-source AI Game Master for tabletop RPGs",
        version="0.1.0-alpha",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            settings.frontend_url,
            "http://localhost:3013",
            "http://127.0.0.1:3013",
            "http://localhost:3010",
            "http://127.0.0.1:3010",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(character_pool.router)
    app.include_router(admin.router)
    app.include_router(llm_test.router)
    app.include_router(media.router)
    app.include_router(model_pool.router)
    app.include_router(modules.router)
    app.include_router(music.router)
    app.include_router(ocr.router)
    app.include_router(rulesets.router)
    app.include_router(ruleset_drafts.router)
    app.include_router(sessions.router)
    app.include_router(session_audio.router)
    app.include_router(session_bond_npcs.router)
    app.include_router(session_notes.router)
    app.include_router(session_time.router)
    app.include_router(users.router)

    return app


app = create_app()
