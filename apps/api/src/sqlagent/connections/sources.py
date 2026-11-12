"""Open a connected database read-only, discover its schema, estimate a query's scan and
run it under a row cap. Synchronous: the API and the worker call these in threads.

Read-only is enforced by the database itself wherever it can be (the second lock behind
the SQL guard):

* PostgreSQL: ``default_transaction_read_only=on`` for the session, so every statement
  runs in a read-only transaction and a write fails with "cannot execute ... in a
  read-only transaction".
* MySQL: ``SET SESSION TRANSACTION READ ONLY``; a write fails with error 1792.
* SQLite: the file is opened with ``mode=ro`` and ``PRAGMA query_only``.

Every statement also runs under a timeout the database enforces (``statement_timeout``,
``MAX_EXECUTION_TIME``, a SQLite progress handler), inside a transaction that is always
rolled back, on a connection that is closed after use (no pool): a question holds one
connection to the customer's database and gives it back.
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import math
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.engine.reflection import ObjectKind
from sqlalchemy.pool import NullPool

APP_NAME = "euron-sqlagent"
DEFAULT_PORTS = {"postgresql": 5432, "mysql": 3306}
SYSTEM_SCHEMAS = {
    "postgresql": {"pg_catalog", "information_schema", "pg_toast"},
    "mysql": {"mysql", "information_schema", "performance_schema", "sys"},
}
# Sampled distinct values are kept only for columns with at most this many.
SAMPLE_DISTINCT = 12
SAMPLE_MAX_TABLE_ROWS = 2_000_000
_TEXT_TYPES = ("char", "text", "string", "enum", "varchar", "citext")


@dataclass(frozen=True)
class SqlTarget:
    kind: str  # postgresql, mysql, sqlite
    host: str = ""
    port: int | None = None
    database: str = ""
    username: str = ""
    password: str | None = None
    ssl_mode: str = "prefer"
    sqlite_path: str | None = None


class QueryTimeoutError(Exception):
    """The database stopped the statement at the connection's timeout."""


class ScanLimitError(Exception):
    """The query would read more rows than the connection allows."""

    def __init__(self, estimated: int, limit: int) -> None:
        super().__init__(f"estimated {estimated} rows scanned, limit {limit}")
        self.estimated = estimated
        self.limit = limit


def _engine(t: SqlTarget, timeout_s: int) -> Engine:
    ms = max(int(timeout_s * 1000), 1)
    if t.kind == "postgresql":
        url = URL.create(
            "postgresql+psycopg",
            t.username or None,
            t.password,
            t.host,
            t.port or 5432,
            t.database or None,
        )
        args: dict[str, Any] = {
            "connect_timeout": 10,
            "options": f"-c default_transaction_read_only=on -c statement_timeout={ms}",
            "application_name": APP_NAME,
            "sslmode": t.ssl_mode or "prefer",
        }
        return sa.create_engine(url, poolclass=NullPool, connect_args=args, hide_parameters=True)
    if t.kind == "mysql":
        url = URL.create(
            "mysql+pymysql",
            t.username or None,
            t.password,
            t.host,
            t.port or 3306,
            t.database or None,
        )
        args = {"connect_timeout": 10, "read_timeout": timeout_s + 15, "charset": "utf8mb4"}
        if t.ssl_mode in ("require", "verify-full"):
            args["ssl"] = {"check_hostname": t.ssl_mode == "verify-full"}
        return sa.create_engine(url, poolclass=NullPool, connect_args=args, hide_parameters=True)
    if t.kind == "sqlite":
        if not t.sqlite_path:
            raise ValueError("a SQLite connection needs its database file")
        path = Path(t.sqlite_path).resolve().as_posix()
        return sa.create_engine(
            f"sqlite:///file:{path}?mode=ro&uri=true", poolclass=NullPool, hide_parameters=True
        )
    raise ValueError(f"unknown connection kind {t.kind!r}")


def _prepare(conn: Connection, t: SqlTarget, timeout_s: int) -> None:
    if t.kind == "mysql":
        conn.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")
        conn.exec_driver_sql(f"SET SESSION MAX_EXECUTION_TIME = {max(int(timeout_s * 1000), 1)}")
    elif t.kind == "sqlite":
        raw = conn.connection.dbapi_connection
        assert isinstance(raw, sqlite3.Connection)
        raw.execute("PRAGMA query_only = 1")
        deadline = time.monotonic() + timeout_s
        # Interrupt a statement that runs past the timeout (checked every 10k VM steps).
        raw.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)


