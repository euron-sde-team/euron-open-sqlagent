"""The shapes the SDK hands back. Plain dataclasses over the API's JSON, with the raw
document kept in ``raw`` for anything not mapped here."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

FINAL = ("answered", "refused", "failed", "no_answer")


@dataclass(frozen=True)
class Chart:
    type: str
    x: str
    y: list[str]
    alternatives: list[str]

    @classmethod
    def of(cls, d: dict[str, Any] | None) -> Chart | None:
        if not d:
            return None
        return cls(str(d["type"]), str(d["x"]), list(d["y"]), list(d.get("alternatives", [])))


@dataclass(frozen=True)
class Answer:
    """A question and what SQLAgent did with it."""

    id: str
    conversation_id: str
    connection_id: str
    question: str
    status: str
    sql: str | None
    explanation: str | None
    validated: bool
    error: str | None
    execution_id: str | None
    columns: list[str]
    rows: list[list[Any]]
    total_rows: int
    truncated: bool
    chart: Chart | None
    raw: dict[str, Any] = field(repr=False)

    @property
    def ok(self) -> bool:
        return self.status == "answered"

    @property
    def final(self) -> bool:
        return self.status in FINAL

    def records(self) -> list[dict[str, Any]]:
        """The rows of the first page as dictionaries keyed by column name."""
        return [dict(zip(self.columns, r, strict=False)) for r in self.rows]

    @classmethod
    def of(cls, d: dict[str, Any]) -> Answer:
        ex = d.get("execution") or {}
        page = d.get("page") or {}
        return cls(
            id=str(d["id"]),
            conversation_id=str(d["conversation_id"]),
            connection_id=str(d["connection_id"]),
            question=str(d["question"]),
            status=str(d["status"]),
            sql=d.get("sql"),
            explanation=d.get("explanation"),
            validated=bool(d.get("validated")),
            error=d.get("error"),
            execution_id=ex.get("id"),
            columns=[str(c["name"]) for c in page.get("columns", ex.get("columns", []))],
            rows=list(page.get("rows", [])),
            total_rows=int(page.get("total", ex.get("row_count", 0)) or 0),
            truncated=bool(ex.get("truncated", False)),
            chart=Chart.of(ex.get("chart")),
            raw=d,
        )


@dataclass(frozen=True)
class Execution:
    """A query run directly (``sql.execute``)."""

    id: str
    status: str
    sql: str
    error: str | None
    row_count: int
    truncated: bool
    duration_ms: float
    columns: list[str]
    rows: list[list[Any]]
    chart: Chart | None
    raw: dict[str, Any] = field(repr=False)

    @property
    def ok(self) -> bool:
        return self.status == "succeeded"

    @classmethod
    def of(cls, d: dict[str, Any]) -> Execution:
        page = d.get("page") or {}
        return cls(
            id=str(d["id"]),
            status=str(d["status"]),
            sql=str(d["sql"]),
            error=d.get("error"),
            row_count=int(d.get("row_count", 0)),
            truncated=bool(d.get("truncated")),
            duration_ms=float(d.get("duration_ms", 0.0)),
            columns=[str(c["name"]) for c in d.get("columns", [])],
            rows=list(page.get("rows", [])),
            chart=Chart.of(d.get("chart")),
            raw=d,
        )
