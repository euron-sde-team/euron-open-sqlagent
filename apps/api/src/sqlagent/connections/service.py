"""Connections to the databases people ask questions about: stored with a sealed password,
tested, and opened read-only for every query.

Every query against a connected database runs in a worker thread through
``sources.open_sql`` (read-only session, statement timeout). The host is checked twice: as
typed (no metadata address) and as it resolves at connect time, so a DNS name pointing at
instance metadata is refused.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.engine import Connection as SaConnection
from sqlalchemy.ext.asyncio import AsyncSession

from sqlagent.audit.service import audit
from sqlagent.connections.models import Connection
from sqlagent.connections.schemas import (
    ConnectionOut,
    ConnectionUpdate,
    Limits,
    ServerConnection,
    TestResult,
)
from sqlagent.connections.sources import (
    DEFAULT_PORTS,
    SqlTarget,
    discover,
    open_sql,
    server_version,
)
from sqlagent.core.container import Container
from sqlagent.core.errors import AppError, ConflictError, NotFoundError
from sqlagent.core.net import resolves_safely
from sqlagent.projects.access import Principal

SQLITE_MAGIC = b"SQLite format 3\x00"
_SERVER_FIELDS = ("host", "port", "database", "username", "ssl_mode", "default_schema")


def secret_context(conn: Connection) -> str:
    return f"connection:{conn.id}:password"


def error_text(exc: BaseException) -> str:
    """The database's own message, first line, without bound parameters."""
    orig = getattr(exc, "orig", None)
    text = str(orig) if isinstance(exc, sa.exc.DBAPIError) and orig is not None else str(exc)
    return (text.strip().splitlines() or [type(exc).__name__])[0][:500]


def to_out(
    c: Connection,
    *,
    tables: int | None = None,
    schema_refreshed_at: datetime | None = None,
    conversations: int = 0,
) -> ConnectionOut:
    cfg = c.config or {}
    return ConnectionOut(
        id=c.id,
        name=c.name,
        kind=c.kind,
        description=c.description,
        host=cfg.get("host"),
        port=cfg.get("port"),
        database=cfg.get("database"),
        username=cfg.get("username"),
        ssl_mode=cfg.get("ssl_mode"),
        default_schema=cfg.get("default_schema"),
        has_password=c.secret_sealed is not None,
        file_name=c.file_name,
        file_size=c.file_size,
        max_rows=c.max_rows,
        max_scan_rows=c.max_scan_rows,
        timeout_s=c.timeout_s,
        sample_values=c.sample_values,
        last_tested_at=c.last_tested_at,
        last_test_ok=c.last_test_ok,
        last_test_message=c.last_test_message,
        server_version=c.server_version,
        tables=tables,
        schema_refreshed_at=schema_refreshed_at,
        conversations=conversations,
        created_at=c.created_at,
    )


async def get(session: AsyncSession, project_id: uuid.UUID, connection_id: uuid.UUID) -> Connection:
    """The project's connection; another project's (or none) is a 404, never a 403."""
    conn = await session.scalar(
        select(Connection).where(
            Connection.id == connection_id, Connection.project_id == project_id
        )
    )
    if conn is None:
        raise NotFoundError("Connection not found")
    return conn


async def out(session: AsyncSession, conn: Connection) -> ConnectionOut:
    return (await outs(session, [conn]))[0]


async def outs(session: AsyncSession, rows: list[Connection]) -> list[ConnectionOut]:
    """Connections with their schema and conversation counts, in two grouped queries."""
    from sqlagent.chat.models import Conversation
    from sqlagent.schema.models import SchemaCache

    ids = [c.id for c in rows]
    if not ids:
        return []
    schemas = {
        r[0]: (r[1], r[2])
        for r in (
            await session.execute(
                select(
                    SchemaCache.connection_id, SchemaCache.table_count, SchemaCache.refreshed_at
                ).where(SchemaCache.connection_id.in_(ids))
            )
        ).all()
    }
    convs: dict[uuid.UUID, int] = {
        r[0]: int(r[1])
        for r in (
            await session.execute(
                select(Conversation.connection_id, func.count())
                .where(Conversation.connection_id.in_(ids))
                .group_by(Conversation.connection_id)
            )
        ).all()
    }
    return [
        to_out(
            c,
            tables=schemas.get(c.id, (None, None))[0],
            schema_refreshed_at=schemas.get(c.id, (None, None))[1],
            conversations=convs.get(c.id, 0),
        )
        for c in rows
    ]


