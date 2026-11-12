"""The query history: every execution, its rows page by page, and a CSV export."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from sqlagent.core.deps import ContainerDep, SessionDep
from sqlagent.core.errors import AppError
from sqlagent.core.schemas import Page
from sqlagent.executions import service
from sqlagent.executions.schemas import ExecutionOut, RowsPage
from sqlagent.projects.access import Viewer

router = APIRouter(prefix="/api/v1/projects/{project_id}/executions", tags=["executions"])


@router.get(
    "", response_model=Page[ExecutionOut], summary="Queries run in the project, newest first"
)
async def list_executions(
    p: Viewer,
    session: SessionDep,
    connection_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    status: str | None = Query(None, pattern="^(succeeded|refused|failed|timeout|scan_limit)$"),
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> Page[ExecutionOut]:
    rows, nxt = await service.list_executions(
        session,
        p.project_id,
        connection_id=connection_id,
        actor_id=actor_id,
        status=status,
        cursor=cursor,
        limit=limit,
    )
    return Page[ExecutionOut](items=[service.to_out(r) for r in rows], next_cursor=nxt)


@router.get("/{execution_id}", response_model=ExecutionOut, summary="One query run")
async def get_execution(execution_id: uuid.UUID, p: Viewer, session: SessionDep) -> ExecutionOut:
    return service.to_out(await service.get(session, p.project_id, execution_id))


@router.get("/{execution_id}/rows", response_model=RowsPage, summary="A page of the stored result")
async def rows(
    execution_id: uuid.UUID,
    p: Viewer,
    session: SessionDep,
    container: ContainerDep,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
) -> RowsPage:
    ex = await service.get(session, p.project_id, execution_id)
    if ex.status != "succeeded":
        raise AppError("This query has no result to page through", code="no_result")
    return await service.page(container, ex, offset, limit)


@router.get(
    "/{execution_id}/export.csv",
    summary="The stored result as CSV",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {}}}},
)
async def export_csv(
    execution_id: uuid.UUID, p: Viewer, session: SessionDep, container: ContainerDep
) -> StreamingResponse:
    ex = await service.get(session, p.project_id, execution_id)
    if ex.status != "succeeded":
        raise AppError("This query has no result to export", code="no_result")
    return StreamingResponse(
        service.csv_stream(container, ex),
        media_type="text/csv; charset=utf-8",
        headers={"content-disposition": f'attachment; filename="sqlagent-{ex.id}.csv"'},
    )
