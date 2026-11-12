"""A deterministic text-to-SQL planner: the brain of the ``mock`` model provider.

It reads the schema block of the prompt (``schema.prompt.parse_block``) and turns a
question into SQL with fixed rules, so tests, the demo and the e2e suite get the same
answer every time without any model or network. It understands what the demo and the
tests ask: counts, sums, averages, minimums and maximums of a column; grouping by a column,
by a related table (through foreign keys) or by a time grain; calendar filters ("in 2025",
"last year", "this month", "last 30 days"); filters on sampled values ("shipped orders");
top and bottom N; listings; and follow-up questions that change only part of the previous
one ("and last year?", "break it down by country", "only the cancelled ones").

It is a test fixture with good manners, not a language model: a question it cannot map to
the schema gets an honest "I could not answer" instead of a guess. And like a real model it
can be talked into writing a destructive statement ("delete the cancelled orders"), which
is exactly what the SQL guard exists to refuse.
"""

from __future__ import annotations

import copy
import datetime as dt
import re
from dataclasses import dataclass, field

from sqlagent.schema.prompt import stem, stems, words
from sqlagent.schema.schemas import SchemaColumn, SchemaTable

NUMERIC = ("int", "numeric", "decimal", "float", "double", "real", "money", "number")
TEMPORAL = ("date", "time")
GRAINS = {
    "day": "day",
    "daily": "day",
    "week": "week",
    "weekly": "week",
    "month": "month",
    "monthly": "month",
    "quarter": "quarter",
    "quarterly": "quarter",
    "year": "year",
    "yearly": "year",
    "annual": "year",
    "annually": "year",
}
MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ]
    )
}
SUM_WORDS = {"total", "sum", "revenue", "sales", "spend", "spent", "spending", "income", "sold"}
AVG_WORDS = {"average", "avg", "mean", "typical"}
MAX_WORDS = {"highest", "maximum", "max", "largest", "biggest", "expensive"}
MIN_WORDS = {"lowest", "minimum", "min", "smallest", "cheapest"}
COUNT_PHRASES = ("how many", "number of", "count of", "count the", "count ")
MONEY_WORDS = {"revenue", "sales", "spend", "spent", "spending", "income", "sold", "value"}
MONEY_COLUMNS = ("total_amount", "amount", "line_total", "revenue", "total", "price", "value")
LABEL_COLUMNS = ("name", "title", "full_name", "label", "company", "email", "code")
FOLLOW_UP_CUES = (
    "and ",
    "what about",
    "how about",
    "now ",
    "only ",
    "same ",
    "instead",
    "break it down",
    "break that down",
    "split it",
    "split that",
    "compare",
    "and?",
    "those",
    "them",
    "that",
)


@dataclass
class Ref:
    table: SchemaTable
    column: SchemaColumn

    @property
    def key(self) -> tuple[str, str]:
        return self.table.qualified, self.column.name


def mentions(t: SchemaTable, qw: set[str]) -> bool:
    parts = {stem(p) for p in words(t.name)}
    return bool(parts) and (parts <= qw or t.name.lower() in qw)


@dataclass
class Intent:
    table: SchemaTable
    label: str | None = None
    metric: str = "count"  # count, sum, avg, max, min, list
    metric_ref: Ref | None = None
    group: Ref | None = None
    grain: str | None = None
    date_ref: Ref | None = None
    start: dt.date | None = None
    end: dt.date | None = None
    filters: list[tuple[Ref, str]] = field(default_factory=list)
    order: str | None = None  # desc or asc
    order_by_date: bool = False
    limit: int | None = None


@dataclass
class Plan:
    sql: str | None
    note: str


class CannotAnswerError(Exception):
    pass


# ─── Schema helpers ──────────────────────────────────────────────────────────


def is_numeric(c: SchemaColumn) -> bool:
    t = c.type.lower()
    return any(n in t for n in NUMERIC) and not any(x in t for x in ("interval", "point"))


