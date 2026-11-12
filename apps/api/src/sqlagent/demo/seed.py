"""``make demo``: a working SQLAgent with real data behind every screen.

Builds the three demo databases (shop on PostgreSQL, people on MySQL, subscriptions on
SQLite), then the SQLAgent side: an organization with three people (admin, analyst,
viewer), two projects, the built-in mock provider plus an OpenAI-compatible provider that
points at the mock service, read-only connections to every demo database, and
conversations asked through the real pipeline (model, SQL guard, read-only execution,
audit log), spread over the last two weeks. Run it again at any time: it starts over.
"""

from __future__ import annotations

import asyncio
import os
import random
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, text, update

from sqlagent.audit.service import Actor
from sqlagent.chat import queue
from sqlagent.chat import service as chat
from sqlagent.chat.engine import answer
from sqlagent.chat.models import Conversation, ConversationMessage
from sqlagent.chat.schemas import AskRequest
from sqlagent.connections import service as connections
from sqlagent.connections.models import Connection
from sqlagent.connections.schemas import ServerConnection
from sqlagent.core.config import get_settings
from sqlagent.core.container import Container
from sqlagent.core.db import import_all_models
from sqlagent.core.security import generate_api_key, hash_password
from sqlagent.demo import databases
from sqlagent.executions.models import QueryExecution
from sqlagent.instance.models import InstanceSettings
from sqlagent.orgs import service as orgs
from sqlagent.orgs.models import Organization, OrgMember
from sqlagent.projects.access import Principal
from sqlagent.projects.models import ApiKey, Project, ProjectMember
from sqlagent.providers import service as providers
from sqlagent.providers.schemas import ProviderCreate
from sqlagent.schema import service as schemas
from sqlagent.templates import service as templates
from sqlagent.templates.models import QueryTemplate
from sqlagent.templates.schemas import TemplateCreate
from sqlagent.usage.models import UsageDaily
from sqlagent.users.models import User

PEOPLE = [
    ("maya.chen@example.com", "Maya Chen", "admin"),
    ("arjun.mehta@example.com", "Arjun Mehta", "editor"),
    ("sofia.lopez@example.com", "Sofia Lopez", "viewer"),
]

RETAIL_CONVERSATIONS = [
    (
        "shop",
        ["How many orders were placed this year?", "and last year?", "break it down by channel"],
    ),
    ("shop", ["Monthly revenue this year"]),
    ("shop", ["Top 5 customers by total spend"]),
    ("shop", ["Revenue by product category", "only delivered orders"]),
    ("shop", ["How many orders per status?"]),
    ("shop", ["Revenue by country this year"]),
    ("shop", ["Average order value by month last year"]),
    ("shop", ["Delete all cancelled orders"]),
    ("shop", ["Show the 10 latest orders"]),
    ("subs", ["Monthly revenue from invoices this year"]),
    ("subs", ["How many accounts per plan?"]),
    ("subs", ["How many churned accounts by country?"]),
    ("subs", ["Which plan has the most active accounts?"]),
]
PEOPLE_CONVERSATIONS = [
    ["Average salary by department"],
    ["How many employees were hired each year?"],
    ["Which department has the most employees?"],
    ["How many leave requests per type this year?", "only approved ones"],
    ["Highest salary in Engineering"],
    ["List active employees in London"],
]
TEMPLATES = [
    (
        "shop",
        "Monthly revenue",
        "Monthly revenue this year",
        "Revenue per month, this calendar year",
    ),
    ("shop", "Top customers", "Top 10 customers by total spend", "Who spends most, all time"),
    ("shop", "Orders by status", "How many orders per status?", "The order pipeline at a glance"),
    ("subs", "Accounts per plan", "How many accounts per plan?", "Plan mix of the customer base"),
]


def _env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} is not set (run the seed inside the Compose stack: make demo)")
    return value


