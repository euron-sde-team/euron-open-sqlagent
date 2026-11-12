"""Chart suggestion from a result's shape alone (A9)."""

from __future__ import annotations

import pytest

from sqlagent.charts.suggest import ColumnIn, suggest


def cols(*spec: str) -> list[ColumnIn]:
    return [ColumnIn(name=s.split(":")[0], kind=s.split(":")[1]) for s in spec]


def test_a_measure_over_time_is_a_line() -> None:
    c = suggest(
        cols("month:date", "revenue:number"),
        [["2026-01-01", 1], ["2026-02-01", 2], ["2026-03-01", 3]],
    )
    assert c is not None and (c.type, c.x, c.y, c.alternatives) == (
        "line",
        "month",
        ["revenue"],
        ["bar"],
    )
    # Time buckets written as text or numbers are time too.
    assert (
        suggest(
            cols("month:text", "n:number"), [["2026-01", 1], ["2026-02", 2], ["2026-03", 4]]
        ).type
        == "line"
    )  # type: ignore[union-attr]
    assert (
        suggest(
            cols("quarter:text", "n:number"), [["2026-Q1", 1], ["2026-Q2", 2], ["2026-Q3", 4]]
        ).type
        == "line"
    )  # type: ignore[union-attr]
    year = suggest(cols("year:number", "hires:number"), [[2021, 3], [2022, 5], [2023, 4]])
    assert year is not None and (year.type, year.x, year.y) == ("line", "year", ["hires"])
    two = suggest(cols("day:date", "n:number"), [["2026-01-01", 1], ["2026-01-02", 2]])
    assert two is not None and two.type == "bar"


def test_a_few_parts_of_a_whole_are_a_pie_and_more_are_bars() -> None:
    pie = suggest(cols("status:text", "n:number"), [["a", 5], ["b", 3], ["c", 1]])
    assert pie is not None and pie.type == "pie" and pie.alternatives == ["bar"]
    rows = [[f"c{i}", i] for i in range(12)]
    bar = suggest(cols("country:text", "revenue:number"), rows)
    assert bar is not None and bar.type == "bar" and bar.alternatives == []
    multi = suggest(cols("dept:text", "avg:number", "max:number"), [["a", 1, 2], ["b", 3, 4]])
    assert multi is not None and multi.type == "bar" and multi.y == ["avg", "max"]
    negative = suggest(cols("x:text", "delta:number"), [["a", -1], ["b", 2]])
    assert negative is not None and negative.type == "bar"


@pytest.mark.parametrize(
    ("columns", "rows"),
    [
        (cols("n:number"), [[1], [2]]),
        (cols("count:number", "x:number"), [[1, 2], [3, 4]]),
        (cols("name:text", "email:text"), [["a", "b"], ["c", "d"]]),
        (cols("a:text", "b:text", "n:number"), [["a", "b", 1], ["c", "d", 2]]),
        (cols("status:text", "n:number"), [["only", 1]]),
        (cols("k:text", "n:number"), [[f"k{i}", i] for i in range(60)]),
    ],
)
def test_shapes_that_do_not_fit_get_no_chart(
    columns: list[ColumnIn], rows: list[list[object]]
) -> None:
    assert suggest(columns, rows) is None