def is_temporal(c: SchemaColumn) -> bool:
    t = c.type.lower()
    return any(n in t for n in TEMPORAL) and "zone" not in c.name.lower()


def is_key(t: SchemaTable, c: SchemaColumn) -> bool:
    fk_cols = {col for fk in t.foreign_keys for col in fk.columns}
    return c.primary_key or c.name in fk_cols or c.name == "id" or c.name.endswith("_id")


def label_of(t: SchemaTable) -> SchemaColumn:
    names = {c.name.lower(): c for c in t.columns}
    for want in LABEL_COLUMNS:
        if want in names:
            return names[want]
    for c in t.columns:
        if not is_numeric(c) and not is_temporal(c) and not is_key(t, c):
            return c
    return t.columns[0]


def date_of(t: SchemaTable) -> SchemaColumn | None:
    temporal = [c for c in t.columns if is_temporal(c)]
    for hint in ("order_date", "date", "created", "issued", "hire", "at", "on"):
        for c in temporal:
            if hint in c.name.lower():
                return c
    return temporal[0] if temporal else None


class Graph:
    """Many-to-one paths along foreign keys: from a fact table to the tables it points at."""

    def __init__(self, tables: list[SchemaTable]) -> None:
        self.tables = tables
        self.by_name = {t.qualified: t for t in tables}
        for t in tables:
            self.by_name.setdefault(t.name, t)

    def find(self, word: str) -> SchemaTable | None:
        s = stem(word)
        for t in self.tables:
            if stem(t.name.lower()) == s or t.name.lower() == word:
                return t
        # A multi-word table named by its last word: "requests" for leave_requests.
        for t in self.tables:
            parts = [stem(p) for p in words(t.name)]
            if len(parts) > 1 and parts[-1] == s and t.kind == "table":
                return t
        return None

    def path(
        self, src: SchemaTable, dst: SchemaTable, depth: int = 2
    ) -> list[tuple[SchemaTable, str, SchemaTable, str]] | None:
        """Join steps ``(from, from_col, to, to_col)`` from ``src`` to ``dst``."""
        if src.qualified == dst.qualified:
            return []
        if depth == 0:
            return None
        best: list[tuple[SchemaTable, str, SchemaTable, str]] | None = None
        for fk in src.foreign_keys:
            nxt = self.by_name.get(fk.ref_table) or self.by_name.get(fk.ref_table.split(".")[-1])
            if nxt is None or len(fk.columns) != 1:
                continue
            rest = self.path(nxt, dst, depth - 1)
            if rest is not None:
                cand = [(src, fk.columns[0], nxt, fk.ref_columns[0]), *rest]
                if best is None or len(cand) < len(best):
                    best = cand
        return best


# ─── Question parsing ────────────────────────────────────────────────────────


def _has_word(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase.lower())}(?![a-z0-9])", text) is not None


def _column_refs(g: Graph, text_words: set[str]) -> list[Ref]:
    out: list[Ref] = []
    for t in g.tables:
        for c in t.columns:
            parts = {stem(p) for p in words(c.name)}
            if c.name.lower() in text_words or (parts and parts <= text_words):
                out.append(Ref(t, c))
    return out


