"""Safe execution: the only path by which SQL reaches a connected database.

Every query goes through the same steps, in order:

1. **The SQL guard** (``sql.guard.check``): one read-only SELECT or nothing. A refusal is
   recorded (execution row, audit entry, usage) and the database is never contacted.
2. **A read-only connection** (``connections.sources.open_sql``): the session is
   read-only in the database itself, with the connection's statement timeout.
3. **The scan limit**: the database's own planner estimates the rows the query reads
   (``EXPLAIN``, which runs nothing); above the connection's ``max_scan_rows`` the query
   is stopped before it starts.
4. **The row limit**: at most ``max_rows`` rows are fetched (the rest is never pulled);
   the result says whether it was cut.
5. **The record**: the result snapshot goes to object storage, the execution row and an
   append-only audit entry (SQL, status, row count, actor) are written in one transaction.
"""

from __future__ import annotations

import contextlib
import csv
import io
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import orjson
from sqlalchemy import literal, select, tuple_
from sqlalchemy.engine import Connection as SaConnection
from sqlalchemy.ext.asyncio import AsyncSession

from sqlagent.audit.service import Actor, audit
from sqlagent.charts.suggest import ChartSuggestion, ColumnIn, suggest
from sqlagent.connections import service as connections
from sqlagent.connections.models import Connection
from sqlagent.connections.sources import (
    QueryResult,
    QueryTimeoutError,
    ScanLimitError,
    estimate_scan,
    is_timeout,
    run_query,
)
from sqlagent.core.container import Container
from sqlagent.core.errors import AppError, NotFoundError
from sqlagent.core.schemas import decode_cursor, encode_cursor
from sqlagent.executions.models import QueryExecution
from sqlagent.executions.schemas import ExecutionOut, RowsPage
from sqlagent.observability import metrics
from sqlagent.sql import guard
from sqlagent.usage import service as usage

log = logging.getLogger("sqlagent.executions")
SNAPSHOT_CACHE_S = 300


@dataclass(frozen=True)
class Outcome:
    execution: QueryExecution
    rows: list[list[Any]]


def _snapshot_key(project_id: uuid.UUID, execution_id: uuid.UUID) -> str:
    return f"projects/{project_id}/results/{execution_id}.json"


def _run(
    c: SaConnection, verdict: guard.Verdict, max_rows: int, max_scan_rows: int
) -> tuple[QueryResult, int | None]:
    estimated = estimate_scan(c, verdict.sql, verdict.tables, verdict.aliases)
    if estimated is not None and estimated > max_scan_rows:
        raise ScanLimitError(estimated, max_scan_rows)
    return run_query(c, verdict.sql, max_rows), estimated


async def execute(
    container: Container,
    session: AsyncSession,
    conn: Connection,
    sql: str,
    actor: Actor,
    *,
    source: str,
    conversation_id: uuid.UUID | None = None,
    model: str = "",
) -> Outcome:
    """Guard, run and record ``sql`` against ``conn``. Never raises for a refused, failed,
    timed-out or too-large query: the outcome's status says what happened."""
    execution = QueryExecution(
        id=uuid.uuid4(),
        project_id=conn.project_id,
        connection_id=conn.id,
        conversation_id=conversation_id,
        source=source,
        sql=sql.strip(),
        actor_id=actor.id,
        actor_label=actor.email or actor.role,
        columns=[],
        row_count=0,
        truncated=False,
        duration_ms=0.0,
    )
    rows: list[list[Any]] = []
    try:
        with metrics.GUARD_SECONDS.time():
            verdict = guard.check(sql, conn.kind)
    except guard.UnsafeSqlError as exc:
        execution.status = "refused"
        execution.error = exc.message
        execution.error_code = exc.code
        metrics.GUARD_REFUSALS.labels(exc.code).inc()
        await _record(session, conn, execution, actor, model)
        return Outcome(execution, rows)
    execution.sql = verdict.sql
    try:
        result, estimated = await connections.run_sync(
            container,
            conn,
            lambda c: _run(c, verdict, conn.max_rows, conn.max_scan_rows),
        )
    except ScanLimitError as exc:
        execution.status = "scan_limit"
        execution.estimated_scan_rows = exc.estimated
        execution.error_code = "scan_limit"
        execution.error = (
            f"The database expects this query to read about {exc.estimated:,} rows, more than "
            f"this connection allows ({exc.limit:,}). Narrow it with a filter or a smaller "
            "time range, or raise the connection's scan limit"
        )
    except (QueryTimeoutError, TimeoutError) as exc:
        execution.status = "timeout"
        execution.error_code = "timeout"
        execution.error = (
            f"The database stopped the query after {conn.timeout_s} s, this connection's "
            "time limit. Narrow it, or raise the connection's timeout"
        )
        log.info("query timed out", extra={"connection": str(conn.id), "error": str(exc)[:200]})
    except AppError as exc:
        execution.status = "failed"
        execution.error = exc.message
        execution.error_code = exc.code
    except Exception as exc:  # drivers raise many unrelated types; the message is what matters
        if is_timeout(exc):
            execution.status = "timeout"
            execution.error_code = "timeout"
            execution.error = f"The database stopped the query after {conn.timeout_s} s"
        else:
            execution.status = "failed"
            execution.error_code = "database_error"
            execution.error = connections.friendly(connections.error_text(exc))
    else:
        rows = result.rows
        columns = [ColumnIn(name=c.name, kind=c.kind) for c in result.columns]
        chart = suggest(columns, rows)
        execution.status = "succeeded"
        execution.row_count = len(rows)
        execution.truncated = result.truncated
        execution.duration_ms = result.duration_ms
        execution.estimated_scan_rows = estimated
        execution.columns = [c.model_dump() for c in columns]
        execution.chart = chart.model_dump() if chart else None
        execution.result_key = _snapshot_key(conn.project_id, execution.id)
        await container.storage.put(
            execution.result_key,
            orjson.dumps({"columns": execution.columns, "rows": rows}),
            "application/json",
        )
    metrics.EXECUTIONS.labels(conn.kind, execution.status).inc()
    await _record(session, conn, execution, actor, model)
    return Outcome(execution, rows)


