# The SQL guard

`apps/api/src/sqlagent/sql/guard.py`. Every query SQLAgent runs passes through it first,
whether a model wrote it, a person pasted it, or a template saved it. It is the first of two
locks; the second is the read-only session ([security.md](security.md)).

## What it accepts

Exactly one statement whose root is a query: `SELECT`, `UNION`, `INTERSECT`, `EXCEPT`,
with or without CTEs, joins, subqueries and window functions. A trailing semicolon is fine.

## What it refuses, and the code it reports

| Code | Refused |
| --- | --- |
| `empty` | Nothing but whitespace and semicolons |
| `too_long` | More than 100,000 characters |
| `parse_error` | Text sqlglot cannot parse in the connection's dialect, or that is not a statement |
| `multiple_statements` | More than one statement (`SELECT 1; DELETE ...`) |
| `not_a_select` | A statement that is not a query: `INSERT`, `UPDATE`, `DELETE`, `MERGE`, DDL, `TRUNCATE`, `GRANT`, `SET`, `COPY`, `PRAGMA`, `ATTACH`, transactions, `EXPLAIN ANALYZE ...` |
| `write_or_admin` | A write or lock anywhere in the tree: a data-modifying CTE (`WITH d AS (DELETE ... RETURNING *)`), `SELECT ... INTO`, `FOR UPDATE`, `LOCK IN SHARE MODE` |
| `denied_function` | A function with side effects, sleeps, file or network access in any supported dialect: `pg_sleep`, `pg_read_file`, `dblink`, `set_config`, `nextval`, `lo_import`, `sleep`, `benchmark`, `load_file`, `get_lock`, `load_extension`, `writefile` and more. A name on any dialect's list is refused on every dialect |
| `table_function` | A function or file path in `FROM` (`generate_series(...)`, `read_csv('...')`) |

The design comes from Euron Open DataQuality's `engine/sqlguard.py`, narrowed to the three
dialects SQLAgent connects to and extended with structured verdicts: the tables a query
reads and its aliases (used to read query plans).

## Where it runs

- `executions/service.execute`: before any connection is opened. A refusal writes a
  `refused` execution and a `query.refused` audit entry and increments
  `sqlagent_guard_refusals_total{code}`. The database is never contacted.
- `sql/service.generate`: the model's answer is checked so the response says whether it
  would run.
- `templates/service`: a template's saved SQL is checked when saved.
- `sql/describe.analyze`: an explanation reports the verdict next to the description.

## Tests

`tests/unit/sql/test_guard.py` (66 cases over the three dialects) and
`tests/integration/test_safety.py` (eleven writes sent through the API with a login that
could write: every one refused and the row count unchanged).