@contextmanager
def open_sql(t: SqlTarget, timeout_s: int) -> Iterator[Connection]:
    """A read-only connection inside a transaction that is always rolled back."""
    engine = _engine(t, timeout_s)
    try:
        with engine.connect() as conn:
            _prepare(conn, t, timeout_s)
            try:
                yield conn
            finally:
                conn.rollback()
    finally:
        engine.dispose()


def server_version(conn: Connection) -> str:
    sql = {
        "postgresql": "SELECT version()",
        "mysql": "SELECT VERSION()",
        "sqlite": "SELECT 'SQLite ' || sqlite_version()",
    }[conn.dialect.name]
    value = conn.exec_driver_sql(sql).scalar()
    return str(value or "").splitlines()[0][:200]


# ─── Schema discovery ────────────────────────────────────────────────────────


@dataclass
class ColumnInfo:
    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False
    sample_values: list[str] = field(default_factory=list)


@dataclass
class ForeignKeyInfo:
    columns: list[str]
    ref_table: str  # schema qualified when the database has schemas
    ref_columns: list[str]


@dataclass
class IndexInfo:
    name: str
    columns: list[str]
    unique: bool


@dataclass
class TableInfo:
    schema: str | None
    name: str
    kind: str  # table or view
    columns: list[ColumnInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    row_count: int | None = None

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.name}" if self.schema else self.name


def _schemas(conn: Connection, schema: str | None) -> list[str | None]:
    kind = conn.dialect.name
    if kind == "sqlite":
        return [None]
    if schema:
        return [schema]
    if kind == "mysql":
        current = conn.exec_driver_sql("SELECT DATABASE()").scalar()
        return [str(current)] if current else []
    inspector = sa.inspect(conn)
    hidden = SYSTEM_SCHEMAS.get(kind, set())
    return [s for s in inspector.get_schema_names() if s not in hidden and not s.startswith("pg_")]


def _row_counts(
    conn: Connection, kind: str, schema: str | None, names: list[str]
) -> dict[str, int]:
    """Cheap row counts: catalog estimates on servers, exact counts on small SQLite files."""
    out: dict[str, int] = {}
    if kind == "postgresql":
        rows = conn.execute(
            sa.text(
                "SELECT c.relname, c.reltuples::bigint FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relkind IN ('r', 'p', 'm')"
            ),
            {"schema": schema},
        ).all()
        out = {str(r[0]): max(int(r[1]), 0) for r in rows}
        # A table never analyzed reports -1 (shown as 0 above): count it if it is small.
        for name in names:
            if out.get(name, 0) == 0:
                quoted = conn.dialect.identifier_preparer.quote
                n = conn.exec_driver_sql(
                    f"SELECT count(*) FROM (SELECT 1 FROM {quoted(schema or '')}.{quoted(name)} "
                    "LIMIT 100001) s"
                ).scalar()
                out[name] = int(n or 0)
    elif kind == "mysql":
        rows = conn.execute(
            sa.text(
                "SELECT table_name, table_rows FROM information_schema.tables "
                "WHERE table_schema = :schema"
            ),
            {"schema": schema},
        ).all()
        out = {str(r[0]): int(r[1] or 0) for r in rows}
    else:
        quote = conn.dialect.identifier_preparer.quote
        for name in names[:500]:
            n = conn.exec_driver_sql(f"SELECT count(*) FROM {quote(name)}").scalar()
            out[name] = int(n or 0)
    return out


def _is_text(type_name: str) -> bool:
    lower = type_name.lower()
    return any(t in lower for t in _TEXT_TYPES)


def _sample(conn: Connection, table: TableInfo, column: ColumnInfo) -> list[str]:
    quote = conn.dialect.identifier_preparer.quote
    target = f"{quote(table.schema)}.{quote(table.name)}" if table.schema else quote(table.name)
    col = quote(column.name)
    rows = conn.exec_driver_sql(
        f"SELECT {col} FROM {target} WHERE {col} IS NOT NULL GROUP BY {col} "
        f"ORDER BY count(*) DESC LIMIT {SAMPLE_DISTINCT + 1}"
    ).all()
    if len(rows) > SAMPLE_DISTINCT:
        return []
    return [str(r[0])[:60] for r in rows]


