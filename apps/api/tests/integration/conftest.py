"""Integration harness: the real API served over HTTP from a background thread and the real
question worker in another, against real Postgres, Redis, the mock model provider and real
demo databases (the shop on PostgreSQL, the people database on MySQL, and SQLite files).

    make test-integration      (starts Postgres, Redis and the two demo database servers)

Isolation: every run uses its own database (``TEST_DATABASE_URL``) and Redis DB index
(``TEST_REDIS_URL``). The suite drops and recreates the database, so it refuses any
database whose name does not contain "test" and any non-local host unless
ALLOW_REMOTE_TEST_DB=true. The demo data is loaded into ``shop_test`` and ``people_test``
on the demo servers, never into the databases ``make demo`` uses.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
import redis.asyncio as aioredis
import uvicorn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from sqlagent.core.config import Settings

TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://sqlagent:sqlagent@localhost:5442/sqlagent_test"
)
TEST_REDIS = os.environ.get("TEST_REDIS_URL", "redis://localhost:5479/15")
ADMIN = {"email": "admin@example.test", "password": "Admin-Pass-123"}
CSRF = {"x-sqa-csrf": "1"}
ROOT = Path(__file__).resolve().parents[4]


def _compose_env() -> dict[str, str]:
    """deploy/compose/.env (written by make env): the demo servers' admin password."""
    path = ROOT / "deploy" / "compose" / ".env"
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and not key.startswith("#"):
                out[key.strip()] = value.strip()
    return out


_ENV = _compose_env()
SOURCE_PASSWORD = os.environ.get(
    "TEST_SOURCE_ADMIN_PASSWORD", _ENV.get("SQLAGENT_SOURCE_ADMIN_PASSWORD", "")
)
READER = "sqlagent_test_reader"
READER_PASSWORD = "Reader-Test-Pass-1"
SOURCE_PG = {
    "host": os.environ.get("TEST_SOURCE_PG_HOST", "127.0.0.1"),
    "port": int(os.environ.get("TEST_SOURCE_PG_PORT", "5443")),
    "admin": "shop_admin",
    "database": "shop_test",
}
SOURCE_MYSQL = {
    "host": os.environ.get("TEST_SOURCE_MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("TEST_SOURCE_MYSQL_PORT", "5406")),
    "admin": "root",
    "database": "people_test",
}


def _guard(url: str) -> None:
    parsed = urlparse(url.replace("+asyncpg", ""))
    if "test" not in (parsed.path or ""):
        raise RuntimeError(f"refusing {parsed.path!r}: the test database name must contain 'test'")
    if (
        parsed.hostname not in ("localhost", "127.0.0.1", "postgres")
        and os.environ.get("ALLOW_REMOTE_TEST_DB") != "true"
    ):
        raise RuntimeError("refusing a non-local test database (set ALLOW_REMOTE_TEST_DB=true)")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Served:
    """An ASGI app (or import string) served by uvicorn on a thread, with its own loop."""

    def __init__(self, app: Any, port: int | None = None) -> None:
        self.port = port or free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self, health: str = "/healthz") -> Served:
        self.thread.start()
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                if httpx.get(self.url + health, timeout=1).status_code < 500:
                    return self
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise RuntimeError(f"server on {self.url} did not start")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=15)


class WorkerThread:
    """The real question worker (``sqlagent.worker.serve``) on its own thread and loop."""

    def __init__(self, settings: Settings, run_tasks: bool = False) -> None:
        self.settings = settings
        self.run_tasks = run_tasks
        self.loop = asyncio.new_event_loop()
        self.stop_event: asyncio.Event | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.ready = threading.Event()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main())

    async def _main(self) -> None:
        from sqlagent.core.container import Container
        from sqlagent.worker import import_task_modules, serve

        import_task_modules()
        container = Container.build(self.settings)
        self.stop_event = asyncio.Event()
        self.ready.set()
        try:
            await serve(container, self.stop_event, self.settings, run_tasks=self.run_tasks)
        finally:
            await container.close()

    def start(self) -> WorkerThread:
        self.thread.start()
        self.ready.wait(10)
        return self

    def stop(self) -> None:
        if self.stop_event is not None:
            self.loop.call_soon_threadsafe(self.stop_event.set)
        self.thread.join(timeout=60)


