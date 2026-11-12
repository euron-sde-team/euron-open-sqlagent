"""Conversations: ask a question (new conversation or follow-up), list them, replay one
with its SQL and results."""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, literal, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from sqlagent.audit.service import audit
from sqlagent.chat import queue
from sqlagent.chat.models import Conversation, ConversationMessage
from sqlagent.chat.schemas import (
    AskRequest,
    ConversationDetail,
    ConversationOut,
    ConversationPage,
    MessageOut,
)
from sqlagent.connections import service as connections
from sqlagent.connections.models import Connection
from sqlagent.core.container import Container
from sqlagent.core.errors import AppError, NotFoundError, RateLimitedError
from sqlagent.core.schemas import decode_cursor, encode_cursor
from sqlagent.executions import service as executions
from sqlagent.executions.models import QueryExecution
from sqlagent.projects.access import Principal
from sqlagent.providers import service as providers


def title_of(question: str) -> str:
    q = " ".join(question.split())
    return q if len(q) <= 80 else q[:77].rstrip() + "..."


async def _limit(container: Container, p: Principal) -> None:
    try:
        decision = await container.kv.hit(
            f"questions:{p.project_id}", container.settings.question_rpm
        )
    except Exception:
        return  # a cache outage never blocks questions
    if not decision.allowed:
        raise RateLimitedError(
            f"This project asks more than {container.settings.question_rpm} questions a minute. "
            f"Try again in {decision.retry_after_s} s",
            headers={"retry-after": str(decision.retry_after_s)},
        )


async def ask(
    container: Container,
    session: AsyncSession,
    p: Principal,
    body: AskRequest,
    *,
    preset_sql: str | None = None,
    template_id: uuid.UUID | None = None,
) -> ConversationMessage:
    """Queue a question. A follow-up joins its conversation (and its connection)."""
    await _limit(container, p)
    if body.conversation_id is not None:
        conversation = await get_conversation(session, p.project_id, body.conversation_id)
        if body.connection_id is not None and body.connection_id != conversation.connection_id:
            raise AppError(
                "A follow-up stays on its conversation's connection; start a new conversation "
                "for another database",
                code="connection_mismatch",
            )
        conn = await connections.get(session, p.project_id, conversation.connection_id)
    else:
        if body.connection_id is None:
            raise AppError("Choose the database to ask about", code="connection_required")
        conn = await connections.get(session, p.project_id, body.connection_id)
        if body.provider_id is not None:
            await providers.get_provider(session, p.project_id, body.provider_id)
        elif preset_sql is None:
            await providers.default_provider(session, p.project_id)
        conversation = Conversation(
            id=uuid.uuid4(),
            project_id=p.project_id,
            connection_id=conn.id,
            title=title_of(body.question),
            provider_id=body.provider_id,
            created_by=p.user_id,
            created_by_label=p.actor.email or p.actor.role,
        )
        session.add(conversation)
        await session.flush()
    seq = int(
        await session.scalar(
            select(func.coalesce(func.max(ConversationMessage.seq), 0)).where(
                ConversationMessage.conversation_id == conversation.id
            )
        )
        or 0
    )
    msg = ConversationMessage(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        project_id=p.project_id,
        connection_id=conn.id,
        seq=seq + 1,
        question=body.question.strip(),
        preset_sql=preset_sql,
        template_id=template_id,
        actor_id=p.user_id,
        actor_label=p.actor.email or p.actor.role,
        actor_role=p.actor.role,
    )
    session.add(msg)
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation.id)
        .values(message_count=Conversation.message_count + 1, last_message_at=datetime.now(UTC))
    )
    audit(
        session,
        p.actor,
        "question.asked",
        "connection",
        conn.id,
        conversation_id=str(conversation.id),
        question=msg.question[:2000],
        project_id=p.project_id,
    )
    await session.commit()
    await queue.notify(container)
    return msg


async def get_conversation(
    session: AsyncSession, project_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    row = await session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.project_id == project_id
        )
    )
    if row is None:
        raise NotFoundError("Conversation not found")
    return row


async def get_message(
    session: AsyncSession, project_id: uuid.UUID, message_id: uuid.UUID
) -> ConversationMessage:
    row = await session.scalar(
        select(ConversationMessage).where(
            ConversationMessage.id == message_id, ConversationMessage.project_id == project_id
        )
    )
    if row is None:
        raise NotFoundError("Question not found")
    return row


