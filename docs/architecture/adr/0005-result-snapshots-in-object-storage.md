# 0005: Results are snapshots in object storage

**Status:** accepted

**Context.** Pages, charts and CSV exports should not query the customer's database again,
and storing result rows in Postgres JSON would bloat the app database.

**Decision.** A successful query writes one JSON snapshot (columns and rows, at most the
row limit) to object storage; the execution row keeps its key. Pages and exports read the
snapshot, cached briefly in Redis.

**Consequences.** One query per execution against the customer's database; results are
replayable as they were; retention deletes snapshots with their executions.
