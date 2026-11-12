"""Benchmarks (make bench): the SQL guard's overhead, the time from a question to its answer
excluding the model, and schema discovery of a large schema.

Runs against the demo PostgreSQL server (make up, or scripts/test-db.sh) in databases of its
own (shop_bench, wide_bench), with the deterministic mock provider, so the model's time is
near zero and what is measured is SQLAgent itself: prompt building, the guard, the read-only
connection, the planner estimate, the query, the snapshot and the records.
"""

from __future__ import annotations

import asyncio
import os
import statistics
import tempfile
import time
import uuid
from pathlib import Path

import sqlalchemy as sa

from sqlagent.audit.service import Actor
from sqlagent.connections.models import Connection
from sqlagent.connections.sources import SqlTarget, discover, open_sql
from sqlagent.core.config import Settings
from sqlagent.core.container import Container
from sqlagent.core.db import Base, import_all_models
from sqlagent.demo.databases import build_shop
from sqlagent.executions import service as executions
from sqlagent.providers.models import ModelProvider
from sqlagent.sql import guard
from sqlagent.sql import service as sql_service
from tests.integration.conftest import SOURCE_PASSWORD, SOURCE_PG, TEST_DB, _admin_url

QUERIES = [
    "SELECT status, count(*) FROM orders GROUP BY status",
    "SELECT c.country, sum(o.total_amount) AS revenue FROM orders o JOIN customers c "
    "ON c.id = o.customer_id WHERE o.order_date >= DATE '2025-01-01' GROUP BY c.country "
    "ORDER BY revenue DESC LIMIT 5",
    "WITH m AS (SELECT date_trunc('month', order_date) AS month, sum(total_amount) AS r "
    "FROM orders GROUP BY 1) SELECT month, r, r - lag(r) OVER (ORDER BY month) FROM m",
]
QUESTIONS = [
    "How many orders per status?",
    "Revenue by country this year",
    "Top 5 customers by total spend",
    "Monthly revenue last year",
    "Revenue by product category",
]


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, round(p / 100 * (len(s) - 1)))]


def bench_guard() -> None:
    n = 2000
    for sql in QUERIES:
        guard.check(sql, "postgresql")
    times: list[float] = []
    for i in range(n):
        sql = QUERIES[i % len(QUERIES)]
        t = time.perf_counter()
        guard.check(sql, "postgresql")
        times.append((time.perf_counter() - t) * 1e6)
    print(
        f"SQL guard: {n} checks, median {statistics.median(times):.0f} us, "
        f"p95 {pct(times, 95):.0f} us per query"
    )


def _create_db(name: str) -> None:
    engine = sa.create_engine(
        _admin_url("postgresql", "shop").replace("postgresql://", "postgresql+psycopg://"),
        isolation_level="AUTOCOMMIT",
    )
    with engine.connect() as c:
        if not c.exec_driver_sql(f"SELECT 1 FROM pg_database WHERE datname = '{name}'").scalar():
            c.exec_driver_sql(f"CREATE DATABASE {name}")
    engine.dispose()


def bench_schema(tables: int = 500, columns: int = 12) -> None:
    _create_db("wide_bench")
    url = _admin_url("postgresql", "wide_bench").replace("postgresql://", "postgresql+psycopg://")
    engine = sa.create_engine(url)
    with engine.begin() as c:
        c.exec_driver_sql("DROP SCHEMA IF EXISTS wide CASCADE")
        c.exec_driver_sql("CREATE SCHEMA wide")
        for i in range(tables):
            cols = ", ".join(f"c{j} {'integer' if j % 2 else 'text'}" for j in range(columns))
            ref = f", parent_id integer REFERENCES wide.t{i - 1}(id)" if i else ""
            c.exec_driver_sql(f"CREATE TABLE wide.t{i} (id integer PRIMARY KEY, {cols}{ref})")
        c.exec_driver_sql("ANALYZE")
    engine.dispose()
    target = SqlTarget(
        "postgresql",
        SOURCE_PG["host"],
        int(SOURCE_PG["port"]),
        "wide_bench",
        "shop_admin",
        SOURCE_PASSWORD,
        "disable",
    )
    runs = []
    for _ in range(3):
        t = time.perf_counter()
        with open_sql(target, 120) as c:
            found = discover(c, "wide", max_tables=5000)
        runs.append(time.perf_counter() - t)
    print(
        f"Schema discovery: {len(found)} tables, {sum(len(x.columns) for x in found)} columns, "
        f"{len(found) - 1} foreign keys in {min(runs):.2f} s (best of 3)"
    )