def _time_filter(q: str, today: dt.date) -> tuple[dt.date | None, dt.date | None] | None:
    """Calendar ranges the question names, relative to ``today``."""
    year = today.year
    if m := re.search(r"\b(?:in|during|for|of)\s+(" + "|".join(MONTHS) + r")(?:\s+(\d{4}))?", q):
        y = int(m[2]) if m[2] else year
        start = dt.date(y, MONTHS[m[1]], 1)
        end = dt.date(y + (start.month == 12), start.month % 12 + 1, 1)
        return start, end
    if m := re.search(r"\bsince\s+(\d{4})\b", q):
        return dt.date(int(m[1]), 1, 1), None
    if m := re.search(r"\b(?:in|during|for|of|from)\s+(\d{4})\b", q) or re.search(
        r"\b(20\d\d|19\d\d)\b", q
    ):
        y = int(m[1])
        return dt.date(y, 1, 1), dt.date(y + 1, 1, 1)
    if m := re.search(r"\b(?:last|past|previous)\s+(\d+)\s+days?\b", q):
        return today - dt.timedelta(days=int(m[1])), today + dt.timedelta(days=1)
    if "last year" in q or "previous year" in q or "a year ago" in q:
        return dt.date(year - 1, 1, 1), dt.date(year, 1, 1)
    if "this year" in q or "year to date" in q or "ytd" in words(q):
        return dt.date(year, 1, 1), today + dt.timedelta(days=1)
    first = today.replace(day=1)
    if "last month" in q or "previous month" in q:
        prev_end = first
        prev_start = (first - dt.timedelta(days=1)).replace(day=1)
        return prev_start, prev_end
    if "this month" in q:
        return first, today + dt.timedelta(days=1)
    return None


def _limit(q: str) -> tuple[str | None, int | None]:
    if m := re.search(r"\b(?:top|best|first|largest|biggest|highest)\s+(\d+)\b", q):
        return "desc", int(m[1])
    if m := re.search(r"\b(?:bottom|worst|lowest|smallest|last)\s+(\d+)\b(?!\s+days?)", q):
        return "asc", int(m[1])
    if re.search(r"\b(?:which|what)\b.*\b(?:most|highest|largest|biggest|best)\b", q):
        return "desc", 1
    if re.search(r"\b(?:which|what)\b.*\b(?:least|fewest|lowest|smallest|worst)\b", q):
        return "asc", 1
    if re.search(r"\btop\b", q):
        return "desc", 10
    return None, None


def _value_filters(g: Graph, q: str) -> list[tuple[Ref, str]]:
    out: list[tuple[Ref, str]] = []
    for t in g.tables:
        for c in t.columns:
            for v in c.sample_values:
                if (
                    len(v) > 2
                    and _has_word(q, v.lower())
                    and not any(r.key == (t.qualified, c.name) for r, _ in out)
                ):
                    out.append((Ref(t, c), v))
    return out


def _metric(q: str, qw: set[str]) -> str | None:
    if any(p in q for p in COUNT_PHRASES):
        return "count"
    if qw & AVG_WORDS:
        return "avg"
    if qw & SUM_WORDS:
        return "sum"
    if qw & MAX_WORDS and not re.search(r"\b(?:which|what|top)\b", q):
        return "max"
    if qw & MIN_WORDS and not re.search(r"\b(?:which|what|bottom)\b", q):
        return "min"
    if re.search(r"\b(?:list|show|display|give me|latest|recent|newest|oldest)\b", q):
        return "list"
    return None


def _group_words(q: str) -> list[str]:
    """The words after "by", "per", "each" or "for each" (two at most)."""
    found: list[str] = []
    for m in re.finditer(
        r"\b(?:by|per|each|for each|across|grouped by)\s+([a-z_]+)(?:\s+([a-z_]+))?", q
    ):
        found.append(" ".join(p for p in (m[1], m[2]) if p))
    return found


def _grain(q: str, qw: set[str]) -> str | None:
    for gw in _group_words(q):
        first = gw.split()[0]
        if first in GRAINS:
            return GRAINS[first]
    for w in ("monthly", "weekly", "daily", "quarterly", "yearly", "annual", "annually"):
        if w in qw:
            return GRAINS[w]
    if re.search(r"\b(?:over time|trend|each month|every month)\b", q):
        return "month"
    return None


def _money_rank(c: SchemaColumn) -> int:
    name = c.name.lower()
    for i, want in enumerate(MONEY_COLUMNS):
        if name == want or name.endswith(want):
            return i
    return len(MONEY_COLUMNS)


