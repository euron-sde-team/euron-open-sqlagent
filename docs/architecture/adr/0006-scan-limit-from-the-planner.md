# 0006: The scan limit uses the planner's estimate

**Status:** accepted

**Context.** A timeout stops a long query but only after it has loaded the database.

**Decision.** Before running, ask the database's planner (`EXPLAIN` without `ANALYZE` on
PostgreSQL, `EXPLAIN` on MySQL, `EXPLAIN QUERY PLAN` with row counts of scanned tables on
SQLite) how many rows it expects to read, and refuse above the connection's
`max_scan_rows`. Sequential scans count the whole table.

**Consequences.** Obviously expensive queries never start. Estimates can be wrong; the
statement timeout remains the hard stop.
