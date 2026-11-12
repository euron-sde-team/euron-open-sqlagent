"""The question queue, in PostgreSQL: claim with ``FOR UPDATE SKIP LOCKED``, lease, finish
under the lease, and reap the leases of workers that died.

A worker's final write carries its own name as a compare-and-set on ``lease_owner``; once
the reaper has handed the question to another worker, the old worker's write matches
nothing and is dropped. Wake-ups travel over pub/sub (Redis, or in process): the queue
channel tells idle workers to look again, and each question's own channel tells the API
request waiting for it that it finished.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sqlagent.chat.models import FINAL_STATUSES, ConversationMessage
from sqlagent.core.container import Container

QUEUE_CHANNEL = "sqa:queue"


def message_channel(message_id: uuid.UUID) -> str:
    return f"sqa:message:{message_id}"


async def notify(container: Container) -> None:
    await container.pubsub.publish(QUEUE_CHANNEL, "1")


async def claim(session: AsyncSession, owner: str, lease_s: float) -> ConversationMessage | None:
    pick = (
        select(ConversationMessage.id)
        .where(
            ConversationMessage.status == "queued", ConversationMessage.available_at <= func.now()
        )
        .order_by(ConversationMessage.available_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    msg = await session.scalar(
        update(ConversationMessage)
        .where(ConversationMessage.id == pick)
        .values(
            status="running",
            lease_owner=owner,
            lease_expires_at=func.now() + timedelta(seconds=lease_s),
            attempts=ConversationMessage.attempts + 1,
        )
        .returning(ConversationMessage)
        .execution_options(synchronize_session=False)
    )
    if msg is None:
        await session.rollback()
        return None
    await session.commit()
    return msg


async def finish(session: AsyncSession, message_id: uuid.UUID, owner: str, **values: Any) -> bool:
    """Write the final state under this worker's lease. False when the lease was lost (the
    caller commits nothing else then)."""
    result = await session.execute(
        update(ConversationMessage)
        .where(
            ConversationMessage.id == message_id,
            ConversationMessage.lease_owner == owner,
            ConversationMessage.status == "running",
        )
        .values(lease_owner=None, lease_expires_at=None, finished_at=func.now(), **values)
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def reap(container: Container, max_attempts: int, limit: int = 100) -> int:
    """Questions whose worker stopped: back to the queue (with backoff), or failed after
    ``max_attempts`` claims."""
    now = datetime.now(UTC)
    async with container.db.sessionmaker() as session:
        rows = (
            await session.scalars(
                select(ConversationMessage)
                .where(
                    ConversationMessage.status == "running",
                    ConversationMessage.lease_expires_at < now,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for msg in rows:
            if msg.attempts >= max_attempts:
                msg.status = "failed"
                msg.error_code = "worker_lost"
                msg.error = (
                    f"The worker answering this question stopped {msg.attempts} times. "
                    "Ask again, and tell an admin if it keeps happening"
                )
                msg.finished_at = now
            else:
                msg.status = "queued"
                msg.available_at = now + timedelta(seconds=min(2**msg.attempts, 30))
            msg.lease_owner = None
            msg.lease_expires_at = None
        await session.commit()
    for msg in rows:
        await container.pubsub.publish(message_channel(msg.id), msg.status)
    if rows:
        await notify(container)
    return len(rows)


async def depth(session: AsyncSession) -> dict[str, int]:
    rows = (
        await session.execute(
            select(ConversationMessage.status, func.count())
            .where(ConversationMessage.status.in_(("queued", "running")))
            .group_by(ConversationMessage.status)
        )
    ).all()
    out = {"queued": 0, "running": 0} | {str(s): int(n) for s, n in rows}
    oldest = await session.scalar(
        select(func.min(ConversationMessage.available_at)).where(
            ConversationMessage.status == "queued", ConversationMessage.available_at <= func.now()
        )
    )
    out["oldest_wait_s"] = int((datetime.now(UTC) - oldest).total_seconds()) if oldest else 0
    return out


async def wait_for(container: Container, message_id: uuid.UUID, timeout_s: float) -> None:
    """Return when the question reaches a final state or ``timeout_s`` passes. Listens on
    the question's channel and also polls, so a lost wake-up only costs a poll interval."""
    deadline = time.monotonic() + timeout_s
    async with container.pubsub.listen(message_channel(message_id)) as sub:
        while True:
            async with container.db.sessionmaker() as session:
                status = await session.scalar(
                    select(ConversationMessage.status).where(ConversationMessage.id == message_id)
                )
            if status is None or status in FINAL_STATUSES:
                return
            left = deadline - time.monotonic()
            if left <= 0:
                return
            with contextlib.suppress(asyncio.TimeoutError):
                await sub.get(min(left, 1.0))