def _numeric_candidates(g: Graph, qw: set[str]) -> list[Ref]:
    """Numeric columns the question may mean, best first: a column it names, then the most
    transactional money column (an amount before a list price), a table it names before
    others, tables before views."""
    plain = qw - set(GRAINS)
    # A column named like a table ("orders" in a view) is the table being mentioned.
    table_words = {stem(p) for t in g.tables for p in words(t.name)}
    ranked: list[tuple[tuple[int, int, int, int], Ref]] = []
    for t in g.tables:
        in_named_table = mentions(t, plain)
        for c in t.columns:
            if not is_numeric(c) or is_key(t, c):
                continue
            parts = {stem(p) for p in words(c.name)} - {stem(p) for p in words(t.name)}
            named = bool(parts & plain) and not parts <= table_words
            money = bool(plain & MONEY_WORDS) and _money_rank(c) < len(MONEY_COLUMNS)
            if not named and not money:
                continue
            ranked.append(
                (
                    (
                        0 if named else 1,
                        _money_rank(c) if money else len(MONEY_COLUMNS),
                        0 if in_named_table else 1,
                        1 if t.kind == "view" else 0,
                    ),
                    Ref(t, c),
                )
            )
    ranked.sort(key=lambda x: x[0])
    return [r for _, r in ranked]


def _resolve_group(g: Graph, gw: str, main: SchemaTable | None) -> Ref | None:
    parts = gw.split()
    # "product category": a table, then one of its columns.
    if len(parts) == 2 and (t := g.find(parts[0])):
        for c in t.columns:
            if stem(c.name.lower()) == stem(parts[1]):
                return Ref(t, c)
    for word in (gw.replace(" ", "_"), parts[0]):
        # A column of the main table, then of any table.
        tables = ([main] if main else []) + [t for t in g.tables if main is None or t is not main]
        for t in tables:
            for c in t.columns:
                if c.name.lower() == word or stem(c.name.lower()) == stem(word):
                    return Ref(t, c)
        if t2 := g.find(word):
            return Ref(t2, label_of(t2))
    return None