def discover(
    conn: Connection,
    schema: str | None = None,
    *,
    max_tables: int = 2000,
    sample_values: bool = False,
) -> list[TableInfo]:
    """Tables and views the login can read outside system schemas, with columns, types,
    primary and foreign keys, indexes and row counts. With ``sample_values``, low
    cardinality text columns also get their distinct values (so "only shipped orders"
    can be answered with the real spelling)."""
    kind = conn.dialect.name
    inspector = sa.inspect(conn)
    out: list[TableInfo] = []
    for s in _schemas(conn, schema):
        table_names = inspector.get_table_names(schema=s)
        view_names = inspector.get_view_names(schema=s)
        names = [*table_names, *view_names][: max(max_tables - len(out), 0)]
        if not names:
            continue
        anything = ObjectKind.ANY
        columns = inspector.get_multi_columns(schema=s, filter_names=names, kind=anything)
        pks = inspector.get_multi_pk_constraint(schema=s, filter_names=names, kind=anything)
        fks = inspector.get_multi_foreign_keys(schema=s, filter_names=names, kind=anything)
        indexes = inspector.get_multi_indexes(schema=s, filter_names=names, kind=anything)
        counts = _row_counts(conn, kind, s, [n for n in names if n in table_names])
        # MySQL's "schema" is the connection's own database: names stay unqualified.
        shown_schema = s if kind == "postgresql" else None
        for name in names:
            key = (s, name)
            pk = pks.get(key)
            pk_cols = set(pk["constrained_columns"] or []) if pk else set()
            info = TableInfo(
                schema=shown_schema,
                name=name,
                kind="view" if name in view_names else "table",
                row_count=counts.get(name),
            )
            for c in columns.get(key, []):
                info.columns.append(
                    ColumnInfo(
                        name=str(c["name"]),
                        type=str(c["type"]).lower()[:60],
                        nullable=bool(c.get("nullable", True)),
                        primary_key=str(c["name"]) in pk_cols,
                    )
                )
            for fk in fks.get(key, []):
                ref_schema = fk.get("referred_schema") or s
                ref = fk["referred_table"]
                info.foreign_keys.append(
                    ForeignKeyInfo(
                        columns=list(fk["constrained_columns"]),
                        ref_table=f"{ref_schema}.{ref}" if kind == "postgresql" else str(ref),
                        ref_columns=list(fk["referred_columns"]),
                    )
                )
            for ix in indexes.get(key, []):
                cols = [str(c) for c in ix.get("column_names") or [] if c]
                if cols:
                    info.indexes.append(
                        IndexInfo(
                            name=str(ix.get("name") or ""),
                            columns=cols,
                            unique=bool(ix.get("unique")),
                        )
                    )
            if (
                sample_values
                and info.kind == "table"
                and (info.row_count or 0) <= SAMPLE_MAX_TABLE_ROWS
            ):
                for col in info.columns:
                    if _is_text(col.type) and not col.primary_key:
                        col.sample_values = _sample(conn, info, col)
            out.append(info)
        if len(out) >= max_tables:
            break
    return sorted(out, key=lambda t: ((t.schema or ""), t.name))


# ─── Scan estimates ──────────────────────────────────────────────────────────


def _pg_plan_rows(conn: Connection, node: dict[str, Any]) -> int:
    rows = 0
    node_type = str(node.get("Node Type", ""))
    if "Scan" in node_type and node.get("Relation Name"):
        planned = int(node.get("Plan Rows") or 0)
        if node_type == "Seq Scan":
            # A sequential scan reads the whole relation, not only the rows it keeps.
            total = conn.execute(
                sa.text(
                    "SELECT reltuples::bigint FROM pg_class c JOIN pg_namespace n "
                    "ON n.oid = c.relnamespace WHERE c.relname = :rel AND n.nspname = :schema"
                ),
                {"rel": node["Relation Name"], "schema": node.get("Schema", "public")},
            ).scalar()
            planned = max(planned, int(total or 0))
        rows += planned
    for child in node.get("Plans", []) or []:
        rows += _pg_plan_rows(conn, child)
    return rows


def estimate_scan(
    conn: Connection, sql: str, tables: list[str], aliases: dict[str, str]
) -> int | None:
    """Rows the database expects to read for ``sql`` (its own planner's estimate), or None
    when the plan could not be read. ``sql`` has passed the guard: EXPLAIN without ANALYZE
    plans it and runs nothing."""
    kind = conn.dialect.name
    try:
        if kind == "postgresql":
            raw = raw_all(conn, f"EXPLAIN (FORMAT JSON) {sql}")[1][0][0]
            plan = raw if isinstance(raw, list) else json.loads(str(raw))
            return _pg_plan_rows(conn, plan[0]["Plan"])
        if kind == "mysql":
            names, rows = raw_all(conn, f"EXPLAIN {sql}")
            idx = names.index("rows") if "rows" in names else None
            return sum(int(r[idx] or 0) for r in rows) if idx is not None else None
        if kind == "sqlite":
            details = [str(r[-1]) for r in raw_all(conn, f"EXPLAIN QUERY PLAN {sql}")[1]]
            quote = conn.dialect.identifier_preparer.quote
            total = 0
            for d in details:
                words = d.split()
                if len(words) >= 2 and words[0] == "SCAN":
                    word = words[2] if words[1] == "TABLE" and len(words) > 2 else words[1]
                    name = aliases.get(word.lower(), word)
                    if name.lower() in {t.lower().split(".")[-1] for t in tables}:
                        n = conn.exec_driver_sql(f"SELECT max(rowid) FROM {quote(name)}").scalar()
                        total += int(n or 0)
            return total
    except Exception:  # an unplannable query fails again, with its real message, when run
        conn.rollback()
        return None
    return None


