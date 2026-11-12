"""The question queue and the scheduler's tasks: leases, recovery after a worker dies,
concurrency, schema refresh, retention and rate limits."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from sqlagent.chat import queue, tasks
from sqlagent.core.container import Container
from tests.integration.conftest import Sources, Stack, WorkerThread

pytestmark = pytest.mark.integration


@pytest.fixture
def run_worker() -> bool:
    return False


async def _sql(stack: Stack, stmt: str, **params: Any) -> Any:
    engine = create_async_engine(stack.settings.database_url)
    try:
        async with engine.begin() as c:
            result = await c.execute(sa.text(stmt), params)
            return result.all() if result.returns_rows else None
    finally:
        await engine.dispose()


async def test_a_question_whose_worker_died_is_answered_by_another(
    ready: Stack, sources: Sources
) -> None:
    conn = await ready.connection(sources.pg())
    msg = await ready.ask("How many orders per status?", connection_id=conn["id"], wait=0)
    assert msg["status"] == "queued"
    container = Container.build(ready.settings)
    try:
        # A worker claims it and dies without finishing (its lease expires).
        async with container.db.sessionmaker() as session:
            claimed = await queue.claim(session, "dead-worker#1", lease_s=10)
        assert claimed is not None and claimed.id is not None
        await _sql(
            ready,
            "UPDATE conversation_messages SET lease_expires_at = now() - interval '1 second' "
            "WHERE id = :id",
            id=msg["id"],
        )
        assert await queue.reap(container, max_attempts=3) == 1
        await _sql(
            ready,
            "UPDATE conversation_messages SET available_at = now() WHERE id = :id",
            id=msg["id"],
        )
        # The dead worker's late write changes nothing.
        async with container.db.sessionmaker() as session:
            assert not await queue.finish(session, claimed.id, "dead-worker#1", status="answered")
            await session.rollback()
        worker = WorkerThread(ready.settings).start()
        ready.worker = worker
        done = await ready.ok("GET", ready.p(f"/messages/{msg['id']}"), params={"wait": 30})
        assert done["status"] == "answered"
        rows = await _sql(
            ready, "SELECT attempts FROM conversation_messages WHERE id = :id", id=msg["id"]
        )
        assert rows[0][0] == 2
        # After too many deaths a question fails instead of looping forever.
        stuck = await ready.ask("How many customers?", connection_id=conn["id"], wait=0)
        await asyncio.sleep(0)
        await _sql(
            ready,
            "UPDATE conversation_messages SET status = 'running', attempts = 3, "
            "lease_owner = 'gone', lease_expires_at = now() - interval '1 second' WHERE id = :id",
            id=stuck["id"],
        )
        assert await queue.reap(container, max_attempts=3) == 1
        failed = await ready.ok("GET", ready.p(f"/messages/{stuck['id']}"))
        assert failed["status"] == "failed" and failed["error_code"] == "worker_lost"
    finally:
        await container.close()


async def test_many_questions_at_once_are_each_answered_exactly_once(
    ready: Stack, sources: Sources
) -> None:
    conn = await ready.connection(sources.pg())
    questions = [
        "How many orders per status?",
        "How many customers per country?",
        "Revenue by product category",
        "How many orders per channel?",
        "Top 5 customers by total spend",
        "Monthly revenue last year",
    ] * 3
    asked = await asyncio.gather(
        *(ready.ask(q, connection_id=conn["id"], wait=0) for q in questions)
    )
    workers = [WorkerThread(ready.settings).start() for _ in range(2)]
    try:
        done = await asyncio.gather(
            *(ready.ok("GET", ready.p(f"/messages/{m['id']}"), params={"wait": 60}) for m in asked)
        )
        assert [d["status"] for d in done] == ["answered"] * len(questions)
        rows = await _sql(
            ready,
            "SELECT count(*), count(DISTINCT execution_id), max(attempts) FROM conversation_messages",
        )
        assert tuple(rows[0]) == (len(questions), len(questions), 1)
    finally:
        for w in workers:
            w.stop()


async def test_scheduler_refreshes_stale_schemas_and_purges_old_history(
    ready: Stack, sources: Sources
) -> None:
    conn = await ready.connection(sources.pg())
    worker = WorkerThread(ready.settings).start()
    ready.worker = worker
    msg = await ready.ask("How many orders per status?", connection_id=conn["id"])
    assert msg["status"] == "answered"
    container = Container.build(ready.settings)
    try:
        old = datetime.now(UTC) - timedelta(days=30)
        await _sql(ready, "UPDATE schema_cache SET refreshed_at = :t", t=old)
        assert await tasks.refresh_schemas(container) == 1
        rows = await _sql(ready, "SELECT refreshed_at FROM schema_cache")
        assert rows[0][0] > old + timedelta(days=29)
        assert await tasks.queue_gauges(container) == 0
        # Retention: history past RETENTION_DAYS goes, with its result snapshot.
        ancient = datetime.now(UTC) - timedelta(days=ready.settings.retention_days + 1)
        await _sql(ready, "UPDATE query_executions SET created_at = :t", t=ancient)
        await _sql(ready, "UPDATE conversations SET last_message_at = :t", t=ancient)
        assert await tasks.retention(container) == 2
        assert await _sql(ready, "SELECT id FROM conversations") == []
        assert await _sql(ready, "SELECT id FROM query_executions") == []
        # The audit log keeps every query.
        assert await ready.audit(action="query.executed")
    finally:
        await container.close()


@pytest.fixture
def settings_overrides(request: pytest.FixtureRequest) -> dict[str, Any]:
    return {"question_rpm": 3} if "rate_limited" in request.node.name else {}


async def test_questions_are_rate_limited_per_project(ready: Stack, sources: Sources) -> None:
    conn = await ready.connection(sources.pg())
    for _ in range(3):
        await ready.ask("How many orders?", connection_id=conn["id"], wait=0)
    resp = await ready.client.post(
        ready.p("/chat"),
        json={"connection_id": conn["id"], "question": "How many orders?", "wait": 0},
    )
    assert resp.status_code == 429 and int(resp.headers["retry-after"]) >= 1