@pytest.fixture(scope="session")
def mock_ai() -> Iterator[str]:
    served = Served("mockai.app:app").start()
    yield served.url
    served.stop()


@pytest.fixture(scope="session")
async def database() -> AsyncIterator[str]:
    """A fresh database built by the migrations (so they are tested on every run)."""
    _guard(TEST_DB)
    admin_url = TEST_DB.rsplit("/", 1)[0] + "/postgres"
    name = TEST_DB.rsplit("/", 1)[1]
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await engine.dispose()
    from sqlagent.migrations.runner import upgrade

    await asyncio.to_thread(upgrade, TEST_DB)
    yield TEST_DB


@dataclass(frozen=True)
class Sources:
    """The demo databases, loaded once per session with a fixed date."""

    today: dt.date
    sqlite_path: Path

    def pg(self, *, admin: bool = False, password: str | None = None) -> dict[str, Any]:
        return {
            "name": "Shop (PostgreSQL)",
            "kind": "postgresql",
            "host": SOURCE_PG["host"],
            "port": SOURCE_PG["port"],
            "database": SOURCE_PG["database"],
            "username": SOURCE_PG["admin"] if admin else READER,
            "password": password
            if password is not None
            else (SOURCE_PASSWORD if admin else READER_PASSWORD),
            "ssl_mode": "disable",
            "sample_values": True,
        }

    def mysql(self, *, admin: bool = False) -> dict[str, Any]:
        return {
            "name": "People (MySQL)",
            "kind": "mysql",
            "host": SOURCE_MYSQL["host"],
            "port": SOURCE_MYSQL["port"],
            "database": SOURCE_MYSQL["database"],
            "username": SOURCE_MYSQL["admin"] if admin else READER,
            "password": SOURCE_PASSWORD if admin else READER_PASSWORD,
            "ssl_mode": "disable",
            "sample_values": True,
        }


def _admin_url(kind: str, database: str) -> str:
    if kind == "postgresql":
        return (
            f"postgresql://{SOURCE_PG['admin']}:{SOURCE_PASSWORD}@{SOURCE_PG['host']}:"
            f"{SOURCE_PG['port']}/{database}"
        )
    return (
        f"mysql://{SOURCE_MYSQL['admin']}:{SOURCE_PASSWORD}@{SOURCE_MYSQL['host']}:"
        f"{SOURCE_MYSQL['port']}/{database}"
    )


def _load_sources(today: dt.date, sqlite_path: Path) -> None:
    import sqlalchemy as sa

    from sqlagent.demo.databases import build_people, build_shop, build_subscriptions

    if not SOURCE_PASSWORD:
        raise RuntimeError(
            "no demo database password: run make env (or set TEST_SOURCE_ADMIN_PASSWORD)"
        )
    pg = sa.create_engine(
        _admin_url("postgresql", "shop").replace("postgresql://", "postgresql+psycopg://"),
        isolation_level="AUTOCOMMIT",
    )
    with pg.connect() as c:
        if not c.exec_driver_sql("SELECT 1 FROM pg_database WHERE datname = 'shop_test'").scalar():
            c.exec_driver_sql("CREATE DATABASE shop_test")
    pg.dispose()
    my = sa.create_engine(_admin_url("mysql", "people").replace("mysql://", "mysql+pymysql://"))
    with my.begin() as c:
        c.exec_driver_sql("CREATE DATABASE IF NOT EXISTS people_test")
    my.dispose()
    build_shop(_admin_url("postgresql", "shop_test"), READER_PASSWORD, today, READER)
    build_people(_admin_url("mysql", "people_test"), READER_PASSWORD, today, READER)
    build_subscriptions(sqlite_path, today)


@pytest.fixture(scope="session")
def sources(tmp_path_factory: pytest.TempPathFactory) -> Sources:
    today = dt.date(2026, 6, 15)
    path = tmp_path_factory.mktemp("sources") / "subscriptions.sqlite"
    _load_sources(today, path)
    return Sources(today=today, sqlite_path=path)