# ─── Execution ───────────────────────────────────────────────────────────────


@dataclass
class ResultColumn:
    name: str
    kind: str  # number, text, date, datetime, boolean, other


@dataclass
class QueryResult:
    columns: list[ResultColumn]
    rows: list[list[Any]]
    truncated: bool
    duration_ms: float


def to_json_value(v: Any) -> Any:
    if v is None or isinstance(v, bool | int | str):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else str(v)
    if isinstance(v, decimal.Decimal):
        f = float(v)
        return f if math.isfinite(f) and abs(f) < 1e15 else str(v)
    if isinstance(v, dt.datetime | dt.date | dt.time):
        return v.isoformat()
    if isinstance(v, dt.timedelta):
        return v.total_seconds()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, bytes | bytearray | memoryview):
        return f"<{len(bytes(v))} bytes>"
    if isinstance(v, list | tuple):
        return [to_json_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): to_json_value(x) for k, x in v.items()}
    return str(v)


def _kind_of(values: list[Any]) -> str:
    seen = [v for v in values if v is not None]
    if not seen:
        return "other"
    if all(isinstance(v, bool) for v in seen):
        return "boolean"
    if all(isinstance(v, int | float | decimal.Decimal) and not isinstance(v, bool) for v in seen):
        return "number"
    if all(isinstance(v, dt.datetime) for v in seen):
        return "datetime"
    if all(isinstance(v, dt.date) for v in seen):
        return "date"
    if all(isinstance(v, str) for v in seen):
        return "text"
    return "other"


def is_timeout(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "statement timeout",
            "canceling statement due to",
            "maximum statement execution time exceeded",
            "3024",
            "interrupted",
        )
    )


def _raw_cursor(conn: Connection, *, server_side: bool = False) -> Any:
    """A DBAPI cursor on the session. User SQL goes through it with no parameters, so the
    drivers never treat a ``%`` in the query (``DATE_FORMAT(d, '%Y')``) as a placeholder."""
    raw = conn.connection.dbapi_connection
    assert raw is not None
    if server_side and conn.dialect.name == "postgresql":
        return raw.cursor(name=f"sqa_{uuid.uuid4().hex[:12]}")
    return raw.cursor()


def run_query(conn: Connection, sql: str, max_rows: int) -> QueryResult:
    """Run ``sql`` (already guarded) and fetch at most ``max_rows`` rows without pulling a
    large result whole: PostgreSQL reads through a server-side cursor, MySQL caps the rows
    the server returns (``sql_select_limit``), SQLite steps lazily."""
    started = time.perf_counter()
    kind = conn.dialect.name
    try:
        if kind == "mysql":
            conn.exec_driver_sql(f"SET SESSION sql_select_limit = {int(max_rows) + 1}")
        cur = _raw_cursor(conn, server_side=True)
        try:
            cur.execute(sql)
            names = [str(d[0]) for d in cur.description or []]
            fetched = cur.fetchmany(max_rows + 1)
        finally:
            cur.close()
    except Exception as exc:
        if is_timeout(exc):
            raise QueryTimeoutError(str(exc)) from exc
        raise
    truncated = len(fetched) > max_rows
    raw_rows = [list(r) for r in fetched[:max_rows]]
    columns = [
        ResultColumn(name=n, kind=_kind_of([r[i] for r in raw_rows])) for i, n in enumerate(names)
    ]
    rows = [[to_json_value(v) for v in r] for r in raw_rows]
    return QueryResult(
        columns=columns,
        rows=rows,
        truncated=truncated,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )


def raw_all(conn: Connection, sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Every row of a short statement (EXPLAIN), through a raw cursor."""
    cur = _raw_cursor(conn)
    try:
        cur.execute(sql)
        names = [str(d[0]) for d in cur.description or []]
        return names, [tuple(r) for r in cur.fetchall()]
    finally:
        cur.close()
