"""The prompts SQLAgent sends a model, and reading its answer back.

Two tasks, named on the system message's first line so the deterministic mock (and a
person reading a log) can tell them apart:

* ``TASK: generate``: the real schema of the connected database (``schema.prompt``), the
  dialect, today's date, the rules, and the conversation so far as alternating turns, so
  a follow-up such as "and last year?" is answered against the previous question and its
  result instead of a guess.
* ``TASK: explain``: one query, to be described in plain language. Nothing is executed.

The model answers with one JSON object. ``parse_answer`` accepts that object, the object
inside a Markdown fence, or a bare ```sql fence, because real models drift.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from typing import Any

from sqlagent.providers.types import Message
from sqlagent.schema import prompt as schema_prompt
from sqlagent.schema.schemas import SchemaTable

GENERATE_RULES = """You turn questions about a database into one SQL query.
Rules:
- Answer with one JSON object and nothing else: {"sql": "...", "explanation": "..."}.
- The query is exactly one read-only SELECT (CTEs, joins, subqueries and window functions
  are fine). Never write INSERT, UPDATE, DELETE, DDL, or more than one statement.
- Use only the tables and columns listed below, with the dialect's syntax and functions.
- Prefer readable column aliases. Add LIMIT when listing rows.
- "explanation" says in one or two plain sentences what the query returns.
- If the question cannot be answered from these tables, answer
  {"sql": null, "explanation": "<why, and what could be asked instead>"}.
- Follow-up questions refer to the previous turns: keep their tables, measures and
  filters, and change only what the new question changes."""

EXPLAIN_RULES = """You explain SQL queries to people who do not read SQL.
Answer with one JSON object and nothing else: {"explanation": "..."}.
Say what the query returns, from which tables, which rows it keeps, how it groups and
sorts, in two to five plain sentences. Do not run or rewrite the query. If it changes
data instead of reading it, say so plainly."""


@dataclass(frozen=True)
class Turn:
    """A prior question in the conversation, with what was answered."""

    question: str
    sql: str | None
    summary: str


@dataclass(frozen=True)
class Answer:
    sql: str | None
    explanation: str


def generate_messages(
    *,
    dialect: str,
    tables: list[SchemaTable],
    question: str,
    history: list[Turn],
    max_schema_chars: int,
    today: dt.date | None = None,
    connection_note: str = "",
) -> tuple[Message, ...]:
    context = " ".join([question, *(t.question for t in history[-2:])])
    block = schema_prompt.render(tables, context, max_schema_chars)
    system = "\n".join(
        [
            "TASK: generate",
            f"Dialect: {dialect}",
            f"Today: {(today or dt.date.today()).isoformat()}",
            *([f"About this database: {connection_note}"] if connection_note else []),
            "",
            GENERATE_RULES,
            "",
            block,
        ]
    )
    messages: list[Message] = [Message(role="system", content=system)]
    for t in history:
        messages.append(Message(role="user", content=f"Question: {t.question}"))
        messages.append(
            Message(
                role="assistant",
                content=json.dumps({"sql": t.sql, "explanation": t.summary}),
            )
        )
    messages.append(Message(role="user", content=f"Question: {question}"))
    return tuple(messages)


def explain_messages(*, dialect: str, sql: str) -> tuple[Message, ...]:
    system = "\n".join(["TASK: explain", f"Dialect: {dialect}", "", EXPLAIN_RULES])
    return (
        Message(role="system", content=system),
        Message(role="user", content=f"```sql\n{sql.strip()}\n```"),
    )


_FENCE = re.compile(r"```(?:json|sql)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)


def _json_object(text: str) -> dict[str, Any] | None:
    candidates = [text.strip()]
    candidates += [m.strip() for m in _FENCE.findall(text)]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for c in candidates:
        try:
            value = json.loads(c)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def parse_answer(text: str) -> Answer:
    """The SQL and explanation in a model's answer (None SQL when it declined)."""
    obj = _json_object(text)
    if obj is not None:
        sql = obj.get("sql")
        explanation = str(obj.get("explanation") or "").strip()
        return Answer(
            sql=str(sql).strip() if isinstance(sql, str) and sql.strip() else None,
            explanation=explanation,
        )
    fences = re.findall(r"```sql\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fences:
        rest = re.sub(r"```sql\s*\n.*?```", "", text, flags=re.DOTALL | re.IGNORECASE)
        return Answer(sql=fences[0].strip(), explanation=rest.strip())
    stripped = text.strip()
    if re.match(r"(?is)^(with|select)\b", stripped):
        return Answer(sql=stripped, explanation="")
    return Answer(sql=None, explanation=stripped[:1000])


def parse_explanation(text: str) -> str:
    obj = _json_object(text)
    if obj is not None and obj.get("explanation"):
        return str(obj["explanation"]).strip()
    return text.strip()
