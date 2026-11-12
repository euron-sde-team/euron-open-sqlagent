"""What a query does, read from its syntax tree: the structured facts the API returns with
every explanation, and a plain-language description built from them.

This never executes anything. The facts come from sqlglot's parse of the text in the
connection's dialect; a model's explanation is shown next to them, so a person can check
the model's words against what the query really says.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlglot import exp

from sqlagent.sql import guard

_AGGREGATES = (exp.Count, exp.Sum, exp.Avg, exp.Max, exp.Min)
_VERB = {
    "insert": "inserts rows into",
    "update": "changes rows in",
    "delete": "deletes rows from",
    "drop": "drops",
    "create": "creates",
    "alter": "alters",
    "truncatetable": "empties",
    "merge": "merges rows into",
}


@dataclass
class Analysis:
    statement: str
    read_only: bool
    refusal: str | None = None
    refusal_code: str | None = None
    tables: list[str] = field(default_factory=list)
    joins: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    group_by: list[str] = field(default_factory=list)
    aggregates: list[str] = field(default_factory=list)
    order_by: list[str] = field(default_factory=list)
    limit: int | None = None
    ctes: list[str] = field(default_factory=list)
    window_functions: int = 0
    subqueries: int = 0
    columns: list[str] = field(default_factory=list)


def _sql(node: exp.Expression, dialect: str) -> str:
    return str(node.sql(dialect=guard.SQLGLOT_DIALECT.get(dialect, dialect)))


def _split_and(node: exp.Expression) -> list[exp.Expression]:
    if isinstance(node, exp.And):
        left, right = node.left, node.right
        out: list[exp.Expression] = []
        for side in (left, right):
            out += _split_and(side) if isinstance(side, exp.Expression) else []
        return out
    return [node]


def analyze(sql: str, dialect: str) -> Analysis:
    """Facts about ``sql``; a statement that does not parse gets ``statement="unparsed"``."""
    ok, reason, code = guard.is_read_only(sql, dialect)
    try:
        statements = guard.parse(sql, dialect)
    except guard.UnsafeSqlError as exc:
        return Analysis(
            statement="unparsed", read_only=False, refusal=exc.message, refusal_code=exc.code
        )
    if not statements:
        return Analysis(statement="empty", read_only=False, refusal=reason, refusal_code=code)
    tree = statements[0]
    a = Analysis(
        statement=tree.key.lower(),
        read_only=ok,
        refusal=reason,
        refusal_code=code,
        tables=guard.referenced_tables(tree),
    )
    a.ctes = [str(c.alias_or_name) for c in tree.find_all(exp.CTE)]
    a.window_functions = sum(1 for _ in tree.find_all(exp.Window))
    a.subqueries = sum(1 for _ in tree.find_all(exp.Subquery))
    select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    if select is None:
        return a
    for j in select.args.get("joins") or []:
        kind = " ".join(str(p) for p in (j.side, j.kind) if p).lower() or "inner"
        on = j.args.get("on")
        target = _sql(j.this, dialect)
        a.joins.append(f"{kind} join {target}" + (f" on {_sql(on, dialect)}" if on else ""))
    where = select.args.get("where")
    if where is not None:
        a.filters = [_sql(c, dialect) for c in _split_and(where.this)]
    having = select.args.get("having")
    if having is not None:
        a.filters += [f"(after grouping) {_sql(c, dialect)}" for c in _split_and(having.this)]
    group = select.args.get("group")
    if group is not None:
        a.group_by = [_sql(g, dialect) for g in group.expressions]
    for proj in select.expressions:
        a.columns.append(str(proj.alias_or_name) or _sql(proj, dialect))
        for agg in proj.find_all(*_AGGREGATES):
            a.aggregates.append(_sql(agg, dialect))
    order = tree.args.get("order") or select.args.get("order")
    if order is not None:
        for o in order.expressions:
            direction = "descending" if o.args.get("desc") else "ascending"
            a.order_by.append(f"{_sql(o.this, dialect)} {direction}")
    limit = tree.args.get("limit") or select.args.get("limit")
    if limit is not None:
        try:
            a.limit = int(limit.expression.this) if limit.expression else None
        except (TypeError, ValueError, AttributeError):
            a.limit = None
    return a


def tree_where(sql: str, dialect: str) -> list[str]:
    try:
        tree = guard.parse(sql, dialect)[0]
    except (guard.UnsafeSqlError, IndexError):
        return []
    where = tree.args.get("where")
    return [_sql(c, dialect) for c in _split_and(where.this)] if where is not None else []


def _list(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def describe(sql: str, dialect: str) -> str:
    """A plain-language description of ``sql`` from its syntax tree."""
    a = analyze(sql, dialect)
    if a.statement in ("unparsed", "empty") or a.refusal_code == "parse_error":
        return f"This text is not a query SQLAgent can read: {a.refusal}."
    if not a.read_only and a.statement in _VERB:
        target = _list(a.tables) or "a table"
        text = f"This statement {_VERB[a.statement]} {target}"
        where = tree_where(sql, dialect)
        if where:
            text += " where " + " and ".join(where)
        return text + f". SQLAgent will not run it: {a.refusal}."
    parts: list[str] = []
    if a.ctes:
        parts.append(f"First it builds the intermediate result {_list(a.ctes)}.")
    source = _list([t for t in a.tables if t not in a.ctes]) or "a computed result"
    sentence = f"It reads {source}"
    if a.joins:
        sentence += ", combining rows with " + _list(a.joins)
    parts.append(sentence + ".")
    if a.filters:
        parts.append("It keeps only rows where " + " and ".join(a.filters) + ".")
    if a.group_by:
        parts.append("It groups the rows by " + _list(a.group_by) + ".")
    if a.aggregates:
        parts.append("It computes " + _list(sorted(set(a.aggregates))) + ".")
    elif a.columns:
        shown = a.columns if len(a.columns) <= 6 else [*a.columns[:6], "more"]
        parts.append("It returns the columns " + _list(shown) + ".")
    if a.window_functions:
        parts.append(f"It uses {a.window_functions} window function(s) over the rows.")
    if a.order_by:
        parts.append("The result is sorted by " + _list(a.order_by) + ".")
    if a.limit is not None:
        parts.append(f"It returns at most {a.limit} rows.")
    if not a.read_only:
        parts.append(f"SQLAgent will not run it: {a.refusal}.")
    return " ".join(parts)