def make_settings(database: str, tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "database_url": database,
        "redis_url": TEST_REDIS,
        "session_secret": "test-only-session-secret-with-32-plus-bytes",
        "api_key_pepper": "test-only-api-key-pepper-with-32-plus-bytes",
        "local_master_key": "test-only-master-key-with-32-plus-bytes-ok",
        "local_storage_dir": str(tmp_path / "objects"),
        "work_dir": str(tmp_path / "work"),
        "public_url": "http://localhost:5410",
        "mail_backend": "log",
        "question_rpm": 100_000,
        "lease_s": 15.0,
        "worker_poll_interval_s": 0.2,
        "task_interval_s": 0.5,
        "worker_metrics_port": 0,
        "worker_concurrency": 8,
        "key_mode": os.environ.get("TEST_KEY_MODE", "local"),
        "storage": os.environ.get("TEST_STORAGE", "local"),
        "aws_endpoint_url": os.environ.get("TEST_AWS_ENDPOINT"),
        "s3_force_path_style": True,
        "kms_key_id": os.environ.get("TEST_KMS_KEY_ID", "alias/sqlagent-local"),
        "objects_bucket": os.environ.get("TEST_OBJECTS_BUCKET", "sqlagent-local-objects"),
    }
    values.update(overrides)
    return Settings(**values)


async def reset(database: str) -> None:
    """Empty every table and the Redis DB between tests."""
    engine = create_async_engine(database)
    async with engine.begin() as conn:
        # A session a previous test left inside a transaction would block TRUNCATE.
        await conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = "
                "current_database() AND pid <> pg_backend_pid() AND state LIKE 'idle in transaction%'"
            )
        )
    async with engine.begin() as conn:
        tables = (
            await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                    "AND tablename NOT IN ('alembic_version', 'audit_log')"
                )
            )
        ).scalars()
        names = ", ".join(f'"{t}"' for t in tables)
        if names:
            await conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    await engine.dispose()
    r = aioredis.Redis.from_url(TEST_REDIS)
    await r.flushdb()
    await r.aclose()


async def bootstrap_admin(database: str) -> None:
    from sqlagent.audit.service import Actor
    from sqlagent.core.db import Database
    from sqlagent.core.security import hash_password
    from sqlagent.orgs import service as orgs
    from sqlagent.users.models import User

    db = Database(database, pool_size=1, max_overflow=0)
    async with db.sessionmaker() as session:
        user = User(
            email=ADMIN["email"],
            name="Admin",
            role="admin",
            password_hash=hash_password(ADMIN["password"]),
        )
        session.add(user)
        await session.flush()
        await orgs.create_for(session, user, "Acme", Actor(user.id, user.email, "admin"))
        await session.commit()
    await db.dispose()


async def login(base_url: str, creds: dict[str, str] = ADMIN) -> httpx.AsyncClient:
    client = httpx.AsyncClient(base_url=base_url, timeout=180, headers=CSRF)
    resp = await client.post("/api/v1/auth/login", json=creds)
    assert resp.status_code == 200, resp.text
    client.headers["authorization"] = f"Bearer {resp.json()['session_token']}"
    return client


