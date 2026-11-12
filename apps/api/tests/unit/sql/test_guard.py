"""The SQL guard, per dialect (A3): exactly one read-only query or a refusal with a reason."""

from __future__ import annotations

import pytest

from sqlagent.sql.guard import DIALECTS, UnsafeSqlError, check, is_read_only, parse

READ_ONLY = {
    "postgresql": [
        "SELECT 1",
        "select * from orders",
        "SELECT o.id FROM public.orders o JOIN public.customers c ON c.id = o.customer_id",
        "WITH recent AS (SELECT * FROM orders WHERE order_date > now() - interval '30 days') "
        "SELECT count(*) FROM recent",
        "SELECT status, count(*) FROM orders GROUP BY status HAVING count(*) > 10",
        "SELECT id, rank() OVER (PARTITION BY customer_id ORDER BY total_amount DESC) FROM orders",
        "SELECT date_trunc('month', order_date)::date AS m, sum(total_amount) FROM orders GROUP BY 1",
        "SELECT a FROM t UNION SELECT b FROM u",
        "SELECT a FROM t INTERSECT SELECT b FROM u",
        "SELECT * FROM (SELECT id FROM orders) s WHERE id IN (SELECT order_id FROM order_items)",
        "SELECT 1;",
        "  SELECT 1  ;  ",
    ],
    "mysql": [
        "SELECT DATE_FORMAT(hire_date, '%Y-%m') AS m, COUNT(*) FROM employees GROUP BY m",
        "SELECT `first_name` FROM `employees` LIMIT 10",
        "SELECT YEAR(hire_date), AVG(salary) FROM employees GROUP BY YEAR(hire_date)",
        "WITH d AS (SELECT * FROM departments) SELECT name FROM d",
    ],
    "sqlite": [
        "SELECT strftime('%Y-%m', issued_on) AS month, sum(amount) FROM invoices GROUP BY 1",
        "SELECT * FROM accounts WHERE status = 'active' LIMIT 5",
        "SELECT p.name, count(*) FROM accounts a JOIN plans p ON p.id = a.plan_id GROUP BY 1",
    ],
}

REFUSED = {
    "postgresql": [
        ("DELETE FROM orders", "not_a_select"),
        ("UPDATE orders SET total_amount = 0", "not_a_select"),
        ("INSERT INTO orders VALUES (1)", "not_a_select"),
        ("DROP TABLE orders", "not_a_select"),
        ("CREATE TABLE x (id int)", "not_a_select"),
        ("ALTER TABLE orders ADD COLUMN x int", "not_a_select"),
        ("TRUNCATE orders", "not_a_select"),
        ("GRANT SELECT ON orders TO public", "not_a_select"),
        ("SET ROLE postgres", "not_a_select"),
        ("COPY orders TO '/tmp/x'", "not_a_select"),
        ("EXPLAIN ANALYZE DELETE FROM orders", "not_a_select"),
        ("BEGIN", "not_a_select"),
        ("SELECT 1; SELECT 2", "multiple_statements"),
        ("SELECT 1; DROP TABLE orders", "multiple_statements"),
        ("SELECT pg_sleep(10)", "denied_function"),
        ("SELECT pg_read_file('/etc/passwd')", "denied_function"),
        ("SELECT pg_terminate_backend(123)", "denied_function"),
        ("SELECT set_config('x', 'y', false)", "denied_function"),
        ("SELECT nextval('orders_id_seq')", "denied_function"),
        ("SELECT * FROM dblink('host=x', 'select 1') AS t(a int)", "table_function"),
        ("SELECT lo_import('/etc/passwd')", "denied_function"),
        ("SELECT * INTO copy_of_orders FROM orders", "write_or_admin"),
        ("SELECT * FROM orders FOR UPDATE", "write_or_admin"),
        ("WITH gone AS (DELETE FROM orders RETURNING *) SELECT * FROM gone", "write_or_admin"),
        ("WITH x AS (UPDATE orders SET total_amount = 0 RETURNING id) SELECT 1", "write_or_admin"),
        ("SELECT * FROM generate_series(1, 1000000000)", "table_function"),
        ("SELEC * FROM orders", "parse_error"),
        ("", "empty"),
        ("   ;  ", "empty"),
    ],
    "mysql": [
        ("SELECT SLEEP(5)", "denied_function"),
        ("SELECT BENCHMARK(1000000, MD5('x'))", "denied_function"),
        ("SELECT LOAD_FILE('/etc/passwd')", "denied_function"),
        ("SELECT GET_LOCK('x', 10)", "denied_function"),
        ("DELETE FROM employees", "not_a_select"),
        ("REPLACE INTO employees VALUES (1)", "not_a_select"),
        ("SELECT * FROM employees FOR UPDATE", "write_or_admin"),
        ("SELECT * FROM employees LOCK IN SHARE MODE", "write_or_admin"),
        ("SELECT 1; SELECT 2", "multiple_statements"),
    ],
    "sqlite": [
        ("SELECT load_extension('evil')", "denied_function"),
        ("SELECT writefile('/tmp/x', 'y')", "denied_function"),
        ("PRAGMA writable_schema = 1", "not_a_select"),
        ("ATTACH DATABASE '/tmp/x.db' AS x", "not_a_select"),
        ("VACUUM", "not_a_select"),
        ("DELETE FROM invoices", "not_a_select"),
    ],
}


@pytest.mark.parametrize(
    ("dialect", "sql"), [(d, s) for d, items in READ_ONLY.items() for s in items]
)
def test_read_only_queries_are_accepted(dialect: str, sql: str) -> None:
    verdict = check(sql, dialect)
    assert verdict.dialect == dialect
    assert not verdict.sql.endswith(";")


@pytest.mark.parametrize(
    ("dialect", "sql", "code"),
    [(d, s, c) for d, items in REFUSED.items() for s, c in items],
)
def test_writes_admin_statements_and_side_effects_are_refused(
    dialect: str, sql: str, code: str
) -> None:
    with pytest.raises(UnsafeSqlError) as caught:
        check(sql, dialect)
    assert caught.value.code == code, caught.value.message
    ok, reason, got = is_read_only(sql, dialect)
    assert ok is False and reason and got == code


def test_a_function_denied_in_any_dialect_is_denied_in_every_dialect() -> None:
    for dialect in DIALECTS:
        with pytest.raises(UnsafeSqlError):
            check("SELECT pg_sleep(1)", dialect)


def test_tables_and_aliases_are_reported() -> None:
    v = check(
        "WITH recent AS (SELECT * FROM public.orders) "
        "SELECT c.name FROM recent r JOIN customers AS c ON c.id = r.customer_id",
        "postgresql",
    )
    assert sorted(v.tables) == ["customers", "public.orders"]
    assert v.aliases == {"r": "recent", "c": "customers"}
    assert is_read_only("SELECT 1", "sqlite") == (True, None, None)


def test_unknown_dialects_and_huge_queries_are_refused() -> None:
    with pytest.raises(UnsafeSqlError) as caught:
        parse("SELECT 1", "oracle")
    assert caught.value.code == "unsupported_dialect"
    with pytest.raises(UnsafeSqlError) as caught:
        check("SELECT " + "1 + " * 30_000 + "1", "postgresql")
    assert caught.value.code == "too_long"
