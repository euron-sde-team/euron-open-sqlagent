"""The project's landing page in one request: what is connected, what was asked lately,
what the guard refused, and what is used most."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from sqlagent.chat import service as chat
from sqlagent.chat.models import Conversation
from sqlagent.chat.schemas import ConversationOut
from sqlagent.connections import service as connections
from sqlagent.connections.schemas import ConnectionOut
from sqlagent.core.deps import SessionDep
from sqlagent.core.schemas import ApiModel
from sqlagent.executions.models import QueryExecution
from sqlagent.projects.access import Viewer
from sqlagent.templates import service as templates
from sqlagent.templates.schemas import TemplateOut
from sqlagent.usage import service as usage
from sqlagent.usage.schemas import UsageByDay

router = APIRouter(prefix="/api/v1/projects/{project_id}/overview", tags=["overview"])


class Overview(ApiModel):
    connections: list[ConnectionOut]
    conversations: int
    questions_7d: int
    answered_7d: int
    refused_7d: int
    executions_7d: int
    rows_returned_7d: int
    median_query_ms: float | None
    recent: list[ConversationOut]
    templates: list[TemplateOut]
    by_day: list[UsageByDay]


@router.get("", response_model=Overview, summary="The project at a glance")
async def overview(p: Viewer, session: SessionDep) -> Overview:
    report = await usage.report(session, p.project_id, 14)
    week = [d for d in report.by_day if d.day >= (datetime.now(UTC).date() - timedelta(days=6))]
    since = datetime.now(UTC) - timedelta(days=7)
    median = await session.scalar(
        select(func.percentile_cont(0.5).within_group(QueryExecution.duration_ms)).where(
            QueryExecution.project_id == p.project_id,
            QueryExecution.status == "succeeded",
            QueryExecution.created_at >= since,
        )
    )
    total = await session.scalar(
        select(func.count())
        .select_from(Conversation)
        .where(Conversation.project_id == p.project_id)
    )
    recent = await chat.list_conversations(
        session, p.project_id, connection_id=None, q=None, cursor=None, limit=6
    )
    return Overview(
        connections=await connections.list_connections(session, p.project_id),
        conversations=int(total or 0),
        questions_7d=sum(d.questions for d in week),
        answered_7d=sum(d.answered for d in week),
        refused_7d=sum(d.refused for d in week),
        executions_7d=sum(d.executions for d in week),
        rows_returned_7d=sum(d.rows_returned for d in week),
        median_query_ms=round(float(median), 1) if median is not None else None,
        recent=recent.items,
        templates=(await templates.list_templates(session, p.project_id, None))[:6],
        by_day=report.by_day,
    )
