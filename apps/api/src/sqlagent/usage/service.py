"""Usage counters (atomic upserts) and the report built from the daily rollups."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sqlagent.connections.models import Connection
from sqlagent.usage.models import UsageDaily
from sqlagent.usage.schemas import UsageByConnection, UsageByDay, UsageByModel, UsageReport

COUNTERS = (
    "questions",
    "answered",
    "refused",
    "failed",
    "executions",
    "rows_returned",
    "input_tokens",
    "output_tokens",
)


async def record(
    session: AsyncSession,
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    model: str = "",
    *,
    day: date | None = None,
    **counts: int,
) -> None:
    """Add ``counts`` to today's row (the caller commits). Concurrent writers add, never
    overwrite: the update is ``column = column + excluded.column``."""
    values = {name: int(counts.get(name, 0)) for name in COUNTERS}
    stmt = insert(UsageDaily).values(
        project_id=project_id,
        day=day or datetime.now(UTC).date(),
        connection_id=connection_id,
        model=model[:260],
        **values,
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[
                UsageDaily.project_id,
                UsageDaily.day,
                UsageDaily.connection_id,
                UsageDaily.model,
            ],
            set_={name: getattr(UsageDaily, name) + stmt.excluded[name] for name in COUNTERS},
        )
    )


async def report(session: AsyncSession, project_id: uuid.UUID, days: int) -> UsageReport:
    since = datetime.now(UTC).date() - timedelta(days=days - 1)
    base = (UsageDaily.project_id == project_id, UsageDaily.day >= since)
    sums = [func.coalesce(func.sum(getattr(UsageDaily, n)), 0).label(n) for n in COUNTERS]
    by_day = (
        await session.execute(
            select(UsageDaily.day, *sums)
            .where(*base)
            .group_by(UsageDaily.day)
            .order_by(UsageDaily.day)
        )
    ).all()
    by_conn = (
        await session.execute(
            select(UsageDaily.connection_id, Connection.name, *sums)
            .join(Connection, Connection.id == UsageDaily.connection_id)
            .where(*base)
            .group_by(UsageDaily.connection_id, Connection.name)
            .order_by(func.sum(UsageDaily.questions).desc())
        )
    ).all()
    by_model = (
        await session.execute(
            select(UsageDaily.model, *sums)
            .where(*base, UsageDaily.model != "")
            .group_by(UsageDaily.model)
            .order_by(func.sum(UsageDaily.questions).desc())
        )
    ).all()

    def counts(row: object) -> dict[str, int]:
        return {n: int(getattr(row, n)) for n in COUNTERS}

    return UsageReport(
        days=days,
        since=since,
        by_day=[UsageByDay(day=r.day, **counts(r)) for r in by_day],
        by_connection=[
            UsageByConnection(connection_id=r.connection_id, connection=r.name, **counts(r))
            for r in by_conn
        ],
        by_model=[UsageByModel(model=r.model, **counts(r)) for r in by_model],
    )