async def _record(
    session: AsyncSession, conn: Connection, ex: QueryExecution, actor: Actor, model: str
) -> None:
    session.add(ex)
    action = "query.refused" if ex.status == "refused" else "query.executed"
    audit(
        session,
        actor,
        action,
        "connection",
        conn.id,
        execution_id=str(ex.id),
        connection=conn.name,
        source=ex.source,
        sql=ex.sql[:20_000],
        status=ex.status,
        row_count=ex.row_count,
        duration_ms=ex.duration_ms,
        error=ex.error,
        project_id=conn.project_id,
    )
    await usage.record(
        session,
        conn.project_id,
        conn.id,
        model,
        executions=0 if ex.status == "refused" else 1,
        rows_returned=ex.row_count,
    )
    await session.commit()


def to_out(ex: QueryExecution) -> ExecutionOut:
    return ExecutionOut(
        id=ex.id,
        connection_id=ex.connection_id,
        conversation_id=ex.conversation_id,
        source=ex.source,
        sql=ex.sql,
        status=ex.status,
        error=ex.error,
        error_code=ex.error_code,
        row_count=ex.row_count,
        truncated=ex.truncated,
        duration_ms=ex.duration_ms,
        estimated_scan_rows=ex.estimated_scan_rows,
        columns=[ColumnIn.model_validate(c) for c in ex.columns or []],
        chart=ChartSuggestion.model_validate(ex.chart) if ex.chart else None,
        actor_id=ex.actor_id,
        actor_label=ex.actor_label,
        created_at=ex.created_at,
    )


async def get(
    session: AsyncSession, project_id: uuid.UUID, execution_id: uuid.UUID
) -> QueryExecution:
    ex = await session.scalar(
        select(QueryExecution).where(
            QueryExecution.id == execution_id, QueryExecution.project_id == project_id
        )
    )
    if ex is None:
        raise NotFoundError("Query not found")
    return ex


async def list_executions(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    connection_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    status: str | None,
    cursor: str | None,
    limit: int,
) -> tuple[list[QueryExecution], str | None]:
    """Newest first, keyset-paginated on (created_at, id)."""
    stmt = select(QueryExecution).where(QueryExecution.project_id == project_id)
    if connection_id:
        stmt = stmt.where(QueryExecution.connection_id == connection_id)
    if actor_id:
        stmt = stmt.where(QueryExecution.actor_id == actor_id)
    if status:
        stmt = stmt.where(QueryExecution.status == status)
    after = decode_cursor(cursor)
    if after:
        at, _, last_id = after.partition("|")
        with contextlib.suppress(ValueError):  # a malformed cursor starts from the top
            stmt = stmt.where(
                tuple_(QueryExecution.created_at, QueryExecution.id)
                < tuple_(literal(_parse_dt(at)), literal(uuid.UUID(last_id)))
            )
    rows = list(
        (
            await session.scalars(
                stmt.order_by(QueryExecution.created_at.desc(), QueryExecution.id.desc()).limit(
                    limit + 1
                )
            )
        ).all()
    )
    nxt = None
    if len(rows) > limit:
        last = rows[limit - 1]
        nxt = encode_cursor(f"{last.created_at.isoformat()}|{last.id}")
    return rows[:limit], nxt


def _parse_dt(value: str) -> Any:
    from datetime import datetime

    return datetime.fromisoformat(value)


async def snapshot(container: Container, ex: QueryExecution) -> list[list[Any]]:
    """The stored rows of a successful execution (cached briefly: pages read it often)."""
    if ex.result_key is None:
        return []
    cache_key = f"result:{ex.id}"
    try:
        cached = await container.kv.get(cache_key)
    except Exception:
        cached = None
    raw = cached if cached is not None else await container.storage.get(ex.result_key)
    if cached is None:
        try:
            await container.kv.set(cache_key, raw, SNAPSHOT_CACHE_S)
        except Exception:
            log.warning("result cache write failed", exc_info=True)
    rows: list[list[Any]] = orjson.loads(raw)["rows"]
    return rows


async def page(container: Container, ex: QueryExecution, offset: int, limit: int) -> RowsPage:
    rows = await snapshot(container, ex)
    return RowsPage(
        execution_id=ex.id,
        columns=[ColumnIn.model_validate(c) for c in ex.columns or []],
        rows=rows[offset : offset + limit],
        offset=offset,
        limit=limit,
        total=len(rows),
    )


def _cell(v: Any) -> Any:
    # Spreadsheet formula injection: a text cell starting with = + - @ is prefixed.
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    if isinstance(v, list | dict):
        return orjson.dumps(v).decode()
    return v


async def csv_stream(container: Container, ex: QueryExecution) -> AsyncIterator[bytes]:
    rows = await snapshot(container, ex)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([c.get("name", "") for c in ex.columns or []])
    yield buf.getvalue().encode()
    for start in range(0, len(rows), 1000):
        buf.seek(0)
        buf.truncate()
        for r in rows[start : start + 1000]:
            writer.writerow([_cell(v) for v in r])
        yield buf.getvalue().encode()