async def list_connections(session: AsyncSession, project_id: uuid.UUID) -> list[ConnectionOut]:
    rows = list(
        (
            await session.scalars(
                select(Connection)
                .where(Connection.project_id == project_id)
                .order_by(Connection.name)
            )
        ).all()
    )
    return await outs(session, rows)


async def _unique_name(
    session: AsyncSession, project_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None
) -> None:
    stmt = select(Connection.id).where(Connection.project_id == project_id, Connection.name == name)
    if exclude:
        stmt = stmt.where(Connection.id != exclude)
    if await session.scalar(stmt):
        raise ConflictError("A connection with this name exists in the project", code="name_taken")


def _limits(container: Container, data: Limits) -> dict[str, int]:
    s = container.settings
    return {
        "max_rows": min(data.max_rows, s.max_rows_ceiling),
        "max_scan_rows": data.max_scan_rows,
        "timeout_s": min(data.timeout_s, s.max_timeout_ceiling_s),
    }


def _server_config(data: ServerConnection) -> dict[str, Any]:
    return {
        "host": data.host,
        "port": data.port or DEFAULT_PORTS[data.kind],
        "database": data.database,
        "username": data.username,
        "ssl_mode": data.ssl_mode,
        "default_schema": data.default_schema,
    }


async def create_server(
    container: Container, session: AsyncSession, p: Principal, data: ServerConnection
) -> Connection:
    await _unique_name(session, p.project_id, data.name)
    conn = Connection(
        id=uuid.uuid4(),
        project_id=p.project_id,
        name=data.name.strip(),
        kind=data.kind,
        config=_server_config(data),
        sample_values=data.sample_values,
        description=data.description,
        created_by=p.user_id,
        **_limits(container, data),
    )
    if data.password:
        conn.secret_sealed = await container.sealer.seal(data.password, secret_context(conn))
    session.add(conn)
    audit(
        session,
        p.actor,
        "connection.created",
        "connection",
        conn.id,
        name=conn.name,
        kind=conn.kind,
        **p.audit_scope(),
    )
    await session.commit()
    return conn


async def create_sqlite(
    container: Container,
    session: AsyncSession,
    p: Principal,
    name: str,
    upload: UploadFile,
    limits: Limits,
    *,
    sample_values: bool = False,
    description: str = "",
) -> Connection:
    """A SQLite database file, kept in object storage and opened read-only by queries."""
    await _unique_name(session, p.project_id, name)
    conn_id = uuid.uuid4()
    key = f"projects/{p.project_id}/connections/{conn_id}/{uuid.uuid4().hex}.sqlite"
    size = await store_upload(container, upload, key)
    conn = Connection(
        id=conn_id,
        project_id=p.project_id,
        name=name.strip(),
        kind="sqlite",
        config={},
        file_key=key,
        file_name=(upload.filename or "database.sqlite")[:300],
        file_size=size,
        sample_values=sample_values,
        description=description,
        created_by=p.user_id,
        **_limits(container, limits),
    )
    session.add(conn)
    audit(
        session,
        p.actor,
        "connection.created",
        "connection",
        conn.id,
        name=conn.name,
        kind="sqlite",
        **p.audit_scope(),
    )
    await session.commit()
    return conn


async def store_upload(container: Container, upload: UploadFile, key: str) -> int:
    """Stream an upload to a temp file, check its size and that it is SQLite, store it."""
    limit = container.settings.max_upload_bytes
    size = 0
    work = Path(container.settings.work_dir)
    await asyncio.to_thread(work.mkdir, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=work, delete=True) as tmp:
        head = b""
        while chunk := await upload.read(1024 * 1024):
            if not head:
                head = chunk[:64]
            size += len(chunk)
            if size > limit:
                raise AppError(f"The file is larger than {limit:,} bytes", code="file_too_large")
            tmp.write(chunk)
        tmp.flush()
        if size == 0:
            raise AppError("The file is empty", code="file_empty")
        if not head.startswith(SQLITE_MAGIC):
            raise AppError("This is not a SQLite database file", code="not_sqlite")
        await container.storage.put_file(key, Path(tmp.name), "application/vnd.sqlite3")
    return size


