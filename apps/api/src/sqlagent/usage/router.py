from __future__ import annotations

from fastapi import APIRouter, Query

from sqlagent.core.deps import SessionDep
from sqlagent.projects.access import Viewer
from sqlagent.usage import service
from sqlagent.usage.schemas import UsageReport

router = APIRouter(prefix="/api/v1/projects/{project_id}/usage", tags=["usage"])


@router.get(
    "",
    response_model=UsageReport,
    summary="Questions, queries and tokens by day, connection and model",
)
async def usage(p: Viewer, session: SessionDep, days: int = Query(30, ge=1, le=366)) -> UsageReport:
    return await service.report(session, p.project_id, days)
