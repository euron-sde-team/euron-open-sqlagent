"""The schema block: rendered from discovered tables, parsed back by the mock, and trimmed
to the most relevant tables when a schema is large."""

from __future__ import annotations

from sqlagent.schema.prompt import (
    HEADER,
    parse_block,
    relevance,
    render,
    render_table,
    select_tables,
    stem,
    stems,
)
from sqlagent.schema.schemas import SchemaColumn, SchemaForeignKey, SchemaTable


def table(
    name: str, cols: list[str], fks: dict[str, str] | None = None, schema: str | None = None
) -> SchemaTable:
    return SchemaTable(
        schema_name=schema,
        name=name,
        kind="table",
        row_count=10,
        columns=[
            SchemaColumn(name=c, type="integer" if c.endswith("id") else "text") for c in cols
        ],
        foreign_keys=[
            SchemaForeignKey(columns=[c], ref_table=ref, ref_columns=["id"])
            for c, ref in (fks or {}).items()
        ],
    )


def test_stems_make_plural_questions_match_singular_names() -> None:
    assert stem("orders") == "order" and stem("categories") == "category"
    assert stem("addresses") == "address" and stem("boss") == "boss"
    assert {"order", "orders", "per", "status"} <= stems("Orders per status?")


def test_render_and_parse_round_trip() -> None:
    tables = [
        table("customers", ["id", "name"], schema="public"),
        table(
            "orders", ["id", "customer_id", "note"], {"customer_id": "public.customers"}, "public"
        ),
        SchemaTable(
            name="monthly",
            kind="view",
            columns=[SchemaColumn(name="m", type="timestamp without time zone")],
        ),
    ]
    tables[1].columns[2].sample_values = ["a", "b"]
    block = render(tables, "", 10_000)
    assert block.startswith(HEADER)
    back = parse_block("TASK: generate\n\n" + block + "\n\nnot part of it")
    assert [t.qualified for t in back] == ["public.customers", "public.orders", "monthly"]
    orders = back[1]
    assert orders.foreign_keys[0].ref_table == "public.customers"
    assert orders.columns[2].sample_values == ["a", "b"]
    assert back[2].kind == "view" and back[2].row_count is None
    assert back[2].columns[0].type == "timestamp without time zone"
    assert parse_block("no schema here") == []


def test_large_schemas_keep_the_relevant_tables_and_their_references() -> None:
    tables = [table(f"noise_{i}", ["id", "a", "b", "c"]) for i in range(200)]
    tables.append(table("invoices", ["id", "account_id", "amount"], {"account_id": "accounts"}))
    tables.append(table("accounts", ["id", "company"]))
    full = sum(len(render_table(t)) for t in tables)
    chosen = select_tables(tables, "Total invoice amount per company", 600)
    names = [t.name for t in chosen]
    assert names[:2] == ["invoices", "accounts"]
    assert sum(len(render_table(t)) + 1 for t in chosen) <= 600 < full
    assert relevance(tables[-2], "invoice amount") > relevance(tables[0], "invoice amount")
    # Everything fits: everything is shown, in schema order.
    assert select_tables(tables[:3], "x", 100_000) == tables[:3]
