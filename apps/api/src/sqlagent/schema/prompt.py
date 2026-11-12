"""The schema as the model sees it: the real tables of the connected database, most
relevant first, within a character budget.

The block is plain text a model reads easily and the deterministic mock provider parses
back (``parse_block``), so both always agree on what the prompt contained:

    Tables:
    - public.orders (table, ~6012 rows)
        id integer PK
        customer_id integer -> public.customers.id
        status varchar(20) values: delivered, shipped, cancelled
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlagent.schema.schemas import SchemaColumn, SchemaForeignKey, SchemaTable

HEADER = "Tables:"
_WORD = re.compile(r"[a-z0-9]+")
_TABLE_LINE = re.compile(r"^- (?P<name>\S+) \((?P<kind>table|view)(?:, ~(?P<rows>\d+) rows)?\)$")
_COLUMN_LINE = re.compile(
    r"^ {4}(?P<name>\S+) (?P<type>.+?)(?P<pk> PK)?(?: -> (?P<ref>\S+))?"
    r"(?: values: (?P<values>.*))?$"
)


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def stem(word: str) -> str:
    """A crude singular: orders -> order, categories -> category, salaries -> salary."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ses", "xes", "ches", "shes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def stems(text: str) -> set[str]:
    out: set[str] = set()
    for w in words(text):
        out.add(w)
        out.add(stem(w))
    return out


def relevance(table: SchemaTable, question: str) -> int:
    """How strongly a question points at a table: its name counts most, then columns."""
    q = stems(question)
    score = 0
    name_parts = {stem(p) for p in words(table.name)}
    score += 10 * len(name_parts & q)
    for c in table.columns:
        parts = {stem(p) for p in words(c.name)}
        score += 2 * len(parts & q)
        if any(v.lower() in question.lower() for v in c.sample_values if len(v) > 2):
            score += 4
    return score


def render_table(t: SchemaTable) -> str:
    rows = f", ~{t.row_count} rows" if t.row_count is not None else ""
    lines = [f"- {t.qualified} ({t.kind}{rows})"]
    refs: dict[str, str] = {}
    for fk in t.foreign_keys:
        if len(fk.columns) == 1 and len(fk.ref_columns) == 1:
            refs[fk.columns[0]] = f"{fk.ref_table}.{fk.ref_columns[0]}"
    for c in t.columns:
        line = f"    {c.name} {c.type}"
        if c.primary_key:
            line += " PK"
        if c.name in refs:
            line += f" -> {refs[c.name]}"
        if c.sample_values:
            line += " values: " + ", ".join(c.sample_values)
        lines.append(line)
    return "\n".join(lines)


def select_tables(tables: list[SchemaTable], question: str, max_chars: int) -> list[SchemaTable]:
    """The tables to show for ``question``: all of them when they fit, otherwise the most
    relevant first (plus the tables they reference) until the budget is spent."""
    rendered = {t.qualified: render_table(t) for t in tables}
    if sum(len(r) + 1 for r in rendered.values()) <= max_chars:
        return list(tables)
    by_name = {t.qualified: t for t in tables}
    ranked = sorted(tables, key=lambda t: (-relevance(t, question), t.qualified))
    chosen: dict[str, SchemaTable] = {}
    used = 0
    for t in ranked:
        group = [t] + [by_name[fk.ref_table] for fk in t.foreign_keys if fk.ref_table in by_name]
        for g in group:
            size = len(rendered[g.qualified]) + 1
            if g.qualified in chosen or used + size > max_chars:
                continue
            chosen[g.qualified] = g
            used += size
        if used >= max_chars:
            break
    return list(chosen.values())


def render(tables: list[SchemaTable], question: str, max_chars: int) -> str:
    chosen = select_tables(tables, question, max_chars)
    return HEADER + "\n" + "\n".join(render_table(t) for t in chosen)


@dataclass
class ParsedTable:
    name: str
    kind: str
    row_count: int | None
    columns: list[SchemaColumn] = field(default_factory=list)
    foreign_keys: list[SchemaForeignKey] = field(default_factory=list)

    def to_schema(self) -> SchemaTable:
        schema, _, name = self.name.rpartition(".")
        return SchemaTable(
            schema_name=schema or None,
            name=name,
            kind=self.kind,
            row_count=self.row_count,
            columns=self.columns,
            foreign_keys=self.foreign_keys,
        )


def parse_block(text: str) -> list[SchemaTable]:
    """The tables in a prompt that ``render`` wrote (anything else is ignored)."""
    if HEADER not in text:
        return []
    out: list[ParsedTable] = []
    for line in text.split(HEADER, 1)[1].splitlines():
        if m := _TABLE_LINE.match(line):
            out.append(
                ParsedTable(
                    name=m["name"],
                    kind=m["kind"],
                    row_count=int(m["rows"]) if m["rows"] else None,
                )
            )
        elif out and (m := _COLUMN_LINE.match(line)):
            col = SchemaColumn(
                name=m["name"],
                type=m["type"],
                primary_key=bool(m["pk"]),
                sample_values=[v.strip() for v in (m["values"] or "").split(",") if v.strip()],
            )
            out[-1].columns.append(col)
            if m["ref"]:
                ref_table, _, ref_col = m["ref"].rpartition(".")
                out[-1].foreign_keys.append(
                    SchemaForeignKey(columns=[col.name], ref_table=ref_table, ref_columns=[ref_col])
                )
        elif out and not line.startswith(" "):
            break
    return [t.to_schema() for t in out]
