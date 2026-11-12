"""Asking questions end to end: a connected database, its real schema in the prompt, one
validated read-only query, its result, a chart, and follow-ups (A1, A5, A6, A9, A12)."""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa

from tests.integration.conftest import Sources, Stack, _admin_url

pytestmark = pytest.mark.integration


def _source_scalar(sql: str) -> object:
    engine = sa.create_engine(
        _admin_url("postgresql", "shop_test").replace("postgresql://", "postgresql+psycopg://")
    )
    try:
        with engine.connect() as c:
            return c.exec_driver_sql(sql).scalar()
    finally:
        engine.dispose()


async def test_a1_ask_a_question_and_get_a_completed_answer_with_its_sql(
    ready: Stack, sources: Sources
) -> None:
    conn = await ready.connection(sources.pg())
    msg = await ready.ask("How many orders per status?", connection_id=conn["id"])
    assert msg["status"] == "answered", msg
    assert msg["validated"] is True
    assert msg["sql"].upper().startswith("SELECT")
    assert "orders" in msg["sql"]
    assert msg["explanation"]
    page = msg["page"]
    assert page["total"] == 5
    statuses = {row[0]: row[1] for row in page["rows"]}
    expected = _source_scalar("SELECT count(*) FROM orders WHERE status = 'delivered'")
    assert statuses["delivered"] == expected
    assert msg["execution"]["status"] == "succeeded"
    assert msg["execution"]["row_count"] == 5
    # The conversation is saved with its question, SQL and result.
    conv = await ready.ok("GET", ready.p(f"/conversations/{msg['conversation_id']}"))
    assert conv["messages"][0]["sql"] == msg["sql"]
    assert conv["messages"][0]["page"]["rows"]


async def test_a5_schema_discovery_lists_real_tables_and_the_prompt_uses_them(
    ready: Stack, sources: Sources
) -> None:
    conn = await ready.connection(sources.pg())
    schema = await ready.ok("GET", ready.p(f"/connections/{conn['id']}/schema"))
    names = {t["name"] for t in schema["tables"]}
    assert names == {"customers", "products", "orders", "order_items", "monthly_revenue"}
    assert not any(
        t["schema_name"] in ("pg_catalog", "information_schema") for t in schema["tables"]
    )
    orders = next(t for t in schema["tables"] if t["name"] == "orders")
    cols = {c["name"]: c for c in orders["columns"]}
    assert cols["id"]["primary_key"] is True
    assert "numeric" in cols["total_amount"]["type"]
    assert orders["foreign_keys"] == [
        {"columns": ["customer_id"], "ref_table": "public.customers", "ref_columns": ["id"]}
    ]
    assert orders["row_count"] == 6000
    assert any(ix["columns"] == ["order_date"] for ix in orders["indexes"])
    assert set(cols["status"]["sample_values"]) == {
        "delivered",
        "shipped",
        "processing",
        "cancelled",
        "returned",
    }
    view = next(t for t in schema["tables"] if t["name"] == "monthly_revenue")
    assert view["kind"] == "view" and [c["name"] for c in view["columns"]] == [
        "month",
        "orders",
        "revenue",
    ]
    # The model is given exactly this schema: the generated SQL joins along a real key.
    gen = await ready.ok(
        "POST",
        ready.p("/sql/generate"),
        {"connection_id": conn["id"], "question": "Revenue by product category"},
    )
    assert gen["valid"] is True
    assert "JOIN public.products" in gen["sql"] and "line_total" in gen["sql"]
    assert set(gen["tables"]) == {"public.order_items", "public.products"}
    # A table that does not exist is never invented.
    gen = await ready.ok(
        "POST",
        ready.p("/sql/generate"),
        {"connection_id": conn["id"], "question": "What is the weather on Mars?"},
    )
    assert gen["sql"] is None and "could not match" in gen["explanation"]


async def test_a5_schema_refresh_sees_a_new_table(ready: Stack, sources: Sources) -> None:
    conn = await ready.connection(sources.pg(admin=True))
    first = await ready.ok("GET", ready.p(f"/connections/{conn['id']}/schema"))
    engine = sa.create_engine(
        _admin_url("postgresql", "shop_test").replace("postgresql://", "postgresql+psycopg://")
    )
    try:
        with engine.begin() as c:
            c.exec_driver_sql("CREATE TABLE IF NOT EXISTS coupons (code text PRIMARY KEY, pct int)")
        refreshed = await ready.ok("POST", ready.p(f"/connections/{conn['id']}/schema/refresh"))
        assert refreshed["refreshed_at"] > first["refreshed_at"]
        assert "coupons" in {t["name"] for t in refreshed["tables"]}
        # The cache moved to the new version at once.
        again = await ready.ok("GET", ready.p(f"/connections/{conn['id']}/schema"))
        assert "coupons" in {t["name"] for t in again["tables"]}
    finally:
        with engine.begin() as c:
            c.exec_driver_sql("DROP TABLE IF EXISTS coupons")
        engine.dispose()