@dataclass
class Stack:
    """The running API and worker, a signed-in admin, the current project, and helpers."""

    api_url: str
    settings: Settings
    client: httpx.AsyncClient
    mock_ai_url: str
    worker: WorkerThread | None
    org_id: str
    project_id: str = ""

    async def ok(
        self,
        method: str,
        path: str,
        json: Any = None,
        status: int | None = None,
        client: httpx.AsyncClient | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        c = client or self.client
        resp = await c.request(method, path, json=json, params=params)
        expected = status or (201 if method == "POST" and resp.status_code == 201 else 200)
        assert resp.status_code == expected, f"{method} {path}: {resp.status_code} {resp.text}"
        if not resp.content:
            return None
        if "json" not in resp.headers.get("content-type", ""):
            return resp.content
        return resp.json()

    def p(self, path: str = "") -> str:
        return f"/api/v1/projects/{self.project_id}{path}"

    async def project(self, name: str = "Analytics") -> dict[str, Any]:
        out = dict(
            await self.ok(
                "POST", "/api/v1/projects", {"org_id": self.org_id, "name": name}, status=201
            )
        )
        self.project_id = out["id"]
        return out

    async def provider(
        self,
        name: str = "mock",
        kind: str = "mock",
        client: httpx.AsyncClient | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        base = {
            "mock": None,
            "openai_compatible": f"{self.mock_ai_url}/v1",
            "openai": f"{self.mock_ai_url}/v1",
            "anthropic": f"{self.mock_ai_url}/anthropic",
            "gemini": f"{self.mock_ai_url}/gemini",
            "ollama": f"{self.mock_ai_url}/ollama",
        }[kind]
        body: dict[str, Any] = {"name": name, "kind": kind, **extra}
        if base:
            body |= {"base_url": base, "api_key": f"sk-{name}-secret", "model": "mock-sql-small"}
        return dict(await self.ok("POST", self.p("/providers"), body, status=201, client=client))

    async def connection(self, body: dict[str, Any], **changes: Any) -> dict[str, Any]:
        return dict(await self.ok("POST", self.p("/connections"), {**body, **changes}, status=201))

    async def sqlite(
        self, path: Path, name: str = "Subscriptions (SQLite)", **form: Any
    ) -> dict[str, Any]:
        with path.open("rb") as f:
            resp = await self.client.post(
                self.p("/connections/sqlite"),
                data={
                    "name": name,
                    "sample_values": "true",
                    **{k: str(v) for k, v in form.items()},
                },
                files={"file": ("subscriptions.sqlite", f, "application/vnd.sqlite3")},
            )
        assert resp.status_code == 201, resp.text
        return dict(resp.json())

    async def ask(
        self,
        question: str,
        *,
        connection_id: str | None = None,
        conversation_id: str | None = None,
        client: httpx.AsyncClient | None = None,
        status: int = 201,
        wait: float = 30,
        **body: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"question": question, "wait": wait, **body}
        if connection_id:
            payload["connection_id"] = connection_id
        if conversation_id:
            payload["conversation_id"] = conversation_id
        return dict(await self.ok("POST", self.p("/chat"), payload, status=status, client=client))

    async def audit(self, **params: Any) -> list[dict[str, Any]]:
        return list((await self.ok("GET", self.p("/audit-logs"), params=params))["items"])

    async def user_in_org(
        self, role: str = "member", email: str | None = None
    ) -> httpx.AsyncClient:
        email = email or f"{role}-{time.monotonic_ns()}@example.test"
        password = "User-Pass-123"
        await self.ok(
            "POST",
            f"/api/v1/orgs/{self.org_id}/members",
            {"email": email, "role": role, "name": "Test User", "password": password},
            status=201,
        )
        return await login(self.api_url, {"email": email, "password": password})

    async def member(self, role: str) -> tuple[httpx.AsyncClient, str]:
        """A person in the organization with ``role`` in the current project."""
        client = await self.user_in_org("member")
        me = (await client.get("/api/v1/auth/me")).json()
        await self.ok(
            "POST",
            self.p("/members"),
            {"email": me["email"], "role": role},
            status=201,
        )
        return client, str(me["id"])


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    """Tests override this to change the API's and the worker's settings."""
    return {}


@pytest.fixture
def run_worker() -> bool:
    """Tests that drive the queue by hand override this to False."""
    return True


@pytest.fixture
async def stack(
    database: str,
    tmp_path: Path,
    mock_ai: str,
    settings_overrides: dict[str, Any],
    run_worker: bool,
) -> AsyncIterator[Stack]:
    from sqlagent.main import create_app

    await reset(database)
    await bootstrap_admin(database)
    settings = make_settings(database, tmp_path, **settings_overrides)
    served = Served(create_app(settings)).start()
    worker = WorkerThread(settings).start() if run_worker else None
    client = await login(served.url)
    org_id = (await client.get("/api/v1/orgs")).json()[0]["id"]
    async with httpx.AsyncClient() as http:
        await http.post(f"{mock_ai}/_mock/reset")
    stack = Stack(served.url, settings, client, mock_ai, worker, org_id)
    try:
        yield stack
    finally:
        await client.aclose()
        # A test may have replaced or started the worker: stop whichever is running now.
        for w in {id(x): x for x in (worker, stack.worker) if x is not None}.values():
            w.stop()
        served.stop()


@pytest.fixture
async def ready(stack: Stack) -> Stack:
    """A stack with a project and the built-in mock provider as its default."""
    await stack.project()
    await stack.provider()
    return stack
