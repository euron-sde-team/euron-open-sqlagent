"""Generate, validate, explain and execute SQL directly (the chat uses the same services)."""

from __future__ import annotations

from fastapi import APIRouter

from sqlagent.connections import service as connections
from sqlagent.core.deps import ContainerDep, SessionDep
from sqlagent.executions import service as executions
from sqlagent.executions.schemas import ExecuteRequest, ExecutionWithRows
from sqlagent.projects.access import Querier
from sqlagent.sql import service
from sqlagent.sql.schemas import (
    ExplainOut,
    ExplainRequest,
    GenerateOut,
    GenerateRequest,
    SqlInput,
    Validation,
)
from sqlagent.usage import service as usage

router = APIRouter(prefix="/api/v1/projects/{project_id}/sql", tags=["sql"])


async def _dialect(session: SessionDep, project_id: object, body: SqlInput) -> str:
    if body.connection_id is not None:
        conn = await connections.get(session, project_id, body.connection_id)  # type: ignore[arg-type]
        return conn.kind
    assert body.dialect is not None
    return body.dialect


@router.post(
    "/generate",
    response_model=GenerateOut,
    summary="Write SQL for a question against the connection's real schema (not executed)",
)
async def generate(
    body: GenerateRequest, p: Querier, session: SessionDep, container: ContainerDep
) -> GenerateOut:
    conn = await connections.get(session, p.project_id, body.connection_id)
    provider = await service.provider_for(session, p.project_id, body.provider_id)
    gen = await service.generate(container, session, conn, body.question, provider)
    await usage.record(
        session,
        conn.project_id,
        conn.id,
        gen.model,
        questions=1,
        input_tokens=gen.usage.input_tokens,
        output_tokens=gen.usage.output_tokens,
    )
    await session.commit()
    return GenerateOut(
        sql=gen.sql,
        explanation=gen.explanation,
        valid=gen.valid,
        refusal=gen.refusal,
        refusal_code=gen.refusal_code,
        tables=gen.tables,
        provider=gen.provider,
        model=gen.model,
        input_tokens=gen.usage.input_tokens,
        output_tokens=gen.usage.output_tokens,
        model_ms=gen.model_ms,
    )


@router.post(
    "/validate",
    response_model=Validation,
    summary="Run the SQL guard over a query: is it exactly one read-only SELECT?",
)
async def validate(body: SqlInput, p: Querier, session: SessionDep) -> Validation:
    return service.validate(body.sql, await _dialect(session, p.project_id, body))


@router.post(
    "/explain",
    response_model=ExplainOut,
    summary="Explain any query in plain language (never executed)",
)
async def explain(
    body: ExplainRequest, p: Querier, session: SessionDep, container: ContainerDep
) -> ExplainOut:
    dialect = await _dialect(session, p.project_id, body)
    provider = (
        await service.provider_for(session, p.project_id, body.provider_id)
        if body.use_model
        else None
    )
    return await service.explain(container, body.sql, dialect, provider)


@router.post(
    "/execute",
    response_model=ExecutionWithRows,
    summary="Run a read-only query: guarded, on a read-only connection, under its limits",
)
async def execute(
    body: ExecuteRequest, p: Querier, session: SessionDep, container: ContainerDep
) -> ExecutionWithRows:
    conn = await connections.get(session, p.project_id, body.connection_id)
    outcome = await executions.execute(container, session, conn, body.sql, p.actor, source="sql")
    ex = outcome.execution
    page = (
        await executions.page(container, ex, 0, body.page_size)
        if ex.status == "succeeded"
        else None
    )
    return ExecutionWithRows(**executions.to_out(ex).model_dump(), page=page)