async def _wipe(container: Container) -> None:
    async with container.db.sessionmaker() as session:
        for model in (
            UsageDaily,
            ConversationMessage,
            QueryExecution,
            Conversation,
            QueryTemplate,
            ApiKey,
            ProjectMember,
            Connection,
            Project,
            OrgMember,
            Organization,
        ):
            await session.execute(delete(model))
        await session.execute(delete(User).where(User.email.in_([p[0] for p in PEOPLE])))
        await session.commit()


async def _drain(container: Container) -> None:
    """Answer every queued question with the real worker pipeline."""
    while True:
        async with container.db.sessionmaker() as session:
            msg = await queue.claim(session, "demo-seed", container.settings.lease_s)
        if msg is None:
            return
        await answer(container, msg, "demo-seed")


async def _ask_all(
    container: Container, p: Principal, plan: list[tuple[Connection, list[str]]]
) -> None:
    for conn, questions in plan:
        conversation_id: uuid.UUID | None = None
        for q in questions:
            async with container.db.sessionmaker() as session:
                msg = await chat.ask(
                    container,
                    session,
                    p,
                    AskRequest(
                        question=q,
                        connection_id=None if conversation_id else conn.id,
                        conversation_id=conversation_id,
                        wait=0,
                    ),
                )
                conversation_id = msg.conversation_id
            await _drain(container)


async def _spread_project(
    session: Any, project_id: uuid.UUID, now: datetime, rng: random.Random
) -> None:
    """One project's conversations, oldest first, from 13 days ago to the last hour."""
    convs = (
        await session.scalars(
            select(Conversation)
            .where(Conversation.project_id == project_id)
            .order_by(Conversation.created_at)
        )
    ).all()
    n = len(convs)
    for i, c in enumerate(convs):
        age = timedelta(days=13 * (n - 1 - i) / max(n - 1, 1), minutes=rng.randint(30, 300))
        at = now - age
        c.created_at = at
        c.last_message_at = at + timedelta(minutes=3 * c.message_count)
        messages = (
            await session.scalars(
                select(ConversationMessage).where(ConversationMessage.conversation_id == c.id)
            )
        ).all()
        for m in messages:
            m.created_at = at + timedelta(minutes=2 * m.seq)
            m.finished_at = m.created_at + timedelta(seconds=2 + m.seq)
        await session.execute(
            update(QueryExecution)
            .where(QueryExecution.conversation_id == c.id)
            .values(created_at=at + timedelta(minutes=1))
        )


async def _spread(container: Container, project_ids: list[uuid.UUID]) -> None:
    """Spread the conversations over the last two weeks (newest last), then rebuild the
    daily usage rollups from what really ran, so the charts tell the same story."""
    rng = random.Random(5)
    now = datetime.now(UTC)
    async with container.db.sessionmaker() as session:
        for project_id in project_ids:
            await _spread_project(session, project_id, now, rng)
        await session.execute(delete(UsageDaily).where(UsageDaily.project_id.in_(project_ids)))
        await session.execute(
            text(
                """
                INSERT INTO usage_daily (project_id, day, connection_id, model, questions,
                    answered, refused, failed, executions, rows_returned, input_tokens,
                    output_tokens)
                SELECT m.project_id, (m.created_at AT TIME ZONE 'UTC')::date, m.connection_id,
                       coalesce(m.model, ''), count(*),
                       count(*) FILTER (WHERE m.status = 'answered'),
                       count(*) FILTER (WHERE m.status = 'refused'),
                       count(*) FILTER (WHERE m.status = 'failed'),
                       count(e.id) FILTER (WHERE e.status <> 'refused'),
                       coalesce(sum(e.row_count), 0), sum(m.input_tokens), sum(m.output_tokens)
                FROM conversation_messages m
                LEFT JOIN query_executions e ON e.id = m.execution_id
                WHERE m.project_id = ANY(:ids)
                GROUP BY 1, 2, 3, 4
                """
            ),
            {"ids": project_ids},
        )
        await session.commit()


