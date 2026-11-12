from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from sqlagent.chat import queue
from sqlagent.chat import service as chat
from sqlagent.chat.schemas import MessageOut
from sqlagent.core.deps import ContainerDep, SessionDep
from sqlagent.projects.access import Querier, Viewer
from sqlagent.templates import service
from sqlagent.templates.schemas import (
    TemplateCreate,
    TemplateFromMessage,
    TemplateOut,
    TemplateRun,
    TemplateUpdate,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/templates", tags=["templates"])


@router.get("", response_model=list[TemplateOut], summary="Saved questions, most used first")
async def list_templates(
    p: Viewer, session: SessionDep, connection_id: uuid.UUID | None = None
) -> list[TemplateOut]:
    return await service.list_templates(session, p.project_id, connection_id)


@router.post("", response_model=TemplateOut, status_code=201, summary="Save a question")
async def create(body: TemplateCreate, p: Querier, session: SessionDep) -> TemplateOut:
    return await service.create(session, p, body)


@router.post(
    "/from-message",
    response_model=TemplateOut,
    status_code=201,
    summary="Save an asked question (and its answered SQL) as a template",
)
async def from_message(body: TemplateFromMessage, p: Querier, session: SessionDep) -> TemplateOut:
    return await service.from_message(session, p, body)


@router.patch("/{template_id}", response_model=TemplateOut, summary="Change a template")
async def update(
    template_id: uuid.UUID, body: TemplateUpdate, p: Querier, session: SessionDep
) -> TemplateOut:
    t = await service.get(session, p.project_id, template_id)
    return await service.update_template(session, p, t, body)


@router.delete("/{template_id}", status_code=204, summary="Delete a template")
async def delete(template_id: uuid.UUID, p: Querier, session: SessionDep) -> Response:
    t = await service.get(session, p.project_id, template_id)
    await service.delete(session, p, t)
    return Response(status_code=204)


@router.post(
    "/{template_id}/run",
    response_model=MessageOut,
    status_code=201,
    summary="Ask a template's question again (its saved SQL runs as is)",
)
async def run(
    template_id: uuid.UUID,
    body: TemplateRun,
    p: Querier,
    session: SessionDep,
    container: ContainerDep,
) -> MessageOut:
    t = await service.get(session, p.project_id, template_id)
    msg = await service.run(container, session, p, t)
    if body.wait > 0:
        await queue.wait_for(container, msg.id, body.wait)
        await session.refresh(msg)
    return await chat.message_out(container, session, msg)