def parse(g: Graph, question: str, today: dt.date, previous: Intent | None) -> Intent:
    q = " ".join(question.lower().replace("?", " ").replace(",", " ").split())
    qw = stems(q)
    mentioned = [t for t in g.tables if mentions(t, qw)]
    metric = _metric(q, qw)
    grain = _grain(q, qw)
    time = _time_filter(q, today)
    order, limit = _limit(q)
    values = _value_filters(g, q)
    group_words = [gw for gw in _group_words(q) if gw.split()[0] not in GRAINS]
    top_entity: SchemaTable | None = None
    if m := re.search(r"\b(?:top|bottom|best|worst)\s+(?:\d+\s+)?([a-z_]+)", q):
        top_entity = g.find(m[1])
    if m := re.search(r"\b(?:which|what)\s+([a-z_]+)", q):
        top_entity = top_entity or g.find(m[1])
        if top_entity is None and m[1] not in ("is", "are", "was", "were", "the"):
            group_words = [m[1], *group_words]

    follow_up = previous is not None and (
        q.startswith(FOLLOW_UP_CUES)
        or any(cue in q for cue in (" instead", "break it down", "break that down", "same "))
        or (not mentioned and metric is None and not _numeric_candidates(g, qw))
    )
    if follow_up and previous is not None:
        intent = copy.deepcopy(previous)
        if metric and metric != "list":
            intent.metric = metric
            if metric == "count":
                intent.metric_ref = None
        if time is not None:
            intent.start, intent.end = time
            intent.date_ref = intent.date_ref or _date_ref(g, intent.table)
        if grain:
            intent.grain, intent.group = grain, None
            intent.date_ref = intent.date_ref or _date_ref(g, intent.table)
        for gw in group_words:
            if ref := _resolve_group(g, gw, intent.table):
                intent.group, intent.grain = ref, None
                break
        if limit is not None:
            intent.order, intent.limit = order, limit
        for ref, value in _prefer(values, intent.table):
            intent.filters = [f for f in intent.filters if f[0].key != ref.key] + [(ref, value)]
        return intent

    # The metric column, then the main table.
    metric_ref: Ref | None = None
    if metric in ("sum", "avg", "max", "min") or (metric is None and qw & MONEY_WORDS):
        metric = metric or "sum"
        cands = _numeric_candidates(g, qw)
        group_target = top_entity or (
            _resolve_group(g, group_words[0], None).table  # type: ignore[union-attr]
            if group_words and _resolve_group(g, group_words[0], None)
            else None
        )
        if group_target is not None:
            reachable = [r for r in cands if g.path(r.table, group_target) is not None]
            cands = reachable or cands
        if cands:
            metric_ref = cands[0]
    if metric_ref is not None:
        main = metric_ref.table
    else:
        facts = [t for t in mentioned if t is not top_entity] or mentioned
        if not facts and values:
            facts = [values[0][0].table]
        if not facts:
            raise CannotAnswerError(question)
        # Count the table the others point at least: "orders per customer" counts orders.
        main = facts[0]
        if top_entity is not None and len(facts) > 1:
            linked = [t for t in facts if g.path(t, top_entity)]
            main = linked[0] if linked else main
        metric = metric or ("count" if (group_words or top_entity or grain) else "list")
        if metric in ("sum", "avg", "max", "min"):
            nums = [c for c in main.columns if is_numeric(c) and not is_key(main, c)]
            if not nums:
                metric = "count"
            else:
                metric_ref = Ref(main, nums[0])

    intent = Intent(table=main, metric=metric or "count", metric_ref=metric_ref)
    if top_entity is not None and top_entity is not main and metric != "list":
        intent.group = Ref(top_entity, label_of(top_entity))
    for gw in group_words:
        if ref := _resolve_group(g, gw, main):
            intent.group = ref
            break
    if grain:
        intent.grain = grain
        intent.date_ref = _date_ref(g, main)
    if time is not None:
        intent.start, intent.end = time
        intent.date_ref = intent.date_ref or _date_ref(g, main)
    if limit is not None:
        intent.order, intent.limit = order, limit
    if intent.metric == "list":
        if re.search(r"\b(?:latest|recent|newest)\b", q):
            intent.order, intent.order_by_date = "desc", True
            intent.date_ref = intent.date_ref or _date_ref(g, main)
        elif re.search(r"\boldest\b", q):
            intent.order, intent.order_by_date = "asc", True
            intent.date_ref = intent.date_ref or _date_ref(g, main)
        intent.limit = intent.limit or (int(m[1]) if (m := re.search(r"\b(\d+)\b", q)) else 50)
    intent.filters = _prefer(values, main)
    intent.label = _label(qw, intent)
    return intent


def _prefer(values: list[tuple[Ref, str]], main: SchemaTable) -> list[tuple[Ref, str]]:
    """One column per matched value: the main table's own column when it has one."""
    out: dict[str, tuple[Ref, str]] = {}
    for ref, value in values:
        kept = out.get(value.lower())
        if kept is None or (ref.table is main and kept[0].table is not main):
            out[value.lower()] = (ref, value)
    return list(out.values())


def _label(qw: set[str], intent: Intent) -> str | None:
    if intent.metric_ref is None or intent.metric not in ("sum", "avg"):
        return None
    for word in ("revenue", "sales", "spend", "income"):
        if word in qw:
            return word if intent.metric == "sum" else f"average_{word}"
    return None


def _date_ref(g: Graph, main: SchemaTable) -> Ref | None:
    if (c := date_of(main)) is not None:
        return Ref(main, c)
    for fk in main.foreign_keys:
        t = g.by_name.get(fk.ref_table) or g.by_name.get(fk.ref_table.split(".")[-1])
        if t is not None and (c := date_of(t)) is not None:
            return Ref(t, c)
    return None