async def run() -> None:
    settings = get_settings()
    import_all_models()
    password = _env("SQLAGENT_DEMO_PASSWORD")
    reader_password = _env("SQLAGENT_DEMO_READER_PASSWORD")
    pg_admin = _env("SQLAGENT_DEMO_SOURCE_PG_ADMIN")
    mysql_admin = _env("SQLAGENT_DEMO_SOURCE_MYSQL_ADMIN")
    mock_url = os.environ.get("SQLAGENT_DEMO_MOCK_URL", "http://mock-ai:5450")

    print(
        "building the demo databases (shop on PostgreSQL, people on MySQL, subscriptions on SQLite)"
    )
    await asyncio.to_thread(databases.build_shop, pg_admin, reader_password)
    await asyncio.to_thread(databases.build_people, mysql_admin, reader_password)
    work = Path(settings.work_dir)
    await asyncio.to_thread(work.mkdir, parents=True, exist_ok=True)
    sqlite_path = Path(tempfile.mkdtemp(dir=work)) / "subscriptions.sqlite"
    await asyncio.to_thread(databases.build_subscriptions, sqlite_path)

    container = Container.build(settings)
    try:
        await _wipe(container)
        async with container.db.sessionmaker() as session:
            users: dict[str, User] = {}
            for email, name, role in PEOPLE:
                user = User(
                    email=email,
                    name=name,
                    role="admin" if role == "admin" else "user",
                    password_hash=hash_password(password),
                )
                session.add(user)
                await session.flush()
                users[role] = user
            admin = users["admin"]
            actor = Actor(admin.id, admin.email, "user")
            org = await orgs.create_for(session, admin, "Acme Retail Group", actor)
            for role in ("editor", "viewer"):
                session.add(OrgMember(org_id=org.id, user_id=users[role].id, role="member"))
            row = await session.get(InstanceSettings, 1)
            if row is None:
                session.add(InstanceSettings(id=1, site_name="SQLAgent", allow_signup=False))
            retail = Project(
                org_id=org.id,
                name="Retail analytics",
                slug="retail-analytics",
                description="Sales, customers and subscriptions: the questions the business asks every week.",
                created_by=admin.id,
            )
            people = Project(
                org_id=org.id,
                name="People team",
                slug="people-team",
                description="Headcount, hiring, salaries and leave, read-only from the HR database.",
                created_by=admin.id,
            )
            session.add_all([retail, people])
            await session.flush()
            for project in (retail, people):
                session.add(ProjectMember(project_id=project.id, user_id=admin.id, role="admin"))
                session.add(
                    ProjectMember(project_id=project.id, user_id=users["editor"].id, role="editor")
                )
                session.add(
                    ProjectMember(project_id=project.id, user_id=users["viewer"].id, role="viewer")
                )
            await session.commit()
            retail_id, people_id = retail.id, people.id

        async def principal(project_id: uuid.UUID, user: User) -> Principal:
            async with container.db.sessionmaker() as s:
                project = await s.get(Project, project_id)
                assert project is not None
                return Principal(project, "admin", Actor(user.id, user.email, "user"))

        p_retail = await principal(retail_id, admin)
        p_people = await principal(people_id, admin)
        analyst = users["editor"]
        a_retail = await principal(retail_id, analyst)
        a_people = await principal(people_id, analyst)

        async with container.db.sessionmaker() as session:
            for p in (p_retail, p_people):
                await providers.create_provider(
                    container,
                    session,
                    p,
                    ProviderCreate(name="sqlagent-mock", kind="mock", is_default=True),
                )
                await providers.create_provider(
                    container,
                    session,
                    p,
                    ProviderCreate(
                        name="gateway",
                        kind="openai_compatible",
                        base_url=f"{mock_url}/v1",
                        api_key="demo-gateway-key",
                        model="mock-sql-small",
                    ),
                )

        def server(name: str, url: str, kind: str, description: str) -> ServerConnection:
            from urllib.parse import urlsplit

            parts = urlsplit(url)
            return ServerConnection(
                name=name,
                kind=kind,
                host=parts.hostname or "",
                port=parts.port,
                database=parts.path.lstrip("/"),
                username=databases.READER,
                password=reader_password,
                ssl_mode="disable",
                sample_values=True,
                description=description,
                max_rows=1000,
                max_scan_rows=5_000_000,
                timeout_s=20,
            )

        async with container.db.sessionmaker() as session:
            shop = await connections.create_server(
                container,
                session,
                p_retail,
                server(
                    "Shop (PostgreSQL)",
                    pg_admin,
                    "postgresql",
                    "Online store: orders, customers, products",
                ),
            )
            people_conn = await connections.create_server(
                container,
                session,
                p_people,
                server("People (MySQL)", mysql_admin, "mysql", "HR: departments, employees, leave"),
            )

            class _Upload:
                filename = "subscriptions.sqlite"

                def __init__(self, path: Path) -> None:
                    self._f = path.open("rb")

                async def read(self, size: int) -> bytes:
                    return self._f.read(size)

            from sqlagent.connections.schemas import Limits

            subs = await connections.create_sqlite(
                container,
                session,
                p_retail,
                "Subscriptions (SQLite)",
                _Upload(sqlite_path),  # type: ignore[arg-type]
                Limits(max_rows=1000, max_scan_rows=5_000_000, timeout_s=20),
                sample_values=True,
                description="SaaS plans, accounts and invoices",
            )
            for conn in (shop, people_conn, subs):
                await schemas.refresh(
                    container, session, conn, Actor(admin.id, admin.email, "user")
                )
                result = await connections.test(container, conn)
                await connections.record_test(session, conn, result)

        by_key = {"shop": shop, "subs": subs}
        await _ask_all(container, a_retail, [(by_key[k], qs) for k, qs in RETAIL_CONVERSATIONS[:6]])
        await _ask_all(container, p_retail, [(by_key[k], qs) for k, qs in RETAIL_CONVERSATIONS[6:]])
        await _ask_all(container, a_people, [(people_conn, qs) for qs in PEOPLE_CONVERSATIONS])

        async with container.db.sessionmaker() as session:
            for key, name, question, description in TEMPLATES:
                await templates.create(
                    session,
                    p_retail,
                    TemplateCreate(
                        connection_id=by_key[key].id,
                        name=name,
                        question=question,
                        description=description,
                    ),
                )
            await templates.create(
                session,
                p_people,
                TemplateCreate(
                    connection_id=people_conn.id,
                    name="Salary by department",
                    question="Average salary by department",
                    description="Pay bands across the company",
                ),
            )
            api_key = generate_api_key(settings.api_key_pepper)
            session.add(
                ApiKey(
                    project_id=retail_id,
                    name="Weekly report (CI)",
                    prefix=api_key.prefix,
                    secret_hash=api_key.secret_hash,
                    scopes=["read", "query"],
                    created_by=admin.id,
                )
            )
            await session.commit()
        # The saved questions get asked again, as a team would during a normal week.
        async with container.db.sessionmaker() as session:
            saved = (await session.scalars(select(QueryTemplate))).all()
        for t in saved:
            p = a_retail if t.project_id == retail_id else a_people
            for _ in range(2):
                async with container.db.sessionmaker() as session:
                    tpl = await session.get(QueryTemplate, t.id)
                    assert tpl is not None
                    await templates.run(container, session, p, tpl)
                await _drain(container)
        await _spread(container, [retail_id, people_id])
        async with container.db.sessionmaker() as session:
            counts: dict[str, Any] = {
                "conversations": await session.scalar(
                    select(func.count()).select_from(Conversation)
                ),
                "questions": await session.scalar(
                    select(func.count()).select_from(ConversationMessage)
                ),
                "queries": await session.scalar(select(func.count()).select_from(QueryExecution)),
            }
    finally:
        await container.close()

    print()
    print("Demo ready: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    print("Sign in with any of these (same password):")
    for email, name, role in PEOPLE:
        print(f"  {email:<26} {name:<12} {role}")
    print(f"  password: {password}")
    print(
        f"An API key for the SDK and CLI (project Retail analytics, read and query): {api_key.plaintext}"
    )
