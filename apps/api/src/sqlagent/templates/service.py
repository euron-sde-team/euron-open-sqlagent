"""Query templates: a saved question (and, optionally, its checked SQL) to ask again."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sqlagent.audit.service import audit
from sqlagent.chat import service as chat
from sqlagent.chat.models import ConversationMessage
from sqlagent.chat.schemas import AskRequest
from sqlagent.connections import service as connections
from sqlagent.connections.models import Connection
from sqlagent.core.container import Container
from sqlagent.core.errors import AppError, ConflictError, NotFoundError
from sqlagent.projects.access import Principal
from sqlagent.sql import guard
from sqlagent.templates.models import QueryTemplate
from sqlagent.templates.schemas import (
    TemplateCreate,
    TemplateFromMessage,
    TemplateOut,
    TemplateUpdate,
)


def to_out(t: QueryTemplate, connection_name: str) -> TemplateOut:
    return TemplateOut(
        id=t.id,
        connection_id=t.connection_id,
        connection_name=connection_name,
        name=t.name,
        question=t.question,
        sql=t.sql,
        description=t.description,
        use_count=t.use_count,
        created_at=t.created_at,
    )


async def list_templates(
    session: AsyncSession, project_id: uuid.UUID, connection_id: uuid.UUID | None
) -> list[TemplateOut]:
    stmt = (
        select(QueryTemplate, Connection.name)
        .join(Connection, Connection.id == QueryTemplate.connection_id)
        .where(QueryTemplate.project_id == project_id)
        .order_by(QueryTemplate.use_count.desc(), QueryTemplate.name)
    )
    if connection_id:
        stmt = stmt.where(QueryTemplate.connection_id == connection_id)
    return [to_out(t, name) for t, name in (await session.execute(stmt)).all()]


async def get(
    session: AsyncSession, project_id: uuid.UUID, template_id: uuid.UUID
) -> QueryTemplate:
    t = await session.scalar(
        select(QueryTemplate).where(
            QueryTemplate.id == template_id, QueryTemplate.project_id == project_id
        )
    )
    if t is None:
        raise NotFoundError("Template not found")
    return t


def _check_sql(sql: str | None, dialect: str) -> str | None:
    if not sql:
        return None
    try:
        return guard.check(sql, dialect).sql
    except guard.UnsafeSqlError as exc:
        raise AppError(
            f"A template's SQL must be read-only: {exc.message}", code="unsafe_sql"
        ) from exc


async def _unique(
    session: AsyncSession, project_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None
) -> None:
    stmt = select(QueryTemplate.id).where(
        QueryTemplate.project_id == project_id, QueryTemplate.name == name
    )
    if exclude:
        stmt = stmt.where(QueryTemplate.id != exclude)
    if await session.scalar(stmt):
        raise ConflictError("A template with this name exists", code="template_name_taken")


async def create(session: AsyncSession, p: Principal, data: TemplateCreate) -> TemplateOut:
    conn = await connections.get(session, p.project_id, data.connection_id)
    await _unique(session, p.project_id, data.name)
    t = QueryTemplate(
        id=uuid.uuid4(),
        project_id=p.project_id,
        connection_id=conn.id,
        name=data.name.strip(),
        question=data.question.strip(),
        sql=_check_sql(data.sql, conn.kind),
        description=data.description,
        created_by=p.user_id,
    )
    session.add(t)
    audit(session, p.actor, "template.created", "template", t.id, name=t.name, **p.audit_scope())
    await session.commit()
    await session.refresh(t)
    return to_out(t, conn.name)


async def from_message(
    session: AsyncSession, p: Principal, data: TemplateFromMessage
) -> TemplateOut:
    msg = await session.scalar(
        select(ConversationMessage).where(
            ConversationMessage.id == data.message_id,
            ConversationMessage.project_id == p.project_id,
        )
    )
    if msg is None:
        raise NotFoundError("Question not found")
    if data.keep_sql and msg.status != "answered":
        raise AppError("Only an answered question's SQL can be kept", code="not_answered")
    return await create(
        session,
        p,
        TemplateCreate(
            connection_id=msg.connection_id,
            name=data.name,
            question=msg.question,
            sql=msg.sql if data.keep_sql else None,
            description=data.description,
        ),
    )


async def update_template(
    session: AsyncSession, p: Principal, t: QueryTemplate, data: TemplateUpdate
) -> TemplateOut:
    conn = await connections.get(session, p.project_id, t.connection_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("name"):
        await _unique(session, p.project_id, changes["name"], exclude=t.id)
        t.name = changes["name"].strip()
    if changes.get("question"):
        t.question = changes["question"].strip()
    if "sql" in changes:
        t.sql = _check_sql(changes["sql"], conn.kind)
    if changes.get("description") is not None:
        t.description = changes["description"]
    audit(
        session,
        p.actor,
        "template.updated",
        "template",
        t.id,
        fields=sorted(changes),
        **p.audit_scope(),
    )
    await session.commit()
    await session.refresh(t)
    return to_out(t, conn.name)


async def delete(session: AsyncSession, p: Principal, t: QueryTemplate) -> None:
    audit(session, p.actor, "template.deleted", "template", t.id, name=t.name, **p.audit_scope())
    await session.delete(t)
    await session.commit()


async def run(
    container: Container, session: AsyncSession, p: Principal, t: QueryTemplate
) -> ConversationMessage:
    """Ask the template's question in a new conversation; with saved SQL the model is not
    asked and the SQL runs as is (through the guard again)."""
    await session.execute(
        update(QueryTemplate)
        .where(QueryTemplate.id == t.id)
        .values(use_count=QueryTemplate.use_count + 1)
    )
    return await chat.ask(
        container,
        session,
        p,
        AskRequest(question=t.question, connection_id=t.connection_id, wait=0),
        preset_sql=t.sql,
        template_id=t.id,
    )