async def update(
    container: Container,
    session: AsyncSession,
    p: Principal,
    conn: Connection,
    data: ConnectionUpdate,
) -> Connection:
    changes = data.model_dump(exclude_unset=True)
    fields = sorted(changes)
    password = changes.pop("password", None)
    if changes.get("name"):
        await _unique_name(session, p.project_id, changes["name"], exclude=conn.id)
        conn.name = changes.pop("name").strip()
    s = container.settings
    if changes.get("max_rows"):
        conn.max_rows = min(changes["max_rows"], s.max_rows_ceiling)
    if changes.get("max_scan_rows"):
        conn.max_scan_rows = changes["max_scan_rows"]
    if changes.get("timeout_s"):
        conn.timeout_s = min(changes["timeout_s"], s.max_timeout_ceiling_s)
    if changes.get("sample_values") is not None:
        conn.sample_values = changes["sample_values"]
    if changes.get("description") is not None:
        conn.description = changes["description"]
    if conn.kind != "sqlite":
        cfg = dict(conn.config or {})
        for name in _SERVER_FIELDS:
            if name in changes and (changes[name] is not None or name == "default_schema"):
                cfg[name] = changes[name]
        conn.config = cfg
    if password is not None:
        conn.secret_sealed = (
            await container.sealer.seal(password, secret_context(conn)) if password else None
        )
    audit(
        session,
        p.actor,
        "connection.updated",
        "connection",
        conn.id,
        fields=fields,
        **p.audit_scope(),
    )
    await session.commit()
    await session.refresh(conn)
    return conn


async def delete(
    container: Container, session: AsyncSession, p: Principal, conn: Connection
) -> None:
    """Remove the connection with its schema, conversations and templates (the audit log
    keeps every query that ever ran against it)."""
    audit(
        session,
        p.actor,
        "connection.deleted",
        "connection",
        conn.id,
        name=conn.name,
        **p.audit_scope(),
    )
    file_key = conn.file_key
    await session.delete(conn)
    await session.commit()
    if file_key:
        await container.storage.delete(file_key)


async def _sqlite_copy(container: Container, key: str) -> Path:
    """A local read-only copy of a stored SQLite file. Keys are immutable (a new upload gets
    a new key), so the copy is downloaded once per process and reused."""
    cache = Path(container.settings.work_dir) / "sqlite"
    await asyncio.to_thread(cache.mkdir, parents=True, exist_ok=True)
    path = cache / (hashlib.sha256(key.encode()).hexdigest()[:32] + ".sqlite")
    if not await asyncio.to_thread(path.exists):
        partial = cache / f"{path.name}.{uuid.uuid4().hex}.part"
        await container.storage.get_file(key, partial)
        await asyncio.to_thread(os.replace, partial, path)
    return path


@asynccontextmanager
async def target(
    container: Container, conn: Connection, password: str | None = None
) -> AsyncIterator[SqlTarget]:
    """Everything needed to open the database: the sealed password opened, the SQLite file
    fetched, the host checked as it resolves."""
    cfg: dict[str, Any] = conn.config or {}
    if conn.kind == "sqlite":
        if not conn.file_key:
            raise AppError("This SQLite connection has no database file", code="sqlite_missing")
        path = await _sqlite_copy(container, conn.file_key)
        yield SqlTarget(kind="sqlite", sqlite_path=str(path))
        return
    host, port = str(cfg.get("host", "")), int(cfg.get("port") or DEFAULT_PORTS[conn.kind])
    if not await resolves_safely(
        f"tcp://{host}:{port}", allow_private=container.settings.source_allow_private
    ):
        raise AppError(
            "The host resolves to an address this deployment refuses (metadata, or private when "
            "SOURCE_ALLOW_PRIVATE=false)",
            code="host_refused",
        )
    if password is None and conn.secret_sealed:
        password = await container.sealer.open(conn.secret_sealed, secret_context(conn))
    yield SqlTarget(
        kind=conn.kind,
        host=host,
        port=port,
        database=str(cfg.get("database", "")),
        username=str(cfg.get("username", "")),
        password=password,
        ssl_mode=str(cfg.get("ssl_mode") or "prefer"),
    )


async def run_sync[T](
    container: Container,
    conn: Connection,
    fn: Callable[[SaConnection], T],
    *,
    timeout_s: int | None = None,
    password: str | None = None,
) -> T:
    """Open the connection read-only in a thread and run ``fn`` on it."""
    limit = timeout_s or conn.timeout_s

    def go(t: SqlTarget) -> T:
        with open_sql(t, limit) as c:
            return fn(c)

    async with target(container, conn, password) as t:
        # The database enforces ``limit``; this only stops waiting on a hung network.
        return await asyncio.wait_for(asyncio.to_thread(go, t), timeout=limit + 30)