# ─── SQL ─────────────────────────────────────────────────────────────────────


def quote(name: str, dialect: str) -> str:
    if re.fullmatch(r"[a-z_][a-z0-9_]*", name):
        return name
    return f"`{name}`" if dialect == "mysql" else f'"{name}"'


def qualified(t: SchemaTable, dialect: str) -> str:
    parts = [t.schema_name, t.name] if t.schema_name and dialect == "postgresql" else [t.name]
    return ".".join(quote(p, dialect) for p in parts if p)


def bucket(expr: str, grain: str, dialect: str) -> str:
    if dialect == "postgresql":
        return f"date_trunc('{grain}', {expr})::date"
    if dialect == "mysql":
        return {
            "day": f"DATE({expr})",
            "week": f"DATE_SUB(DATE({expr}), INTERVAL WEEKDAY({expr}) DAY)",
            "month": f"DATE_FORMAT({expr}, '%Y-%m-01')",
            "quarter": f"MAKEDATE(YEAR({expr}), 1) + INTERVAL QUARTER({expr}) - 1 QUARTER",
            "year": f"YEAR({expr})",
        }[grain]
    return {
        "day": f"date({expr})",
        "week": f"date({expr}, 'weekday 0', '-6 days')",
        "month": f"strftime('%Y-%m', {expr})",
        "quarter": (
            f"strftime('%Y', {expr}) || '-Q' || ((cast(strftime('%m', {expr}) AS integer) + 2) / 3)"
        ),
        "year": f"strftime('%Y', {expr})",
    }[grain]


def date_literal(d: dt.date, dialect: str) -> str:
    return f"DATE '{d.isoformat()}'" if dialect == "postgresql" else f"'{d.isoformat()}'"


def to_sql(g: Graph, intent: Intent, dialect: str) -> str:
    main = intent.table
    aliases: dict[str, str] = {main.qualified: "t0"}
    joins: list[str] = []

    def alias_for(t: SchemaTable) -> str:
        if t.qualified in aliases:
            return aliases[t.qualified]
        path = g.path(main, t)
        if path is None:
            raise CannotAnswerError(f"no path from {main.name} to {t.name}")
        for src, src_col, dst, dst_col in path:
            if dst.qualified in aliases:
                continue
            a = f"t{len(aliases)}"
            aliases[dst.qualified] = a
            joins.append(
                f"JOIN {qualified(dst, dialect)} {a} ON {a}.{quote(dst_col, dialect)} = "
                f"{aliases[src.qualified]}.{quote(src_col, dialect)}"
            )
        return aliases[t.qualified]

    def col(ref: Ref) -> str:
        return f"{alias_for(ref.table)}.{quote(ref.column.name, dialect)}"

    select: list[str] = []
    group: list[str] = []
    order: list[str] = []
    where: list[str] = []
    measure_name = "row_count"
    if intent.metric == "list":
        shown = list(main.columns)[:8]
        select = [f"t0.{quote(c.name, dialect)}" for c in shown]
        if intent.order_by_date and intent.date_ref is not None:
            order.append(
                f"{col(intent.date_ref)} {intent.order.upper() if intent.order else 'DESC'}"
            )
    else:
        if intent.grain and intent.date_ref is not None:
            expr = bucket(col(intent.date_ref), intent.grain, dialect)
            select.append(f"{expr} AS {intent.grain}")
            group.append(expr)
        elif intent.group is not None:
            gname = intent.group.column.name
            if gname in ("name", "title", "label") and intent.group.table is not main:
                gname = f"{stem(intent.group.table.name.lower())}_{gname}"
            select.append(f"{col(intent.group)} AS {quote(gname, dialect)}")
            group.append(col(intent.group))
        if intent.metric == "count" or intent.metric_ref is None:
            measure_name = f"{stem(main.name.lower())}_count"
            select.append(f"COUNT(*) AS {measure_name}")
        else:
            fn = intent.metric.upper()
            prefix = {"sum": "total", "avg": "average", "max": "max", "min": "min"}[intent.metric]
            column = intent.metric_ref.column.name
            measure_name = intent.label or (
                column if column.startswith(prefix) else f"{prefix}_{column}"
            )
            inner = col(intent.metric_ref)
            expr = f"{fn}({inner})"
            if intent.metric == "avg" or intent.metric == "sum":
                expr = f"ROUND({expr}, 2)"
            select.append(f"{expr} AS {measure_name}")
        if group:
            if intent.grain:
                order.append(f"{intent.grain} ASC")
            else:
                order.append(f"{measure_name} {(intent.order or 'desc').upper()}")
    if intent.date_ref is not None and intent.start is not None:
        where.append(f"{col(intent.date_ref)} >= {date_literal(intent.start, dialect)}")
    if intent.date_ref is not None and intent.end is not None:
        where.append(f"{col(intent.date_ref)} < {date_literal(intent.end, dialect)}")
    for ref, value in intent.filters:
        escaped = value.replace("'", "''")
        where.append(f"{col(ref)} = '{escaped}'")
    sql = f"SELECT {', '.join(select)}\nFROM {qualified(main, dialect)} t0"
    for j in joins:
        sql += f"\n{j}"
    if where:
        sql += "\nWHERE " + "\n  AND ".join(where)
    if group:
        sql += "\nGROUP BY " + ", ".join(group)
    if order:
        sql += "\nORDER BY " + ", ".join(order)
    if intent.limit is not None and (group or intent.metric == "list"):
        sql += f"\nLIMIT {intent.limit}"
    return sql


