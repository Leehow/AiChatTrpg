"""HTTP route for the design-state -> parsed_v6 compile endpoint.

Split out of `routes/ruleset_drafts.py` so that file stays under the
400-line cap. The endpoint is attached to the same router via
`add_compile_routes(router)`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from orm.models import User
from routes.deps import current_user, db_session
from schemas.ruleset_draft import CompileDesignResponse
from services.ruleset_draft_compile import (
    CompileBlockedResult,
    CompileSuccessResult,
    compile_design_for_draft,
)


logger = logging.getLogger("chatrpg.ruleset_draft_compile")


def add_compile_routes(router: APIRouter) -> None:
    """Attach the compile-design endpoint to the given router."""
    router.add_api_route(
        "/{draft_id}/compile-design",
        post_compile_design,
        methods=["POST"],
        response_model=CompileDesignResponse,
        name="compile_design",
    )


async def post_compile_design(
    draft_id: str,
    db: AsyncSession = Depends(db_session),
    user: User = Depends(current_user),
) -> CompileDesignResponse:
    """Compile design_state -> parsed_v6 for the given draft.

    POST (not PATCH) because some CDNs / proxies block PATCH (see
    CLAUDE.md). The endpoint is idempotent within a given design_state
    snapshot.
    """
    result = await compile_design_for_draft(
        db, draft_id=draft_id, owner_id=user.id,
    )
    if isinstance(result, CompileBlockedResult):
        return CompileDesignResponse(
            status="blocked",
            parsed_v6_after=result.parsed_v6,
            validation_report=result.validation_report,
            ready_blockers=list(result.ready_blockers),
            design_phase=result.design_phase,
            error=result.error,
        )
    assert isinstance(result, CompileSuccessResult)
    return CompileDesignResponse(
        status="success",
        edit_id=result.edit_id,
        parsed_v6_after=result.parsed_v6,
        validation_report=result.validation_report,
        sections_emitted=list(result.sections_emitted),
        needs_dice_compile=result.needs_dice_compile,
        needs_character_ui_compile=result.needs_character_ui_compile,
        design_phase=result.design_phase,
    )
