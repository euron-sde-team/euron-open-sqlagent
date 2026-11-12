"""Periodic work for questions and schemas, run by the scheduler (and safe with several
replicas: every task claims its rows or is idempotent)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from sqlagent.chat import queue
from sqlagent.chat.models import Conversation
from sqlagent.connections.models import Connection
from sqlagent.core.container import Container
from sqlagent.core.errors import AppError
from sqlagent.core.tasks import periodic
from sqlagent.executions.models import QueryExecution
from sqlagent.observability import metrics
from sqlagent.schema import service as schemas

log = logging.getLogger("sqlagent.tasks")


@periodic("reap_leases")
async def reap_leases(container: Container) -> int:
    return await queue.reap(container, container.settings.max_attempts)


@periodic("queue_gauges")
async def queue_gauges(container: Container) -> int:
    async with container.db.sessionmaker() as session:
        depth = await queue.depth(session)
    for status, n in depth.items():
        metrics.QUEUE_DEPTH.labels(status).set(n)
    # One line per tick: CloudWatch turns `queued` into the backlog metric (observability).
    log.info("question queue", extra=depth)
    return 0


@periodic("refresh_schemas")
async def refresh_schemas(container: Container) -> int:
    """Rediscover schemas older than SCHEMA_REFRESH_HOURS, a few per tick."""
    age = timedelta(hours=container.settings.schema_refresh_hours)
    done = 0
    async with container.db.sessionmaker() as session:
        for connection_id in await schemas.stale(session, age, limit=5):
            conn = await session.get(Connection, connection_id)
            if conn is None:
                continue
            try:
                await schemas.refresh(container, session, conn)
                metrics.SCHEMA_REFRESHES.labels("ok").inc()
                done += 1
            except AppError as exc:
                metrics.SCHEMA_REFRESHES.labels("failed").inc()
                log.info(
                    "schema refresh failed",
                    extra={"connection": str(conn.id), "error": exc.message},
                )
    return done


@periodic("retention")
async def retention(container: Container) -> int:
    """Conversations, executions and result snapshots past RETENTION_DAYS. The audit log is
    append-only and never purged here."""
    cutoff = datetime.now(UTC) - timedelta(days=container.settings.retention_days)
    async with container.db.sessionmaker() as session:
        old = (
            await session.execute(
                select(QueryExecution.id, QueryExecution.result_key)
                .where(QueryExecution.created_at < cutoff)
                .limit(500)
            )
        ).all()
        for _, key in old:
            if key:
                try:
                    await container.storage.delete(key)
                except Exception:
                    log.warning("snapshot delete failed", exc_info=True)
        if old:
            await session.execute(
                delete(QueryExecution).where(QueryExecution.id.in_([r[0] for r in old]))
            )
        gone = await session.execute(
            delete(Conversation).where(Conversation.last_message_at < cutoff)
        )
        await session.commit()
    return len(old) + int(gone.rowcount or 0)  # type: ignore[attr-defined]
