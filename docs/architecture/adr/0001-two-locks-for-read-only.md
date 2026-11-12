# 0001: Read-only is enforced twice

**Status:** accepted

**Context.** A model writes the SQL, and a model can be talked into writing a write. A
parser can have a bug. A login can have more rights than it should.

**Decision.** Every query must pass the SQL guard (one read-only `SELECT`, parsed per
dialect) and then run on a session the database itself holds read-only (PostgreSQL
`default_transaction_read_only`, MySQL `SET SESSION TRANSACTION READ ONLY`, SQLite
`mode=ro` and `query_only`), always rolled back.

**Consequences.** Validation is never the only thing between a question and a write; each
lock is tested on its own. Databases without a read-only session mode would need a
read-only login to keep the second lock, which is why 0.1.0 supports these three.