async def test_a6_follow_up_resolves_against_the_previous_question(
    ready: Stack, sources: Sources
) -> None:
    conn = await ready.connection(sources.pg())
    this_year = dt.date.today().year
    first = await ready.ok(
        "POST",
        ready.p("/chat"),
        {"connection_id": conn["id"], "question": "How many orders were placed this year?"},
        status=201,
    )
    assert first["status"] == "answered"
    assert f"{this_year}-01-01" in first["sql"]
    follow = await ready.ask("and last year?", conversation_id=first["conversation_id"])
    assert follow["status"] == "answered", follow
    # Same table and measure, only the time range changed.
    assert "COUNT(*)" in follow["sql"] and "orders" in follow["sql"]
    assert f"{this_year - 1}-01-01" in follow["sql"] and f"{this_year}-01-01" in follow["sql"]
    expected = _source_scalar(
        f"SELECT count(*) FROM orders WHERE order_date >= '{this_year - 1}-01-01' "
        f"AND order_date < '{this_year}-01-01'"
    )
    assert follow["page"]["rows"] == [[expected]]
    # A second follow-up keeps building on the conversation.
    split = await ready.ask("break it down by channel", conversation_id=first["conversation_id"])
    assert split["status"] == "answered"
    assert "channel" in split["sql"] and f"{this_year - 1}-01-01" in split["sql"]
    assert sum(r[1] for r in split["page"]["rows"]) == expected
    conv = await ready.ok("GET", ready.p(f"/conversations/{first['conversation_id']}"))
    assert [m["seq"] for m in conv["messages"]] == [1, 2, 3]
    assert conv["message_count"] == 3


async def test_a9_results_offer_a_chart_when_the_shape_fits(ready: Stack, sources: Sources) -> None:
    conn = await ready.connection(sources.pg())
    by_month = await ready.ask("Monthly revenue last year", connection_id=conn["id"])
    assert by_month["execution"]["chart"]["type"] == "line"
    assert by_month["execution"]["chart"]["x"] == "month"
    by_status = await ready.ask("How many orders per status?", connection_id=conn["id"])
    assert by_status["execution"]["chart"]["type"] == "pie"
    assert "bar" in by_status["execution"]["chart"]["alternatives"]
    top = await ready.ask("Top 10 customers by total spend", connection_id=conn["id"])
    assert top["execution"]["chart"]["type"] == "bar"
    listing = await ready.ask("Show the 5 latest orders", connection_id=conn["id"])
    assert listing["execution"]["chart"] is None
    assert listing["page"]["total"] == 5
    single = await ready.ask("How many customers are there?", connection_id=conn["id"])
    assert single["execution"]["chart"] is None
    # The same decision is available for any result.
    out = await ready.ok(
        "POST",
        ready.p("/charts/suggest"),
        {
            "columns": [{"name": "country", "kind": "text"}, {"name": "revenue", "kind": "number"}],
            "rows": [["DE", 10], ["IN", 20], ["US", 30]],
        },
    )
    assert out["chart"]["type"] == "pie"


async def test_mysql_and_sqlite_answer_in_their_own_dialects(
    ready: Stack, sources: Sources
) -> None:
    people = await ready.connection(sources.mysql())
    msg = await ready.ask("Average salary by department", connection_id=people["id"])
    assert msg["status"] == "answered", msg
    assert msg["page"]["total"] == 7
    assert msg["execution"]["chart"]["type"] in ("bar", "pie")
    hired = await ready.ask("How many employees were hired each year?", connection_id=people["id"])
    assert hired["status"] == "answered" and "YEAR(" in hired["sql"]
    subs = await ready.sqlite(sources.sqlite_path)
    msg = await ready.ask("Monthly revenue from invoices this year", connection_id=subs["id"])
    assert msg["status"] == "answered", msg
    assert "strftime" in msg["sql"]
    msg = await ready.ask("How many accounts per plan?", connection_id=subs["id"])
    assert sorted(r[0] for r in msg["page"]["rows"]) == [
        "Business",
        "Enterprise",
        "Starter",
        "Team",
    ]


async def test_templates_save_and_rerun_a_question(ready: Stack, sources: Sources) -> None:
    conn = await ready.connection(sources.pg())
    msg = await ready.ask("Revenue by country this year", connection_id=conn["id"])
    tpl = await ready.ok(
        "POST",
        ready.p("/templates/from-message"),
        {"message_id": msg["id"], "name": "Revenue by country"},
        status=201,
    )
    assert tpl["sql"] == msg["sql"]
    again = await ready.ok("POST", ready.p(f"/templates/{tpl['id']}/run"), {"wait": 30}, status=201)
    assert again["status"] == "answered"
    assert again["sql"] == msg["sql"] and again["template_id"] == tpl["id"]
    assert again["page"]["rows"] == msg["page"]["rows"]
    # A template's SQL is guarded when saved.
    resp = await ready.client.post(
        ready.p("/templates"),
        json={
            "connection_id": conn["id"],
            "name": "Bad",
            "question": "x",
            "sql": "DELETE FROM orders",
        },
    )
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "unsafe_sql"
    listed = await ready.ok("GET", ready.p("/templates"))
    assert [t["use_count"] for t in listed] == [1]


async def test_results_paginate_and_export_as_csv(ready: Stack, sources: Sources) -> None:
    conn = await ready.connection(sources.pg(), max_rows=120)
    out = await ready.ok(
        "POST",
        ready.p("/sql/execute"),
        {
            "connection_id": conn["id"],
            "sql": "SELECT id, name FROM customers ORDER BY id",
            "page_size": 50,
        },
    )
    assert out["status"] == "succeeded"
    assert out["row_count"] == 120 and out["truncated"] is True
    assert len(out["page"]["rows"]) == 50 and out["page"]["total"] == 120
    page = await ready.ok(
        "GET", ready.p(f"/executions/{out['id']}/rows"), params={"offset": 100, "limit": 50}
    )
    assert [r[0] for r in page["rows"]] == list(range(101, 121))
    resp = await ready.client.get(ready.p(f"/executions/{out['id']}/export.csv"))
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.strip().splitlines()
    assert lines[0] == "id,name" and len(lines) == 121
    listed = await ready.ok("GET", ready.p("/executions"), params={"connection_id": conn["id"]})
    assert listed["items"][0]["id"] == out["id"]
