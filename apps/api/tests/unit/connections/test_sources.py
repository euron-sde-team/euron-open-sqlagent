"""Pure parts of the read-only source layer: value conversion, column kinds, timeouts,
friendly driver errors."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from sqlagent.connections.service import friendly
from sqlagent.connections.sources import SqlTarget, _engine, _kind_of, is_timeout, to_json_value


def test_values_become_json() -> None:
    assert to_json_value(Decimal("12.50")) == 12.5
    assert to_json_value(Decimal("1e20")) == "1E+20"
    assert to_json_value(float("nan")) == "nan"
    assert to_json_value(dt.date(2026, 1, 2)) == "2026-01-02"
    assert to_json_value(dt.datetime(2026, 1, 2, 3, 4)) == "2026-01-02T03:04:00"
    assert to_json_value(dt.timedelta(minutes=2)) == 120.0
    u = uuid.uuid4()
    assert to_json_value(u) == str(u)
    assert to_json_value(b"\x00\x01") == "<2 bytes>"
    assert to_json_value([Decimal(1), {"a": dt.date(2026, 1, 1)}]) == [1.0, {"a": "2026-01-01"}]
    assert to_json_value(None) is None and to_json_value(True) is True
    assert to_json_value(object()).startswith("<object")


@pytest.mark.parametrize(
    ("values", "kind"),
    [
        ([1, 2.5, Decimal(3), None], "number"),
        ([True, False], "boolean"),
        ([dt.datetime(2026, 1, 1)], "datetime"),
        ([dt.date(2026, 1, 1)], "date"),
        (["a", None], "text"),
        ([None], "other"),
        (["a", 1], "other"),
    ],
)
def test_column_kinds_come_from_values(values: list[object], kind: str) -> None:
    assert _kind_of(values) == kind


def test_timeouts_are_recognised_per_database() -> None:
    assert is_timeout(Exception("canceling statement due to statement timeout"))
    assert is_timeout(
        Exception(
            "(3024, 'Query execution was interrupted, maximum statement execution time exceeded')"
        )
    )
    assert is_timeout(Exception("interrupted"))
    assert not is_timeout(Exception("syntax error"))


@pytest.mark.parametrize(
    ("raw", "says"),
    [
        ('password authentication failed for user "x"', "password was refused"),
        ("(1045, \"Access denied for user 'x'\")", "password was refused"),
        ('database "nope" does not exist', "database name was not found"),
        ("(1049, \"Unknown database 'x'\")", "database name was not found"),
        ('could not translate host name "db" to address', "could not be resolved"),
        ("connection refused", "Nothing answered"),
        ("timeout expired", "timed out"),
        ("SSL SYSCALL error", "SSL handshake failed"),
        ("something else", "something else"),
    ],
)
def test_driver_errors_say_what_to_check(raw: str, says: str) -> None:
    assert says in friendly(raw)


def test_engines_are_read_only_by_construction(tmp_path: Path) -> None:
    pg = _engine(SqlTarget("postgresql", "db", 5432, "shop", "u", "p"), 7)
    assert pg.url.drivername == "postgresql+psycopg"
    sqlite = _engine(SqlTarget("sqlite", sqlite_path=str(tmp_path / "x.sqlite")), 7)
    assert "mode=ro" in str(sqlite.url)
    with pytest.raises(ValueError, match="needs its database file"):
        _engine(SqlTarget("sqlite"), 1)
    with pytest.raises(ValueError, match="unknown connection kind"):
        _engine(SqlTarget("oracle"), 1)
