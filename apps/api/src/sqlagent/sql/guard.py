"""The SQL guard: a query runs only if it is exactly one read-only ``SELECT``.

Every query SQLAgent executes, whether a model generated it or a person pasted it, is
parsed with sqlglot in the connection's dialect and accepted only when it is a single
statement whose root is a query (``SELECT``, ``UNION``, ``INTERSECT``, ``EXCEPT``, with or
without CTEs) and nothing anywhere in its tree writes, locks rows, changes session state,
reads files or calls a function known to have side effects.

This is the first of two locks. The second is the connection itself, opened read-only by
the database wherever the database supports it (``connections/sources.py``), so a query
that slipped past this parser still cannot write.

The design follows Euron Open DataQuality's ``engine/sqlguard.py``, narrowed to the three
dialects SQLAgent connects to and extended with a structured verdict (the tables a query
reads, its normalized text) that the API shows next to every query.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

# sqlglot logs a warning for every statement it falls back to parsing as a raw command;
# the guard refuses those anyway, so the warning is noise.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

DIALECTS = ("postgresql", "mysql", "sqlite")
SQLGLOT_DIALECT = {"postgresql": "postgres", "mysql": "mysql", "sqlite": "sqlite"}
MAX_SQL_CHARS = 100_000

# Functions with side effects, sleeps, file or network access, or session changes.
DENIED_FUNCTIONS: dict[str, frozenset[str]] = {
    "postgresql": frozenset(
        {
            "pg_sleep",
            "pg_sleep_for",
            "pg_sleep_until",
            "pg_read_file",
            "pg_read_binary_file",
            "pg_ls_dir",
            "pg_ls_logdir",
            "pg_ls_waldir",
            "pg_stat_file",
            "pg_terminate_backend",
            "pg_cancel_backend",
            "pg_reload_conf",
            "pg_rotate_logfile",
            "pg_promote",
            "pg_switch_wal",
            "pg_create_restore_point",
            "pg_advisory_lock",
            "pg_advisory_xact_lock",
            "pg_try_advisory_lock",
            "pg_notify",
            "pg_logical_emit_message",
            "pg_import_system_collations",
            "lo_import",
            "lo_export",
            "lo_unlink",
            "lo_create",
            "lo_put",
            "dblink",
            "dblink_exec",
            "dblink_connect",
            "set_config",
            "nextval",
            "setval",
            "txid_current",
            "query_to_xml",
            "query_to_json",
            "table_to_xml",
            "cursor_to_xml",
        }
    ),
    "mysql": frozenset(
        {
            "sleep",
            "benchmark",
            "load_file",
            "get_lock",
            "release_lock",
            "release_all_locks",
            "is_free_lock",
            "master_pos_wait",
            "source_pos_wait",
            "sys_exec",
            "sys_eval",
            "uuid_short",
        }
    ),
    "sqlite": frozenset(
        {
            "load_extension",
            "writefile",
            "readfile",
            "edit",
            "fts3_tokenizer",
            "zeroblob",
        }
    ),
}
# A function on another dialect's list is refused everywhere too: the name gives away the
# intent even when this database would not know it.
_ALL_DENIED = frozenset().union(*DENIED_FUNCTIONS.values())

_ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Subquery)
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,
    exp.Into,
    exp.Lock,
    exp.Set,
    exp.Pragma,
    exp.Copy,
    exp.Use,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Grant,
    exp.Analyze,
    exp.LoadData,
)


# Roots that are real statements (refused as not a SELECT); any other root (a bare word
# read as an alias or column) means the text was not a statement at all.
_STATEMENT_KEYS = frozenset(
    {
        "insert",
        "update",
        "delete",
        "merge",
        "create",
        "drop",
        "alter",
        "truncatetable",
        "command",
        "copy",
        "pragma",
        "set",
        "use",
        "transaction",
        "commit",
        "rollback",
        "grant",
        "analyze",
        "loaddata",
        "describe",
        "show",
        "cache",
        "uncache",
        "refresh",
        "values",
    }
)


class UnsafeSqlError(ValueError):
    """The SQL is not a single read-only query. ``code`` says which rule refused it."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the guard learned about an accepted query."""

    sql: str
    dialect: str
    tables: list[str] = field(default_factory=list)
    # alias (lower case) -> table name, for reading query plans that name aliases.
    aliases: dict[str, str] = field(default_factory=dict)
    tree: exp.Expression | None = None


def parse(sql: str, dialect: str) -> list[exp.Expression]:
    if dialect not in SQLGLOT_DIALECT:
        raise UnsafeSqlError(f"unsupported dialect {dialect!r}", "unsupported_dialect")
    if len(sql) > MAX_SQL_CHARS:
        raise UnsafeSqlError(f"the query is longer than {MAX_SQL_CHARS:,} characters", "too_long")
    try:
        parsed = sqlglot.parse(sql, read=SQLGLOT_DIALECT[dialect])
        return [s for s in parsed if isinstance(s, exp.Expression)]
    except (ParseError, TokenError) as exc:
        first = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
        raise UnsafeSqlError(f"the query does not parse: {first}", "parse_error") from exc


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return str(node.sql_name()).lower()


def check(sql: str, dialect: str) -> Verdict:
    """Accept ``sql`` as one read-only query in ``dialect`` or raise UnsafeSqlError."""
    text = sql.strip().rstrip(";").strip()
    if not text:
        raise UnsafeSqlError("the query is empty", "empty")
    statements = parse(sql, dialect)
    if len(statements) != 1:
        raise UnsafeSqlError(
            f"exactly one statement is allowed, found {len(statements)}", "multiple_statements"
        )
    tree = statements[0]
    if not isinstance(tree, _ALLOWED_ROOTS):
        if tree.key not in _STATEMENT_KEYS:
            raise UnsafeSqlError("the text does not read as a SQL statement", "parse_error")
        raise UnsafeSqlError(f"only SELECT queries run, not {tree.key.upper()}", "not_a_select")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise UnsafeSqlError(
                f"{node.key.upper()} is not allowed in a read-only query", "write_or_admin"
            )
        if isinstance(node, exp.Func):
            name = _function_name(node)
            if name in _ALL_DENIED:
                raise UnsafeSqlError(f"the function {name} is not allowed", "denied_function")
        if isinstance(node, exp.Table) and isinstance(node.this, exp.Func | exp.Literal):
            raise UnsafeSqlError("table functions and file paths are not allowed", "table_function")
    return Verdict(
        sql=text,
        dialect=dialect,
        tables=referenced_tables(tree),
        aliases={
            str(t.alias).lower(): str(t.name)
            for t in tree.find_all(exp.Table)
            if t.alias and t.name
        },
        tree=tree,
    )


def referenced_tables(tree: exp.Expression) -> list[str]:
    """Tables the query reads, schema qualified when written so; CTE names excluded."""
    ctes = {str(c.alias_or_name).lower() for c in tree.find_all(exp.CTE)}
    seen: dict[str, None] = {}
    for t in tree.find_all(exp.Table):
        name = str(t.name)
        if not name or name.lower() in ctes:
            continue
        db = str(t.db) if t.db else ""
        seen[f"{db}.{name}" if db else name] = None
    return list(seen)


def is_read_only(sql: str, dialect: str) -> tuple[bool, str | None, str | None]:
    """``(ok, reason, code)`` without raising."""
    try:
        check(sql, dialect)
    except UnsafeSqlError as exc:
        return False, exc.message, exc.code
    return True, None, None