async def bench_questions(rounds: int = 40) -> None:
    _create_db("shop_bench")
    build_shop(
        _admin_url("postgresql", "shop_bench"),
        "Bench-Reader-Pass-1",
        reader="sqlagent_bench_reader",
    )
    work = Path(tempfile.mkdtemp())
    settings = Settings(
        environment="test",
        database_url=TEST_DB.rsplit("/", 1)[0] + "/sqlagent_bench",
        redis_url=os.environ.get("TEST_REDIS_URL", "redis://localhost:5479/13"),
        local_storage_dir=str(work / "objects"),
        work_dir=str(work / "work"),
    )
    admin = sa.create_engine(
        settings.database_url.replace("+asyncpg", "+psycopg").rsplit("/", 1)[0] + "/postgres",
        isolation_level="AUTOCOMMIT",
    )
    with admin.connect() as c:
        c.exec_driver_sql("DROP DATABASE IF EXISTS sqlagent_bench WITH (FORCE)")
        c.exec_driver_sql("CREATE DATABASE sqlagent_bench")
    admin.dispose()
    import_all_models()
    container = Container.build(settings)
    async with container.db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    project_id = uuid.uuid4()
    async with container.db.sessionmaker() as session:
        from sqlagent.orgs.models import Organization
        from sqlagent.projects.models import Project

        org = Organization(name="Bench", slug=f"bench-{project_id.hex[:6]}")
        session.add(org)
        await session.flush()
        session.add(Project(id=project_id, org_id=org.id, name="Bench", slug="bench"))
        await session.flush()
        conn_row = Connection(
            id=uuid.uuid4(),
            project_id=project_id,
            name="Shop",
            kind="postgresql",
            config={
                "host": SOURCE_PG["host"],
                "port": SOURCE_PG["port"],
                "database": "shop_bench",
                "username": "sqlagent_bench_reader",
                "ssl_mode": "disable",
            },
            max_rows=1000,
            max_scan_rows=10_000_000,
            timeout_s=30,
            sample_values=True,
        )
        from sqlagent.connections.service import secret_context

        conn_row.secret_sealed = await container.sealer.seal(
            "Bench-Reader-Pass-1", secret_context(conn_row)
        )
        provider = ModelProvider(
            project_id=project_id,
            name="mock",
            kind="mock",
            base_url="",
            model="sqlagent-mock",
            is_default=True,
        )
        session.add_all([conn_row, provider])
        await session.commit()
        actor = Actor(None, "bench", "api_key")
        totals: list[float] = []
        models: list[float] = []
        for i in range(rounds):
            q = QUESTIONS[i % len(QUESTIONS)]
            t = time.perf_counter()
            gen = await sql_service.generate(container, session, conn_row, q, provider)
            assert gen.valid and gen.sql, gen.explanation
            out = await executions.execute(
                container, session, conn_row, gen.sql, actor, source="sql"
            )
            assert out.execution.status == "succeeded"
            totals.append((time.perf_counter() - t) * 1000)
            models.append(gen.model_ms)
    await container.close()
    warm = totals[len(QUESTIONS) :]
    excl = [t - m for t, m in zip(totals[len(QUESTIONS) :], models[len(QUESTIONS) :], strict=True)]
    print(
        f"Question to answer (mock model, demo shop, {len(warm)} warm runs): median "
        f"{statistics.median(warm):.0f} ms, p95 {pct(warm, 95):.0f} ms; excluding model time "
        f"median {statistics.median(excl):.0f} ms"
    )


def main() -> None:
    bench_guard()
    asyncio.run(bench_questions())
    bench_schema()


if __name__ == "__main__":
    main()
