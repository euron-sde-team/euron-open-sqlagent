"""What a query does (from its AST), the prompts the model gets, and reading answers back."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from sqlagent.schema.schemas import SchemaColumn, SchemaForeignKey, SchemaTable
from sqlagent.sql.describe import analyze, describe
from sqlagent.sql.prompt import (
    Turn,
    explain_messages,
    generate_messages,
    parse_answer,
    parse_explanation,
)

ORDERS = SchemaTable(
    schema_name="public",
    name="orders",
    kind="table",
    row_count=6000,
    columns=[
        SchemaColumn(name="id", type="integer", primary_key=True),
        SchemaColumn(name="customer_id", type="integer"),
        SchemaColumn(name="status", type="varchar(20)", sample_values=["delivered", "shipped"]),
        SchemaColumn(name="order_date", type="date"),
        SchemaColumn(name="total_amount", type="numeric(12, 2)"),
    ],
    foreign_keys=[
        SchemaForeignKey(columns=["customer_id"], ref_table="public.customers", ref_columns=["id"])
    ],
)
CUSTOMERS = SchemaTable(
    schema_name="public",
    name="customers",
    kind="table",
    row_count=400,
    columns=[
        SchemaColumn(name="id", type="integer", primary_key=True),
        SchemaColumn(name="name", type="varchar(120)"),
        SchemaColumn(name="country", type="varchar(60)"),
    ],
)


def test_analysis_reads_the_structure_of_a_query() -> None:
    a = analyze(
        "WITH big AS (SELECT * FROM orders WHERE total_amount > 100) "
        "SELECT c.country, count(*) AS n, sum(b.total_amount) FROM big b "
        "LEFT JOIN customers c ON c.id = b.customer_id WHERE c.country <> 'X' AND b.status = 'shipped' "
        "GROUP BY c.country HAVING count(*) > 2 ORDER BY n DESC LIMIT 10",
        "postgresql",
    )
    assert a.statement == "select" and a.read_only is True
    assert a.ctes == ["big"] and sorted(a.tables) == ["customers", "orders"]
    assert a.joins == ["left join customers AS c on c.id = b.customer_id"]
    assert a.filters[:2] == ["c.country <> 'X'", "b.status = 'shipped'"]
    assert a.filters[2].startswith("(after grouping)")
    assert a.group_by == ["c.country"] and a.limit == 10
    assert a.order_by == ["n descending"]
    assert "COUNT(*)" in a.aggregates and "SUM(b.total_amount)" in a.aggregates


@pytest.mark.parametrize(
    ("sql", "dialect", "expected"),
    [
        (
            "SELECT name FROM customers ORDER BY name LIMIT 5",
            "postgresql",
            "It returns at most 5 rows",
        ),
        ("DELETE FROM orders WHERE status = 'cancelled'", "postgresql", "deletes rows from orders"),
        ("UPDATE employees SET salary = 0", "mysql", "changes rows in employees"),
        ("DROP TABLE invoices", "sqlite", "drops invoices"),
        ("SELEC oops", "postgresql", "not a query SQLAgent can read"),
        (
            "SELECT name, rank() OVER (ORDER BY salary DESC) FROM employees",
            "mysql",
            "window function",
        ),
        ("SELECT 1", "sqlite", "a computed result"),
    ],
)
def test_descriptions_are_plain_language(sql: str, dialect: str, expected: str) -> None:
    assert expected in describe(sql, dialect)


def test_a_write_is_described_and_flagged_not_run() -> None:
    text = describe("DELETE FROM orders WHERE status = 'cancelled'", "postgresql")
    assert "where status = 'cancelled'" in text and "SQLAgent will not run it" in text
    assert analyze("", "postgresql").statement in ("empty", "unparsed")


def test_generate_prompt_carries_the_real_schema_dialect_date_and_history() -> None:
    msgs = generate_messages(
        dialect="mysql",
        tables=[ORDERS, CUSTOMERS],
        question="and last year?",
        history=[Turn("How many orders this year?", "SELECT COUNT(*) FROM orders", "One number.")],
        max_schema_chars=10_000,
        today=dt.date(2026, 6, 15),
        connection_note="The online store",
    )
    system = msgs[0].content
    assert system.startswith("TASK: generate\nDialect: mysql\nToday: 2026-06-15")
    assert "About this database: The online store" in system
    assert "- public.orders (table, ~6000 rows)" in system
    assert "    customer_id integer -> public.customers.id" in system
    assert "    status varchar(20) values: delivered, shipped" in system
    assert [m.role for m in msgs] == ["system", "user", "assistant", "user"]
    assert json.loads(msgs[2].content)["sql"] == "SELECT COUNT(*) FROM orders"
    assert msgs[-1].content == "Question: and last year?"
    explain = explain_messages(dialect="sqlite", sql="SELECT 1;")
    assert (
        explain[0].content.startswith("TASK: explain")
        and "```sql\nSELECT 1;\n```" in explain[1].content
    )


@pytest.mark.parametrize(
    ("text", "sql", "explanation"),
    [
        ('{"sql": "SELECT 1", "explanation": "One."}', "SELECT 1", "One."),
        ('Sure!\n```json\n{"sql": "SELECT 2", "explanation": "Two"}\n```', "SELECT 2", "Two"),
        ('Here: {"sql": "SELECT 3", "explanation": "x"} done', "SELECT 3", "x"),
        ("```sql\nSELECT 4 FROM t\n```\nThis counts.", "SELECT 4 FROM t", "This counts."),
        ("SELECT 5", "SELECT 5", ""),
        ('{"sql": null, "explanation": "No such table."}', None, "No such table."),
        ("I cannot help with that.", None, "I cannot help with that."),
        ('{"sql": "   ", "explanation": "blank"}', None, "blank"),
    ],
)
def test_answers_are_read_back_whatever_shape_the_model_used(
    text: str, sql: str | None, explanation: str
) -> None:
    answer = parse_answer(text)
    assert answer.sql == sql and answer.explanation == explanation


def test_explanations_are_read_back() -> None:
    assert parse_explanation('{"explanation": "Counts orders."}') == "Counts orders."
    assert parse_explanation("Plain words.") == "Plain words."
