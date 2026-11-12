"""Asking questions and reading conversations."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response

from sqlagent.chat import queue, service
from sqlagent.chat.schemas import (
    AskRequest,
    ConversationDetail,
    ConversationOut,
    ConversationPage,
    ConversationUpdate,
    MessageOut,
)
from sqlagent.core.deps import ContainerDep, SessionDep
from sqlagent.projects.access import Querier, Viewer

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["chat"])


@router.post(
    "/chat",
    response_model=MessageOut,
    status_code=201,
    summary="Ask a question in plain English; waits up to `wait` seconds for the answer",
    description=(
        "Starts a conversation on `connection_id`, or continues `conversation_id` (a "
        "follow-up sees the earlier questions, their SQL and a summary of their results). "
        "The answer carries the generated SQL, whether the SQL guard accepted it, the "
        "result's first page and a chart suggestion. If it is not ready within `wait`, the "
        "question comes back `queued` or `running`: poll `GET /messages/{id}`."
    ),
)
async def ask(
    body: AskRequest, p: Querier, session: SessionDep, container: ContainerDep
) -> MessageOut:
    msg = await service.ask(container, session, p, body)
    if body.wait > 0:
        await queue.wait_for(container, msg.id, body.wait)
        await session.refresh(msg)
    return await service.message_out(container, session, msg, page_size=body.page_size)


@router.get(
    "/messages/{message_id}", response_model=MessageOut, summary="One question and its answer"
)
async def get_message(
    message_id: uuid.UUID,
    p: Viewer,
    session: SessionDep,
    container: ContainerDep,
    wait: float = Query(0, ge=0, le=60, description="Seconds to wait for a final state"),
    page_size: int = Query(50, ge=1, le=1000),
) -> MessageOut:
    msg = await service.get_message(session, p.project_id, message_id)
    if wait > 0:
        await queue.wait_for(container, msg.id, wait)
        await session.refresh(msg)
    return await service.message_out(container, session, msg, page_size=page_size)


@router.get(
    "/conversations", response_model=ConversationPage, summary="Conversations, most recent first"
)
async def list_conversations(
    p: Viewer,
    session: SessionDep,
    connection_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=200, description="Search the titles"),
    cursor: str | None = None,
    limit: int = Query(30, ge=1, le=100),
) -> ConversationPage:
    return await service.list_conversations(
        session, p.project_id, connection_id=connection_id, q=q, cursor=cursor, limit=limit
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
    summary="A conversation replayed: every question with its SQL and result",
)
async def get_conversation(
    conversation_id: uuid.UUID, p: Viewer, session: SessionDep, container: ContainerDep
) -> ConversationDetail:
    return await service.detail(container, session, p.project_id, conversation_id)


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut, summary="Rename")
async def rename(
    conversation_id: uuid.UUID,
    body: ConversationUpdate,
    p: Querier,
    session: SessionDep,
    container: ContainerDep,
) -> ConversationOut:
    c = await service.get_conversation(session, p.project_id, conversation_id)
    await service.rename(session, p, c, body.title)
    detail = await service.detail(container, session, p.project_id, c.id)
    return ConversationOut(**detail.model_dump(exclude={"messages"}))


@router.delete(
    "/conversations/{conversation_id}",
    status_code=204,
    summary="Delete a conversation (its queries stay in the audit log)",
)
async def delete(conversation_id: uuid.UUID, p: Querier, session: SessionDep) -> Response:
    c = await service.get_conversation(session, p.project_id, conversation_id)
    await service.delete(session, p, c)
    return Response(status_code=204)
