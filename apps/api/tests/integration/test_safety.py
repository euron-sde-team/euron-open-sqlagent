"""The safety contract: sealed credentials, the SQL guard before execution, read-only
connections in the database itself, enforced limits, explaining without executing
(A2, A3, A4, A8, A10)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from sqlagent.connections.sources import SqlTarget, open_sql
from tests.integration.conftest import SOURCE_PASSWORD, Sources, Stack, _admin_url

pytestmark = pytest.mark.integration


def _count(kind: str, sql: str) -> int:
    url = _admin_url(kind, "shop_test" if kind == "postgresql" else "people_test")
    driver = "postgresql+psycopg://" if kind == "postgresql" else "mysql+pymysql://"
    engine = sa.create_engine(url.replace(f"{kind}://", driver, 1))
    try:
        with engine.connect() as c:
            return int(c.exec_driver_sql(sql).scalar() or 0)
    finally:
        engine.dispose()


async def test_a2_password_is_sealed_never_returned_and_is_what_opens_the_database(
    ready: Stack, sources: Sources
) -> None:
    body = sources.pg()
    conn = await ready.connection(body)
    assert conn["has_password"] is True
    assert "password" not in conn
    for path in ("/connections", f"/connections/{conn['id']}"):
        text = (await ready.client.get(ready.p(path))).text
        assert body["password"] not in text
    # Stored sealed: the row holds ciphertext, never the password.
    engine = create_async_engine(ready.settings.database_url)
    async with engine.connect() as c:
        sealed = (
            await c.execute(
                sa.text("SELECT secret_sealed, config::text FROM connections WHERE id = :id"),
                {"id": conn["id"]},
            )
        ).one()
    await engine.dispose()
    assert sealed[0] is not None and body["password"].encode() not in bytes(sealed[0])
    assert body["password"] not in sealed[1]
    # The sealed password is the credential that opens the database: the test connects ...
    ok = await ready.ok("POST", ready.p(f"/connections/{conn['id']}/test"))
    assert ok["ok"] is True and ok["read_only"] is True
    assert ok["server_version"].startswith("PostgreSQL 16")
    assert ok["latency_ms"] > 0 and ok["tables"] == 5
    # ... and with a wrong one stored instead, the same connection is refused.
    await ready.ok("PATCH", ready.p(f"/connections/{conn['id']}"), {"password": "wrong-password"})
    bad = await ready.ok("POST", ready.p(f"/connections/{conn['id']}/test"))
    assert bad["ok"] is False and "password was refused" in bad["message"]
    # Provider keys are sealed too, and the stored key is what reaches the provider.
    prov = await ready.provider("gateway", "openai_compatible")
    assert prov["has_api_key"] is True and "api_key" not in prov
    await ready.ok("POST", ready.p(f"/providers/{prov['id']}/test"))
    auth = (await ready.client.get(f"{ready.mock_ai_url}/_mock/auth")).json()
    assert auth["v1"] == "Bearer sk-gateway-secret"
    listed = (await ready.client.get(ready.p("/providers"))).text
    assert "sk-gateway-secret" not in listed


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "UPDATE orders SET total_amount = 0",
        "INSERT INTO orders (id) VALUES (999999)",
        "DROP TABLE orders",
        "TRUNCATE orders",
        "SELECT 1; DELETE FROM orders",
        "SELECT pg_sleep(1)",
        "WITH gone AS (DELETE FROM orders RETURNING *) SELECT count(*) FROM gone",
        "SELECT * INTO stolen FROM orders",
        "SELECT * FROM orders FOR UPDATE",
        "COPY orders TO '/tmp/orders.csv'",
    ],
)
async def test_a3_the_guard_refuses_before_the_database_is_reached(
    ready: Stack, sources: Sources, sql: str
) -> None:
    # The admin login could write: only the guard (and the session) stand in the way.
    conn = await ready.connection(sources.pg(admin=True))
    before = _count("postgresql", "SELECT count(*) FROM orders")
    out = await ready.ok("POST", ready.p("/sql/execute"), {"connection_id": conn["id"], "sql": sql})
    assert out["status"] == "refused", out
    assert out["error_code"] in (
        "not_a_select",
        "multiple_statements",
        "denied_function",
        "write_or_admin",
    )
    assert out["row_count"] == 0 and out["duration_ms"] == 0
    assert _count("postgresql", "SELECT count(*) FROM orders") == before
    # The refusal is in the audit log with the SQL, and never reached the database.
    entry = (await ready.audit(action="query.refused", connection_id=conn["id"]))[0]
    assert entry["details"]["sql"] == sql.strip() and entry["details"]["status"] == "refused"


async def test_a3_a_generated_write_is_refused_and_never_runs(
    ready: Stack, sources: Sources
) -> None:
    conn = await ready.connection(sources.pg(admin=True))
    before = _count("postgresql", "SELECT count(*) FROM orders WHERE status = 'cancelled'")
    msg = await ready.ask("Delete all cancelled orders", connection_id=conn["id"])
    assert msg["status"] == "refused"
    assert msg["sql"].startswith("DELETE FROM")
    assert msg["validated"] is False
    assert "only SELECT" in msg["error"]
    assert msg["execution"]["status"] == "refused" and msg["page"] is None
    assert _count("postgresql", "SELECT count(*) FROM orders WHERE status = 'cancelled'") == before
    actions = [e["action"] for e in await ready.audit(connection_id=conn["id"])]
    assert "question.refused" in actions and "query.refused" in actions


@pytest.mark.parametrize("kind", ["postgresql", "mysql", "sqlite"])
async def test_a4_a_write_that_reaches_the_connection_still_fails_at_the_database(
    sources: Sources, kind: str
) -> None:
    """Bypass the guard entirely and send writes straight down the read-only connection,
    logged in with a login that has write rights."""
    if kind == "postgresql":
        target = SqlTarget(
            "postgresql", "127.0.0.1", 5443, "shop_test", "shop_admin", SOURCE_PASSWORD, "disable"
        )
        writes = [
            "DELETE FROM orders",
            "CREATE TABLE x (id int)",
            "UPDATE products SET unit_price = 0",
        ]
        marker = "read-only transaction"
    elif kind == "mysql":
        target = SqlTarget(
            "mysql", "127.0.0.1", 5406, "people_test", "root", SOURCE_PASSWORD, "disable"
        )
        writes = ["DELETE FROM leave_requests", "UPDATE employees SET salary = 0"]
        marker = "read only transaction"
    else:
        target = SqlTarget("sqlite", sqlite_path=str(sources.sqlite_path))
        writes = ["DELETE FROM invoices", "CREATE TABLE x (id int)"]
        marker = "readonly"
    for sql in writes:
        with open_sql(target, 10) as c:
            raw = c.connection.dbapi_connection
            assert raw is not None
            cur = raw.cursor()
            with pytest.raises(Exception) as caught:
                cur.execute(sql)
        text = str(caught.value).lower().replace("-", " ").replace("_", " ")
        assert marker.replace("-", " ") in text or "read only" in text or "query only" in text, text
    if kind == "postgresql":
        assert _count("postgresql", "SELECT count(*) FROM orders") == 6000
    elif kind == "mysql":
        assert _count("mysql", "SELECT count(*) FROM employees WHERE salary = 0") == 0


async def test_a8_a_query_over_the_scan_limit_is_stopped_before_it_runs(
    ready: Stack, sources: Sources
) -> None:
    conn = await ready.connection(sources.pg(), max_scan_rows=1000)
    out = await ready.ok(
        "POST",
        ready.p("/sql/execute"),
        {"connection_id": conn["id"], "sql": "SELECT status, count(*) FROM orders GROUP BY status"},
    )
    assert out["status"] == "scan_limit"
    assert out["estimated_scan_rows"] >= 6000
    assert "more than this connection allows (1,000)" in out["error"]
    small = await ready.ok(
        "POST",
        ready.p("/sql/execute"),
        {"connection_id": conn["id"], "sql": "SELECT name FROM products ORDER BY name"},
    )
    assert small["status"] == "succeeded" and small["row_count"] == 33
    # The same limit applies to a question.
    msg = await ready.ask("How many orders per status?", connection_id=conn["id"])
    assert msg["status"] == "failed" and msg["error_code"] == "scan_limit"


@pytest.mark.parametrize("kind", ["postgresql", "mysql", "sqlite"])
async def test_a8_a_query_over_the_time_limit_is_cancelled_by_the_database(
    ready: Stack, sources: Sources, kind: str
) -> None:
    if kind == "postgresql":
        conn = await ready.connection(sources.pg(), timeout_s=1)
        sql = "SELECT count(*) FROM order_items a, order_items b, order_items c"
    elif kind == "mysql":
        conn = await ready.connection(sources.mysql(), timeout_s=1)
        sql = (
            "SELECT sum(a.days * b.days + c.days) FROM leave_requests a, leave_requests b, "
            "leave_requests c"
        )
    else:
        conn = await ready.sqlite(sources.sqlite_path, timeout_s=1)
        sql = "SELECT count(*) FROM invoices a, invoices b, invoices c"
    out = await ready.ok("POST", ready.p("/sql/execute"), {"connection_id": conn["id"], "sql": sql})
    assert out["status"] == "timeout", out
    assert out["error_code"] == "timeout" and "1 s" in out["error"]
    entry = (await ready.audit(action="query.executed", connection_id=conn["id"]))[0]
    assert entry["details"]["status"] == "timeout"


async def test_a10_explaining_a_pasted_query_never_executes_it(
    ready: Stack, sources: Sources
) -> None:
    conn = await ready.connection(sources.pg())
    pasted = (
        "SELECT c.country, sum(o.total_amount) AS revenue FROM orders o "
        "JOIN customers c ON c.id = o.customer_id WHERE o.status = 'delivered' "
        "GROUP BY c.country ORDER BY revenue DESC LIMIT 3"
    )
    out = await ready.ok(
        "POST", ready.p("/sql/explain"), {"connection_id": conn["id"], "sql": pasted}
    )
    assert out["executed"] is False and out["source"] == "model"
    assert "orders" in out["explanation"] and "customers" in out["explanation"]
    assert out["analysis"]["read_only"] is True
    assert out["analysis"]["tables"] == ["orders", "customers"]
    assert out["analysis"]["group_by"] == ["c.country"] and out["analysis"]["limit"] == 3
    # A query against a table that does not exist is explained too: it never ran.
    ghost = await ready.ok(
        "POST",
        ready.p("/sql/explain"),
        {
            "dialect": "mysql",
            "sql": "SELECT name FROM no_such_table WHERE id > 10",
            "use_model": False,
        },
    )
    assert ghost["source"] == "syntax" and "no_such_table" in ghost["explanation"]
    # A destructive statement is explained, flagged, and still not run.
    before = _count("postgresql", "SELECT count(*) FROM orders")
    bad = await ready.ok(
        "POST",
        ready.p("/sql/explain"),
        {"connection_id": conn["id"], "sql": "DELETE FROM orders WHERE status = 'cancelled'"},
    )
    assert bad["analysis"]["read_only"] is False and "deletes rows" in bad["explanation"]
    assert _count("postgresql", "SELECT count(*) FROM orders") == before
    executions = await ready.ok("GET", ready.p("/executions"))
    assert executions["items"] == []
    # Validation answers the same question without the model.
    v = await ready.ok("POST", ready.p("/sql/validate"), {"dialect": "postgresql", "sql": pasted})
    assert v["valid"] is True and v["tables"] == ["orders", "customers"]
    v = await ready.ok(
        "POST", ready.p("/sql/validate"), {"dialect": "sqlite", "sql": "PRAGMA writable_schema=1"}
    )
    assert v["valid"] is False and v["code"] == "not_a_select"
