from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, Response, UploadFile

from sqlagent.connections import service
from sqlagent.connections.schemas import (
    ConnectionOut,
    ConnectionUpdate,
    Limits,
    ServerConnection,
    TestResult,
)
from sqlagent.core.deps import ContainerDep, SessionDep
from sqlagent.projects.access import Editor, Viewer
from sqlagent.schema import service as schemas
from sqlagent.schema.schemas import SchemaOut

router = APIRouter(prefix="/api/v1/projects/{project_id}/connections", tags=["connections"])


@router.get("", response_model=list[ConnectionOut], summary="Database connections")
async def list_connections(p: Viewer, session: SessionDep) -> list[ConnectionOut]:
    return await service.list_connections(session, p.project_id)


@router.post(
    "",
    response_model=ConnectionOut,
    status_code=201,
    summary="Add a PostgreSQL or MySQL database (the password is sealed, never returned)",
)
async def create_connection(
    body: ServerConnection, p: Editor, session: SessionDep, container: ContainerDep
) -> ConnectionOut:
    conn = await service.create_server(container, session, p, body)
    return await service.out(session, conn)


@router.post(
    "/sqlite", response_model=ConnectionOut, status_code=201, summary="Add a SQLite database file"
)
async def create_sqlite(
    p: Editor,
    session: SessionDep,
    container: ContainerDep,
    name: str = Form(min_length=1, max_length=120),
    file: UploadFile = File(...),
    max_rows: int = Form(1000, ge=1, le=100_000),
    max_scan_rows: int = Form(10_000_000, ge=1),
    timeout_s: int = Form(30, ge=1, le=600),
    sample_values: bool = Form(False),
    description: str = Form("", max_length=2000),
) -> ConnectionOut:
    limits = Limits(max_rows=max_rows, max_scan_rows=max_scan_rows, timeout_s=timeout_s)
    conn = await service.create_sqlite(
        container,
        session,
        p,
        name,
        file,
        limits,
        sample_values=sample_values,
        description=description,
    )
    return await service.out(session, conn)


@router.post(
    "/test",
    response_model=TestResult,
    summary="Test a connection before saving it: real latency, server version, read-only",
)
async def test_unsaved(body: ServerConnection, p: Editor, container: ContainerDep) -> TestResult:
    return await service.test(
        container, service.unsaved(p.project_id, body), password=body.password or ""
    )


@router.get("/{connection_id}", response_model=ConnectionOut, summary="One connection")
async def get_connection(connection_id: uuid.UUID, p: Viewer, session: SessionDep) -> ConnectionOut:
    return await service.out(session, await service.get(session, p.project_id, connection_id))


@router.patch("/{connection_id}", response_model=ConnectionOut, summary="Change a connection")
async def update_connection(
    connection_id: uuid.UUID,
    body: ConnectionUpdate,
    p: Editor,
    session: SessionDep,
    container: ContainerDep,
) -> ConnectionOut:
    conn = await service.get(session, p.project_id, connection_id)
    conn = await service.update(container, session, p, conn, body)
    return await service.out(session, conn)


@router.delete(
    "/{connection_id}",
    status_code=204,
    summary="Delete a connection with its schema cache, conversations and templates",
)
async def delete_connection(
    connection_id: uuid.UUID, p: Editor, session: SessionDep, container: ContainerDep
) -> Response:
    conn = await service.get(session, p.project_id, connection_id)
    await service.delete(container, session, p, conn)
    return Response(status_code=204)


@router.post(
    "/{connection_id}/test",
    response_model=TestResult,
    summary="Test a saved connection: real latency, server version, read-only session",
)
async def test_connection(
    connection_id: uuid.UUID, p: Editor, session: SessionDep, container: ContainerDep
) -> TestResult:
    conn = await service.get(session, p.project_id, connection_id)
    result = await service.test(container, conn)
    await service.record_test(session, conn, result)
    return result


@router.get(
    "/{connection_id}/schema",
    response_model=SchemaOut,
    summary="The discovered schema: tables, columns, types, keys, indexes, row counts",
    description="Served from the schema cache; discovered on first use.",
)
async def get_schema(
    connection_id: uuid.UUID, p: Viewer, session: SessionDep, container: ContainerDep
) -> SchemaOut:
    conn = await service.get(session, p.project_id, connection_id)
    return await schemas.ensure(container, session, conn)


@router.post(
    "/{connection_id}/schema/refresh",
    response_model=SchemaOut,
    summary="Discover the schema again now",
)
async def refresh_schema(
    connection_id: uuid.UUID, p: Editor, session: SessionDep, container: ContainerDep
) -> SchemaOut:
    conn = await service.get(session, p.project_id, connection_id)
    return await schemas.refresh(container, session, conn, p.actor)