def confirm_read_only(c: SaConnection) -> bool:
    """Ask the database whether this session is read-only."""
    kind = c.dialect.name
    if kind == "postgresql":
        return str(c.exec_driver_sql("SHOW transaction_read_only").scalar()) == "on"
    if kind == "mysql":
        return str(c.exec_driver_sql("SELECT @@session.transaction_read_only").scalar()) == "1"
    return str(c.exec_driver_sql("PRAGMA query_only").scalar()) == "1"


def _probe(c: SaConnection, schema: str | None) -> tuple[str, int, bool]:
    inspector = sa.inspect(c)
    if c.dialect.name == "sqlite":
        count = len(inspector.get_table_names()) + len(inspector.get_view_names())
    else:
        count = len(discover_names(c, schema))
    return server_version(c), count, confirm_read_only(c)


def discover_names(c: SaConnection, schema: str | None) -> list[str]:
    from sqlagent.connections.sources import _schemas

    inspector = sa.inspect(c)
    names: list[str] = []
    for s in _schemas(c, schema):
        names += inspector.get_table_names(schema=s) + inspector.get_view_names(schema=s)
    return names


async def test(
    container: Container, conn: Connection, *, password: str | None = None, timeout_s: int = 20
) -> TestResult:
    """Connect, read the server version, count the visible tables and confirm the session
    is read-only. The latency is the real round trip of all of it."""
    started = time.perf_counter()
    schema = (conn.config or {}).get("default_schema")
    try:
        version, tables, read_only = await run_sync(
            container,
            conn,
            lambda c: _probe(c, schema),
            timeout_s=timeout_s,
            password=password,
        )
    except TimeoutError:
        return TestResult(
            ok=False, message="The database did not answer in time", latency_ms=_ms(started)
        )
    except AppError as exc:
        return TestResult(ok=False, message=exc.message, latency_ms=_ms(started))
    except Exception as exc:  # drivers raise many unrelated types; the message is what matters
        return TestResult(ok=False, message=friendly(error_text(exc)), latency_ms=_ms(started))
    return TestResult(
        ok=True,
        message=f"Connected read-only. {tables} tables and views visible",
        server_version=version,
        tables=tables,
        latency_ms=_ms(started),
        read_only=read_only,
    )


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def friendly(message: str) -> str:
    """Driver errors, rewritten to say what to check."""
    m = message.lower()
    if "password authentication failed" in m or "access denied" in m:
        return "The username or password was refused. Check them, and that the user may log in"
    if ("does not exist" in m and "database" in m) or "unknown database" in m:
        return "The database name was not found on the server"
    if (
        "could not translate host" in m
        or "name or service not known" in m
        or "nodename nor servname" in m
        or "name resolution" in m
    ):
        return "The host name could not be resolved. Check the spelling, or use an IP address"
    if "connection refused" in m or "can't connect" in m or "unable to connect" in m:
        return (
            "Nothing answered on that host and port. Check the port, firewall and that "
            "the database is running"
        )
    if "timeout" in m or "timed out" in m:
        return "The connection timed out. Check that the database is reachable from this deployment"
    if "ssl" in m:
        return f"The SSL handshake failed ({message[:160]}). Try another SSL mode"
    return message


async def record_test(session: AsyncSession, conn: Connection, result: TestResult) -> None:
    conn.last_tested_at = datetime.now(UTC)
    conn.last_test_ok = result.ok
    conn.last_test_message = result.message
    if result.server_version:
        conn.server_version = result.server_version
    await session.commit()


def unsaved(project_id: uuid.UUID, data: ServerConnection) -> Connection:
    """A connection that is only tested, never stored."""
    return Connection(
        id=uuid.uuid4(),
        project_id=project_id,
        name=data.name,
        kind=data.kind,
        config=_server_config(data),
        timeout_s=min(data.timeout_s, 20),
    )


async def discover_schema(container: Container, conn: Connection) -> tuple[list[Any], float]:
    """Discover the connected database's tables (run in a thread, read-only). Returns the
    tables and how long discovery took in milliseconds."""
    started = time.perf_counter()
    schema = (conn.config or {}).get("default_schema")
    max_tables = container.settings.schema_max_tables
    tables = await run_sync(
        container,
        conn,
        lambda c: discover(c, schema, max_tables=max_tables, sample_values=conn.sample_values),
        timeout_s=max(conn.timeout_s, 60),
    )
    return tables, _ms(started)
