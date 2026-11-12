"""The Python SDK and CLI (sdk/python) against the live API."""

from __future__ import annotations

import asyncio

import pytest
from euron_sqlagent import AsyncSQLAgent, SQLAgent, SQLAgentError
from euron_sqlagent.cli import main as cli

from tests.integration.conftest import Sources, Stack

pytestmark = pytest.mark.integration


async def _key(stack: Stack, scopes: list[str]) -> str:
    created = await stack.ok(
        "POST", stack.p("/api-keys"), {"name": "sdk", "scopes": scopes}, status=201
    )
    return str(created["key"])


async def test_the_sync_client_asks_follows_up_explains_and_exports(
    ready: Stack, sources: Sources
) -> None:
    await ready.connection(sources.pg())
    key = await _key(ready, ["read", "query"])

    def go() -> None:
        with SQLAgent(base_url=ready.api_url, api_key=key) as client:
            assert client.project()["id"] == ready.project_id
            assert [c["name"] for c in client.connections()] == ["Shop (PostgreSQL)"]
            schema = client.schema("Shop (PostgreSQL)")
            assert len(schema["tables"]) == 5
            answer = client.ask("How many orders per status?", connection="Shop (PostgreSQL)")
            assert answer.ok and answer.validated and answer.chart and answer.chart.type == "pie"
            assert answer.records()[0]["status"] == "delivered"
            follow = client.ask("and only shipped ones", conversation=answer.conversation_id)
            assert follow.ok and "shipped" in (follow.sql or "")
            again = client.answer(answer.id)
            assert again.sql == answer.sql
            gen = client.generate("Revenue by product category", connection="Shop (PostgreSQL)")
            assert gen["valid"] is True
            assert client.validate("DROP TABLE orders", dialect="postgresql")["valid"] is False
            explained = client.explain(
                "SELECT count(*) FROM orders", connection="Shop (PostgreSQL)", use_model=False
            )
            assert explained["executed"] is False
            result = client.execute(
                "SELECT id, name FROM products ORDER BY id", connection="Shop (PostgreSQL)"
            )
            assert result.ok and result.row_count == 33 and result.columns == ["id", "name"]
            assert client.rows(result.id, offset=30)["rows"][0][0] == 31
            assert client.csv(result.id).splitlines()[0] == "id,name"
            assert client.conversations()[0]["id"] == answer.conversation_id
            assert len(client.conversation(answer.conversation_id)["messages"]) == 2
            with pytest.raises(SQLAgentError) as caught:
                client.ask("x", connection="No such database")
            assert caught.value.code == "not_found"

    await asyncio.to_thread(go)


async def test_the_async_client_and_scopes(ready: Stack, sources: Sources) -> None:
    await ready.connection(sources.pg())
    reader = await _key(ready, ["read"])
    async with AsyncSQLAgent(base_url=ready.api_url, api_key=reader) as client:
        assert len(await client.connections()) == 1
        with pytest.raises(SQLAgentError) as caught:
            await client.ask("How many orders?", connection="Shop (PostgreSQL)")
        assert caught.value.status == 403 and caught.value.code == "insufficient_scope"
    full = await _key(ready, ["read", "query"])
    async with AsyncSQLAgent(base_url=ready.api_url, api_key=full) as client:
        answer = await client.ask("How many customers per segment?", connection="Shop (PostgreSQL)")
        assert answer.ok and answer.total_rows == 3
        result = await client.execute("SELECT 1 AS one", connection="Shop (PostgreSQL)")
        assert result.rows == [[1]]
        assert (await client.csv(result.id)).startswith("one")
        out = await client.explain("SELECT 1", dialect="sqlite", use_model=False)
        assert out["source"] == "syntax"


async def test_the_cli(ready: Stack, sources: Sources, capsys: pytest.CaptureFixture[str]) -> None:
    await ready.connection(sources.pg())
    key = await _key(ready, ["read", "query"])
    base = ["--url", ready.api_url, "--api-key", key]

    def run(*args: str) -> int:
        with pytest.raises(SystemExit) as code:
            cli([*base, *args])
        return int(code.value.code or 0)

    def go() -> None:
        assert run("connections") == 0
        assert "Shop (PostgreSQL)" in capsys.readouterr().out
        assert run("ask", "Shop (PostgreSQL)", "How many orders per status?") == 0
        out = capsys.readouterr().out
        assert "validated read-only" in out and "delivered" in out and "chart: pie" in out
        assert run("ask", "Shop (PostgreSQL)", "Delete all orders") == 1
        assert "[refused]" in capsys.readouterr().out
        assert run("validate", "DROP TABLE orders", "--dialect", "postgresql") == 1
        assert "refused" in capsys.readouterr().out
        assert run("run", "Shop (PostgreSQL)", "SELECT count(*) AS n FROM customers", "--csv") == 0
        assert capsys.readouterr().out.splitlines() == ["n", "400"]
        assert run("explain", "SELECT 1", "--dialect", "mysql", "--no-model") == 0
        assert "read-only" in capsys.readouterr().out
        assert run("schema", "Shop (PostgreSQL)") == 0
        assert "public.orders" in capsys.readouterr().out
        assert run("templates") == 0
        assert run("ask", "Nope", "x") == 2

    await asyncio.to_thread(go)