async def message_out(
    container: Container,
    session: AsyncSession,
    msg: ConversationMessage,
    *,
    page_size: int = 50,
    with_page: bool = True,
) -> MessageOut:
    execution = None
    page = None
    if msg.execution_id is not None:
        ex = await session.get(QueryExecution, msg.execution_id)
        if ex is not None:
            execution = executions.to_out(ex)
            if with_page and ex.status == "succeeded":
                page = await executions.page(container, ex, 0, page_size)
    return MessageOut(
        id=msg.id,
        conversation_id=msg.conversation_id,
        connection_id=msg.connection_id,
        seq=msg.seq,
        question=msg.question,
        status=msg.status,
        sql=msg.sql,
        explanation=msg.explanation,
        error=msg.error,
        error_code=msg.error_code,
        validated=bool(execution and execution.status != "refused"),
        provider_name=msg.provider_name,
        model=msg.model,
        input_tokens=msg.input_tokens,
        output_tokens=msg.output_tokens,
        model_ms=msg.model_ms,
        total_ms=msg.total_ms,
        template_id=msg.template_id,
        actor_label=msg.actor_label,
        created_at=msg.created_at,
        finished_at=msg.finished_at,
        execution=execution,
        page=page,
    )


async def list_conversations(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    connection_id: uuid.UUID | None,
    q: str | None,
    cursor: str | None,
    limit: int,
) -> ConversationPage:
    """Most recent first, keyset-paginated on (last_message_at, id); the latest question's
    status comes from one lateral lookup per page, not one query per row."""
    last_status = (
        select(ConversationMessage.status)
        .where(ConversationMessage.conversation_id == Conversation.id)
        .order_by(ConversationMessage.seq.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    stmt = (
        select(Conversation, Connection.name, last_status)
        .join(Connection, Connection.id == Conversation.connection_id)
        .where(Conversation.project_id == project_id)
    )
    if connection_id:
        stmt = stmt.where(Conversation.connection_id == connection_id)
    if q:
        stmt = stmt.where(Conversation.title.ilike(f"%{q.replace('%', '')}%"))
    after = decode_cursor(cursor)
    if after:
        at, _, last_id = after.partition("|")
        with contextlib.suppress(ValueError):  # a malformed cursor starts from the top
            stmt = stmt.where(
                tuple_(Conversation.last_message_at, Conversation.id)
                < tuple_(literal(datetime.fromisoformat(at)), literal(uuid.UUID(last_id)))
            )
    rows = (
        await session.execute(
            stmt.order_by(Conversation.last_message_at.desc(), Conversation.id.desc()).limit(
                limit + 1
            )
        )
    ).all()
    items = [_conversation_out(c, name, status) for c, name, status in rows[:limit]]
    nxt = None
    if len(rows) > limit:
        last = rows[limit - 1][0]
        nxt = encode_cursor(f"{last.last_message_at.isoformat()}|{last.id}")
    return ConversationPage(items=items, next_cursor=nxt)


def _conversation_out(c: Conversation, connection_name: str, status: str | None) -> ConversationOut:
    return ConversationOut(
        id=c.id,
        connection_id=c.connection_id,
        connection_name=connection_name,
        title=c.title,
        message_count=c.message_count,
        last_message_at=c.last_message_at,
        created_by_label=c.created_by_label,
        created_at=c.created_at,
        last_status=status,
    )


async def detail(
    container: Container, session: AsyncSession, project_id: uuid.UUID, conversation_id: uuid.UUID
) -> ConversationDetail:
    c = await get_conversation(session, project_id, conversation_id)
    conn = await session.get(Connection, c.connection_id)
    messages = (
        await session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == c.id)
            .order_by(ConversationMessage.seq)
        )
    ).all()
    out = [await message_out(container, session, m, page_size=20) for m in messages]
    base = _conversation_out(c, conn.name if conn else "", out[-1].status if out else None)
    return ConversationDetail(**base.model_dump(), messages=out)


async def rename(session: AsyncSession, p: Principal, c: Conversation, title: str) -> Conversation:
    c.title = title.strip()
    await session.commit()
    await session.refresh(c)
    return c


async def delete(session: AsyncSession, p: Principal, c: Conversation) -> None:
    audit(
        session,
        p.actor,
        "conversation.deleted",
        "conversation",
        c.id,
        title=c.title,
        project_id=p.project_id,
    )
    await session.delete(c)
    await session.commit()
