"""Schema discovery and the schema cache.

The cache has two layers:

* ``schema_cache`` in Postgres: one row per connection, the discovered tables as JSONB,
  refreshed by the scheduler when older than ``SCHEMA_REFRESH_HOURS`` and on demand.
* The key-value cache (Redis, or process memory without it): the same document,
  serialized, under ``schema:<connection>:<refreshed_at>``. A refresh writes a row with a
  new ``refreshed_at``, so readers move to a new key at once and the old entry ages out;
  nothing has to be deleted for a refresh to be seen everywhere.

Every question reads the schema, so the hot path is one indexed lookup of
``refreshed_at`` plus a cache hit, never the JSONB document.
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from datetime import UTC, datetime, timedelta

import orjson
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sqlagent.audit.service import Actor, audit
from sqlagent.connections import service as connections
from sqlagent.connections.models import Connection
from sqlagent.core.container import Container
from sqlagent.core.errors import AppError
from sqlagent.observability import metrics
from sqlagent.schema.models import SchemaCache
from sqlagent.schema.schemas import SchemaOut, SchemaTable

log = logging.getLogger("sqlagent.schema")
CACHE_TTL_S = 3600


def _key(connection_id: uuid.UUID, refreshed_at: datetime) -> str:
    return f"schema:{connection_id}:{refreshed_at.timestamp():.6f}"


def _out(conn: Connection, row: SchemaCache, tables: list[SchemaTable]) -> SchemaOut:
    return SchemaOut(
        connection_id=conn.id,
        dialect=conn.kind,
        tables=tables,
        table_count=row.table_count,
        column_count=row.column_count,
        refreshed_at=row.refreshed_at,
        duration_ms=row.duration_ms,
        last_error=row.last_error,
    )


async def refresh(
    container: Container,
    session: AsyncSession,
    conn: Connection,
    actor: Actor | None = None,
) -> SchemaOut:
    """Discover the schema from the database now and store it. A failure keeps the previous
    schema (if any) and records the error on it."""
    connection_id = conn.id
    try:
        found, duration = await connections.discover_schema(container, conn)
    except AppError as exc:
        await _record_error(session, connection_id, exc.message)
        raise
    except Exception as exc:  # drivers raise many unrelated types
        message = connections.friendly(connections.error_text(exc))
        await _record_error(session, connection_id, message)
        raise AppError(message, code="schema_discovery_failed") from exc
    tables = [SchemaTable.model_validate(_table_dict(t)) for t in found]
    now = datetime.now(UTC)
    values = {
        "connection_id": conn.id,
        "project_id": conn.project_id,
        "tables": [t.model_dump() for t in tables],
        "table_count": len(tables),
        "column_count": sum(len(t.columns) for t in tables),
        "duration_ms": duration,
        "refreshed_at": now,
        "last_error": None,
    }
    stmt = insert(SchemaCache).values(**values)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[SchemaCache.connection_id],
            set_={k: stmt.excluded[k] for k in values if k != "connection_id"},
        )
    )
    if actor is not None:
        audit(
            session,
            actor,
            "schema.refreshed",
            "connection",
            conn.id,
            tables=len(tables),
            duration_ms=duration,
            project_id=conn.project_id,
        )
    await session.commit()
    row = await session.get(SchemaCache, conn.id, populate_existing=True)
    assert row is not None
    await _cache_set(container, conn.id, row.refreshed_at, tables)
    return _out(conn, row, tables)


def _table_dict(t: object) -> dict[str, object]:
    d = dataclasses.asdict(t)  # type: ignore[call-overload]
    d["schema_name"] = d.pop("schema")
    return d  # type: ignore[no-any-return]


async def _record_error(session: AsyncSession, connection_id: uuid.UUID, message: str) -> None:
    row = await session.get(SchemaCache, connection_id)
    if row is not None:
        row.last_error = message[:500]
        await session.commit()


async def _cache_set(
    container: Container, connection_id: uuid.UUID, at: datetime, tables: list[SchemaTable]
) -> None:
    try:
        await container.kv.set(
            _key(connection_id, at),
            orjson.dumps([t.model_dump() for t in tables]),
            CACHE_TTL_S,
        )
    except Exception:  # a cache outage only costs a database read
        metrics.DEPENDENCY_ERRORS.labels("cache", "schema_write").inc()
        log.warning("schema cache write failed", exc_info=True)


async def load(container: Container, session: AsyncSession, conn: Connection) -> SchemaOut | None:
    """The cached schema, or None when it was never discovered."""
    row = (
        await session.execute(
            select(
                SchemaCache.refreshed_at,
                SchemaCache.table_count,
                SchemaCache.column_count,
                SchemaCache.duration_ms,
                SchemaCache.last_error,
            ).where(SchemaCache.connection_id == conn.id)
        )
    ).first()
    if row is None:
        return None
    refreshed_at = row[0]
    tables: list[SchemaTable] | None = None
    try:
        cached = await container.kv.get(_key(conn.id, refreshed_at))
    except Exception:
        metrics.DEPENDENCY_ERRORS.labels("cache", "schema_read").inc()
        cached = None
    if cached is not None:
        tables = [SchemaTable.model_validate(t) for t in orjson.loads(cached)]
    else:
        doc = await session.scalar(
            select(SchemaCache.tables).where(SchemaCache.connection_id == conn.id)
        )
        tables = [SchemaTable.model_validate(t) for t in doc or []]
        await _cache_set(container, conn.id, refreshed_at, tables)
    return SchemaOut(
        connection_id=conn.id,
        dialect=conn.kind,
        tables=tables,
        table_count=int(row[1]),
        column_count=int(row[2]),
        refreshed_at=refreshed_at,
        duration_ms=float(row[3]),
        last_error=row[4],
    )


async def ensure(container: Container, session: AsyncSession, conn: Connection) -> SchemaOut:
    """The cached schema, discovering it first if it never was."""
    return await load(container, session, conn) or await refresh(container, session, conn)


async def stale(session: AsyncSession, older_than: timedelta, limit: int = 20) -> list[uuid.UUID]:
    """Connections whose cached schema is older than ``older_than``."""
    cutoff = datetime.now(UTC) - older_than
    return list(
        (
            await session.scalars(
                select(SchemaCache.connection_id)
                .where(SchemaCache.refreshed_at < cutoff)
                .order_by(SchemaCache.refreshed_at)
                .limit(limit)
            )
        ).all()
    )
