"""The deterministic planner behind the mock provider: the same question gets the same SQL,
every generated query passes the guard, and follow-ups change only what they name (A6)."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from sqlagent.providers.mock.planner import plan
from sqlagent.providers.mock.responder import respond
from sqlagent.schema.prompt import render
from sqlagent.schema.schemas import SchemaColumn, SchemaForeignKey, SchemaTable
from sqlagent.sql.guard import check

TODAY = dt.date(2026, 6, 15)


def col(
    name: str, type_: str = "integer", pk: bool = False, values: list[str] | None = None
) -> SchemaColumn:
    return SchemaColumn(name=name, type=type_, primary_key=pk, sample_values=values or [])


def fk(column: str, ref: str) -> SchemaForeignKey:
    return SchemaForeignKey(columns=[column], ref_table=ref, ref_columns=["id"])


SHOP = [
    SchemaTable(
        schema_name="public",
        name="customers",
        kind="table",
        columns=[
            col("id", pk=True),
            col("name", "varchar(120)"),
            col("country", "varchar(60)", values=["Germany", "India"]),
            col("segment", "varchar(20)", values=["consumer", "enterprise"]),
            col("created_at", "date"),
        ],
    ),
    SchemaTable(
        schema_name="public",
        name="products",
        kind="table",
        columns=[
            col("id", pk=True),
            col("name", "varchar"),
            col("category", "varchar"),
            col("unit_price", "numeric(10, 2)"),
        ],
    ),
    SchemaTable(
        schema_name="public",
        name="orders",
        kind="table",
        columns=[
            col("id", pk=True),
            col("customer_id"),
            col("status", "varchar(20)", values=["delivered", "shipped", "cancelled"]),
            col("order_date", "date"),
            col("total_amount", "numeric(12, 2)"),
            col("channel", "varchar(20)", values=["web", "mobile"]),
        ],
        foreign_keys=[fk("customer_id", "public.customers")],
    ),
    SchemaTable(
        schema_name="public",
        name="order_items",
        kind="table",
        columns=[
            col("id", pk=True),
            col("order_id"),
            col("product_id"),
            col("quantity"),
            col("line_total", "numeric(12, 2)"),
        ],
        foreign_keys=[fk("order_id", "public.orders"), fk("product_id", "public.products")],
    ),
    SchemaTable(
        schema_name="public",
        name="monthly_revenue",
        kind="view",
        columns=[col("month", "date"), col("orders", "bigint"), col("revenue", "numeric")],
    ),
]


def sql_for(*questions: str, dialect: str = "postgresql") -> str:
    out = plan(SHOP, list(questions), dialect, TODAY)
    assert out.sql is not None, out.note
    return out.sql


@pytest.mark.parametrize(
    ("question", "must"),
    [
        (
            "How many orders were placed last year?",
            ["COUNT(*)", "public.orders", "'2025-01-01'", "'2026-01-01'"],
        ),
        (
            "How many orders per status?",
            ["t0.status AS status", "GROUP BY t0.status", "ORDER BY order_count DESC"],
        ),
        (
            "Monthly revenue this year",
            ["date_trunc('month', t0.order_date)", "SUM(t0.total_amount)", "AS revenue"],
        ),
        (
            "Top 5 customers by total spend",
            ["JOIN public.customers t1", "t1.name AS customer_name", "LIMIT 5"],
        ),
        (
            "Revenue by product category",
            ["public.order_items t0", "JOIN public.products", "t1.category", "line_total"],
        ),
        ("Which channel has the most orders?", ["t0.channel", "LIMIT 1"]),
        ("Show the 10 latest orders", ["ORDER BY t0.order_date DESC", "LIMIT 10"]),
        (
            "How many cancelled orders in March 2026?",
            ["t0.status = 'cancelled'", "'2026-03-01'", "'2026-04-01'"],
        ),
        (
            "Average order value by month last year",
            ["AVG(t0.total_amount)", "public.orders", "'2025-01-01'"],
        ),
        ("How many customers since 2025?", ["t0.created_at >= DATE '2025-01-01'"]),
        ("Revenue in the last 30 days", ["'2026-05-16'", "'2026-06-16'"]),
        ("How many orders this month?", ["'2026-06-01'"]),
        ("How many orders last month?", ["'2026-05-01'", "'2026-06-01'"]),
        ("Bottom 3 countries by revenue", ["ORDER BY revenue ASC", "LIMIT 3"]),
        ("Weekly revenue this year", ["date_trunc('week'"]),
    ],
)
def test_questions_become_guarded_sql_against_the_real_schema(
    question: str, must: list[str]
) -> None:
    sql = sql_for(question)
    for part in must:
        assert part in sql, (part, sql)
    check(sql, "postgresql")
    assert sql_for(question) == sql  # deterministic


def test_follow_ups_change_only_what_they_name() -> None:
    first = sql_for("How many orders were placed this year?")
    assert "'2026-01-01'" in first
    second = sql_for("How many orders were placed this year?", "and last year?")
    assert "COUNT(*)" in second and "'2025-01-01'" in second and "'2026-01-01'" in second
    third = sql_for(
        "How many orders were placed this year?", "and last year?", "break it down by channel"
    )
    assert "t0.channel" in third and "'2025-01-01'" in third
    filtered = sql_for("Revenue by country this year", "only enterprise customers")
    assert "t1.segment = 'enterprise'" in filtered and "t1.country" in filtered
    regrouped = sql_for("How many customers per segment", "break it down by country instead")
    assert "t0.country" in regrouped and "segment" not in regrouped.split("FROM")[0]
    limited = sql_for("Revenue by country", "top 3 instead")
    assert "LIMIT 3" in limited
    averaged = sql_for("Total revenue by month", "what about the average instead")
    assert "AVG(" in averaged


@pytest.mark.parametrize("dialect", ["postgresql", "mysql", "sqlite"])
def test_each_dialect_gets_its_own_date_functions(dialect: str) -> None:
    sql = sql_for("Monthly revenue last year", dialect=dialect)
    check(sql, dialect)
    marker = {"postgresql": "date_trunc", "mysql": "DATE_FORMAT", "sqlite": "strftime"}[dialect]
    assert marker in sql
    yearly = sql_for("How many orders were placed each year?", dialect=dialect)
    check(yearly, dialect)
    quarterly = sql_for("Quarterly revenue", dialect=dialect)
    check(quarterly, dialect)
    daily = sql_for("Daily revenue last month", dialect=dialect)
    check(daily, dialect)


def test_destructive_requests_are_written_as_asked_so_the_guard_can_refuse_them() -> None:
    assert (
        sql_for("Delete all cancelled orders")
        == "DELETE FROM public.orders WHERE status = 'cancelled'"
    )
    assert sql_for("drop table customers") == "DROP TABLE public.customers"
    assert sql_for("update the products price").startswith("UPDATE public.products SET unit_price")


def test_unanswerable_questions_get_an_honest_no() -> None:
    out = plan(SHOP, ["What is the weather on Mars?"], "postgresql", TODAY)
    assert out.sql is None and "could not match" in out.note
    assert plan([], ["How many orders?"], "postgresql", TODAY).sql is None


def test_responder_reads_the_prompt_like_a_model_would() -> None:
    system = "\n".join(
        ["TASK: generate", "Dialect: mysql", "Today: 2026-06-15", "", render(SHOP, "", 50_000)]
    )
    answer = json.loads(respond(system, [("user", "Question: How many orders per status?")]))
    assert answer["sql"].startswith("SELECT t0.status") and "orders" in answer["explanation"]
    follow = json.loads(
        respond(
            system,
            [
                ("user", "Question: How many orders this year?"),
                ("assistant", json.dumps({"sql": "x", "explanation": "y"})),
                ("user", "Question: and last year?"),
            ],
        )
    )
    assert "'2025-01-01'" in follow["sql"]
    explained = json.loads(
        respond("TASK: explain\nDialect: sqlite", [("user", "```sql\nSELECT 1\n```")])
    )
    assert "computed result" in explained["explanation"]
    assert "only answers SQLAgent prompts" in respond("You are a poet", [("user", "hi")])
