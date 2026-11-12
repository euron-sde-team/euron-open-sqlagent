"""Which chart fits a result, decided from its shape alone.

A result can be charted when it has one category column (text, a date, or a time bucket
such as a year) and one or more numeric columns:

* ``line`` when the category is time (dates, or a column named like a time bucket whose
  values sort as time) and there are at least three points;
* ``pie`` for one measure over a handful of non-negative parts (two to eight rows) that
  read as shares of a whole;
* ``bar`` otherwise, up to 50 categories.

Anything else (one row of one value, wide listings, more than 50 categories) gets no chart:
the table is the honest view. The person can always switch to another type that fits.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field

from sqlagent.core.schemas import ApiModel

ChartType = Literal["bar", "line", "pie"]
TIME_NAMES = re.compile(r"(^|_)(date|day|week|month|quarter|year|period|time|at|on)($|_)")
_ISO_DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?([T ].*)?$|^\d{4}-Q[1-4]$")
MAX_BAR = 50
MAX_PIE = 8


class ColumnIn(ApiModel):
    name: str = Field(max_length=200)
    kind: str = Field("text", description="number, text, date, datetime, boolean or other")


class ChartSuggestion(ApiModel):
    type: ChartType
    x: str
    y: list[str]
    # Other types that also fit this shape, for the manual override.
    alternatives: list[ChartType] = Field(default_factory=list)
    reason: str


def _is_time(col: ColumnIn, values: list[Any]) -> bool:
    if col.kind in ("date", "datetime"):
        return True
    present = [v for v in values if v is not None]
    if not present or not TIME_NAMES.search(col.name.lower()):
        return False
    if col.kind == "number":
        return all(isinstance(v, int | float) and 1900 <= v <= 2200 for v in present)
    return all(isinstance(v, str) and _ISO_DATE.match(v) for v in present)


def suggest(columns: list[ColumnIn], rows: list[list[Any]]) -> ChartSuggestion | None:
    if len(rows) < 2 or len(columns) < 2:
        return None
    numeric = [i for i, c in enumerate(columns) if c.kind == "number"]
    category = [i for i, c in enumerate(columns) if i not in numeric and c.kind != "boolean"]
    if not numeric:
        return None
    if not category:
        # A time bucket typed as a number (YEAR(...)): the first column, when it is time.
        first = columns[0]
        if first.kind == "number" and _is_time(first, [r[0] for r in rows]) and len(numeric) > 1:
            category, numeric = [0], numeric[1:]
        else:
            return None
    if len(category) != 1:
        return None
    x = category[0]
    ys = [columns[i].name for i in numeric]
    xs = [r[x] for r in rows]
    if _is_time(columns[x], xs):
        if len(rows) >= 3:
            return ChartSuggestion(
                type="line",
                x=columns[x].name,
                y=ys,
                alternatives=["bar"],
                reason="A measure over time",
            )
        return ChartSuggestion(
            type="bar", x=columns[x].name, y=ys, alternatives=[], reason="Two points in time"
        )
    if len(rows) > MAX_BAR:
        return None
    values = [r[numeric[0]] for r in rows]
    shares = (
        all(isinstance(v, int | float) and v >= 0 for v in values)
        and sum(float(v) for v in values if isinstance(v, int | float)) > 0
    )
    if len(ys) == 1 and 2 <= len(rows) <= MAX_PIE and shares:
        return ChartSuggestion(
            type="pie",
            x=columns[x].name,
            y=ys,
            alternatives=["bar"],
            reason="A few parts of one whole",
        )
    alternatives: list[ChartType] = (
        ["pie"] if len(ys) == 1 and len(rows) <= MAX_PIE and shares else []
    )
    return ChartSuggestion(
        type="bar",
        x=columns[x].name,
        y=ys,
        alternatives=alternatives,
        reason="A measure per category",
    )
