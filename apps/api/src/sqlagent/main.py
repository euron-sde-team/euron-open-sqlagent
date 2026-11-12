"""API application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from sqlagent import __version__
from sqlagent.audit.router import router as audit_router
from sqlagent.auth.router import router as auth_router
from sqlagent.charts.router import router as charts_router
from sqlagent.chat.router import router as chat_router
from sqlagent.connections.router import router as connections_router
from sqlagent.core.config import Settings, get_settings
from sqlagent.core.container import Container
from sqlagent.core.db import import_all_models
from sqlagent.core.errors import install_error_handlers
from sqlagent.core.logs import configure_logging
from sqlagent.core.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from sqlagent.core.tracing import configure_tracing
from sqlagent.executions.router import router as executions_router
from sqlagent.instance.router import router as instance_router
from sqlagent.orgs.router import router as orgs_router
from sqlagent.overview.router import router as overview_router
from sqlagent.projects.router import router as projects_router
from sqlagent.providers.router import router as providers_router
from sqlagent.sql.router import router as sql_router
from sqlagent.system.router import router as system_router
from sqlagent.templates.router import router as templates_router
from sqlagent.usage.router import router as usage_router
from sqlagent.users.router import router as users_router

DESCRIPTION = """
API of a self-hosted database assistant: connect PostgreSQL, MySQL or SQLite, ask a question
in plain English, and get one validated, read-only SQL query, its result as a table or a
chart, and a plain-language explanation. Every query passes the SQL guard (exactly one
read-only SELECT) and runs on a connection the database itself holds read-only.

* People sign in with `POST /api/v1/auth/login` and send the session token as
  `Authorization: Bearer <token>` (the dashboard uses an HttpOnly cookie instead).
* Applications, the SDK and the CLI use a project API key: `Authorization: Bearer sqa_...`
  or `X-API-Key: sqa_...`. Scopes: `read`, `query`, `manage`.
* `POST /api/v1/projects/{project_id}/chat` asks a question and waits for the answer;
  `POST .../sql/explain` explains any query without running it.
"""


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    import_all_models()
    configure_logging(settings.log_level)
    configure_tracing(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or Container.build(settings)
        try:
            yield
        finally:
            if container is None:
                await app.state.container.close()

    app = FastAPI(
        title="Euron Open SQLAgent",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        separate_input_output_schemas=False,
    )
    install_error_handlers(app)
    for router in (
        auth_router,
        users_router,
        instance_router,
        orgs_router,
        projects_router,
        providers_router,
        connections_router,
        chat_router,
        sql_router,
        executions_router,
        charts_router,
        templates_router,
        overview_router,
        usage_router,
        audit_router,
        system_router,
    ):
        app.include_router(router)

    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "authorization",
            "content-type",
            "x-sqa-csrf",
            "x-api-key",
            "x-project-id",
            "x-request-id",
        ],
        expose_headers=["x-request-id", "retry-after", "content-disposition"],
        max_age=600,
    )
    app.add_middleware(BodySizeLimitMiddleware, settings=settings)
    app.add_middleware(RequestContextMiddleware)
    return app