def _destructive(g: Graph, q: str, dialect: str) -> str | None:
    """What a model talked into writing would write. The guard must refuse it."""
    if m := re.search(r"\b(?:drop|truncate)\s+(?:the\s+)?(?:table\s+)?([a-z_]+)", q):
        t = g.find(m[1])
        return f"DROP TABLE {qualified(t, dialect) if t else m[1]}"
    if m := re.search(r"\b(?:delete|remove|erase)\b.*?\b([a-z_]+)\b", q):
        for word in words(q):
            if t := g.find(word):
                sql = f"DELETE FROM {qualified(t, dialect)}"
                for ref, value in _value_filters(g, q):
                    if ref.table is t:
                        sql += f" WHERE {quote(ref.column.name, dialect)} = '{value}'"
                        break
                return sql
    if m := re.search(r"\b(?:update|set|change)\b", q):
        for word in words(q):
            if (t := g.find(word)) and (
                nums := [c for c in t.columns if is_numeric(c) and not is_key(t, c)]
            ):
                return f"UPDATE {qualified(t, dialect)} SET {quote(nums[0].name, dialect)} = 0"
    return None


def plan(
    tables: list[SchemaTable],
    questions: list[str],
    dialect: str,
    today: dt.date | None = None,
) -> Plan:
    """SQL for the last of ``questions``; the earlier ones are the conversation so far."""
    today = today or dt.date.today()
    g = Graph(tables)
    if not tables:
        return Plan(None, "The prompt contained no tables, so there is nothing to query.")
    current = questions[-1].lower()
    if bad := _destructive(g, current, dialect):
        return Plan(bad, "Statement written as asked.")
    previous: Intent | None = None
    for q in questions[:-1]:
        try:
            previous = parse(g, q, today, previous)
        except CannotAnswerError:
            continue
    try:
        intent = parse(g, questions[-1], today, previous)
        return Plan(to_sql(g, intent, dialect), "")
    except CannotAnswerError:
        names = ", ".join(t.name for t in tables[:6])
        return Plan(
            None,
            "I could not match this question to the tables in this database. Name a table "
            f"or a column, for example: how many rows are in {tables[0].name}? "
            f"Tables: {names}.",
        )
