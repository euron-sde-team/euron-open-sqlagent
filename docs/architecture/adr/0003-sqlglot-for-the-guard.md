# 0003: The guard parses with sqlglot

**Status:** accepted

**Context.** Keyword matching misses `WITH d AS (DELETE ...)`, `SELECT ... INTO`, comments
and dialect quirks, and refuses harmless text that mentions a keyword.

**Decision.** Parse with sqlglot in the connection's dialect and walk the tree: one
statement, a query root, no write or lock nodes, no denied functions, no table functions.

**Consequences.** Decisions are structural and testable per dialect. Text sqlglot cannot
parse is refused (`parse_error`), which errs on the safe side.
