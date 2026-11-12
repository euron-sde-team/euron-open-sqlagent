"""The question worker and the scheduler.

``sqlagent worker`` answers queued questions (``chat/engine.py``). Stateless and safe to
run as many replicas: questions are claimed with ``FOR UPDATE SKIP LOCKED`` and leased
(``chat/queue.py``). Up to ``WORKER_CONCURRENCY`` questions are answered at once as
asyncio tasks (model calls are I/O; database queries run in threads). Idle workers wake on
a queue notification or poll. SIGTERM stops claiming and waits for running questions up to
the grace period; their leases make a hard kill safe (another worker answers them).

``sqlagent scheduler`` runs the periodic tasks: the lease reaper, schema refresh,
retention and queue gauges. Prometheus metrics on ``WORKER_METRICS_PORT``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import time

from prometheus_client import start_http_server

from sqlagent.chat import queue
from sqlagent.chat.engine import answer
from sqlagent.core.config import Settings, get_settings
from sqlagent.core.container import Container
from sqlagent.core.db import import_all_models
from sqlagent.core.logs import configure_logging
from sqlagent.core.tasks import tasks

log = logging.getLogger("sqlagent.worker")
SHUTDOWN_GRACE_S = 25.0


def import_task_modules() -> None:
    """Every module that registers a periodic task."""
    from sqlagent.chat import tasks as _chat  # noqa: F401


def worker_name() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


async def tick(container: Container) -> bool:
    busy = False
    for name, task in tasks().items():
        try:
            handled = await task(container)
        except Exception:
            log.exception("task %s failed", name)
            continue
        if handled:
            log.info("task done", extra={"task": name, "items": handled})
            busy = True
    return busy


async def periodic_loop(
    container: Container, stop: asyncio.Event, settings: Settings, wake: asyncio.Event | None
) -> None:
    while not stop.is_set():
        started = time.monotonic()
        busy = await tick(container)
        if busy and wake is not None:
            wake.set()
        delay = 0.5 if busy else max(settings.task_interval_s - (time.monotonic() - started), 0.5)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=delay)


async def serve(
    container: Container, stop: asyncio.Event, settings: Settings, *, run_tasks: bool = False
) -> None:
    name = worker_name()
    wake = asyncio.Event()
    slots = asyncio.Semaphore(settings.worker_concurrency)
    running: set[asyncio.Task[None]] = set()

    async def listen() -> None:
        while not stop.is_set():
            try:
                async with container.pubsub.listen(queue.QUEUE_CHANNEL) as sub:
                    while not stop.is_set():
                        if await sub.get(1.0):
                            wake.set()
            except Exception:
                await asyncio.sleep(2)

    async def one(slot_name: str) -> bool:
        async with container.db.sessionmaker() as session:
            msg = await queue.claim(session, slot_name, settings.lease_s)
        if msg is None:
            return False

        async def go() -> None:
            try:
                await answer(container, msg, slot_name)
            finally:
                slots.release()

        task = asyncio.create_task(go())
        running.add(task)
        task.add_done_callback(running.discard)
        return True

    async def until(event: asyncio.Event, wait_s: float | None = None) -> None:
        """Wait for ``event`` or ``stop``, whichever comes first (never cancelled mid-query)."""
        waits = [asyncio.ensure_future(event.wait()), asyncio.ensure_future(stop.wait())]
        try:
            await asyncio.wait(waits, timeout=wait_s, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for w in waits:
                w.cancel()

    async def claimer() -> None:
        n = 0
        while not stop.is_set():
            acquired = asyncio.ensure_future(slots.acquire())
            stopping = asyncio.ensure_future(stop.wait())
            await asyncio.wait([acquired, stopping], return_when=asyncio.FIRST_COMPLETED)
            stopping.cancel()
            if not acquired.done() or stop.is_set():
                acquired.cancel()
                if acquired.done() and not acquired.cancelled():
                    slots.release()
                return
            n += 1
            try:
                claimed = await one(f"{name}#{n}")
            except Exception:
                log.exception("claim failed")
                claimed = False
            if not claimed:
                slots.release()
                await until(wake, settings.worker_poll_interval_s)
                wake.clear()

    listener = asyncio.create_task(listen())
    # The claimer and the periodic tasks finish their current (short) transaction and stop
    # on their own; cancelling them mid-query could strand a connection in a transaction.
    graceful = [asyncio.create_task(claimer())]
    if run_tasks:
        graceful.append(asyncio.create_task(periodic_loop(container, stop, settings, wake)))
    await stop.wait()
    log.info("stopping: %d running questions get %ss to finish", len(running), SHUTDOWN_GRACE_S)
    listener.cancel()
    await asyncio.wait(graceful, timeout=SHUTDOWN_GRACE_S)
    if running:
        _, pending = await asyncio.wait(running, timeout=SHUTDOWN_GRACE_S)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


async def _main(role: str) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    import_all_models()
    import_task_modules()
    if settings.worker_metrics_port:
        start_http_server(settings.worker_metrics_port)
    container = Container.build(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    log.info("%s started", role, extra={"concurrency": settings.worker_concurrency})
    try:
        if role == "scheduler":
            await periodic_loop(container, stop, settings, None)
        else:
            await serve(container, stop, settings)
    finally:
        await container.close()
        log.info("%s stopped", role)


async def main() -> None:
    await _main("worker")


async def scheduler_main() -> None:
    await _main("scheduler")
