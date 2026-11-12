"""Who may do what in a project. Every project route resolves a ``Principal`` first.

The project comes from the path (``/projects/{project_id}/...``), from the API key (a key
belongs to one project), or from the ``X-Project-Id`` header.

People hold a project role (viewer < editor < admin). Owners and admins of the project's
organization, and instance admins, act as project admins. Viewers read connections,
schemas, conversations and results; editors also ask questions, run SQL and manage
connections and templates; admins also manage members, API keys, model providers and read
the audit log. API keys carry scopes:

* ``read``: everything a viewer sees
* ``query``: ask questions, generate, validate, explain and execute SQL
* ``manage``: create and change connections and templates (connections as code from CI)

A project the caller cannot see answers 404, never 403, so its existence does not leak.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sqlagent.audit.service import Actor
from sqlagent.auth.dependencies import api_key_from, current_user
from sqlagent.core.deps import ContainerDep, SessionDep, client_ip
from sqlagent.core.errors import (
    AppError,
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
)
from sqlagent.core.security import constant_time_equals, hash_key_secret, parse_api_key
from sqlagent.orgs import service as orgs
from sqlagent.projects.models import ApiKey, Project, ProjectMember

ROLE_RANK = {"viewer": 0, "editor": 1, "admin": 2}
SCOPES = ("read", "query", "manage")
PROJECT_HEADER = "x-project-id"
_TOUCH_EVERY = timedelta(minutes=5)


@dataclass(frozen=True)
class Principal:
    project: Project
    role: str  # viewer, editor, admin
    actor: Actor
    key: ApiKey | None = None

    @property
    def project_id(self) -> uuid.UUID:
        return self.project.id

    @property
    def org_id(self) -> uuid.UUID:
        return self.project.org_id

    @property
    def user_id(self) -> uuid.UUID | None:
        return None if self.key is not None else self.actor.id

    def at_least(self, role: str) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]

    def has_scope(self, scope: str) -> bool:
        return self.key is None or scope in (self.key.scopes or [])

    def audit_scope(self) -> dict[str, uuid.UUID]:
        """The tenant columns for an audit row written on this principal's behalf."""
        return {"org_id": self.org_id, "project_id": self.project_id}


async def _key(request: Request, session: AsyncSession, raw: str, pepper: str) -> ApiKey:
    parsed = parse_api_key(raw)
    if parsed is None:
        raise AuthenticationError("The API key is malformed", code="invalid_api_key")
    prefix, secret = parsed
    key = await session.scalar(select(ApiKey).where(ApiKey.prefix == prefix))
    if (
        key is None
        or key.revoked_at is not None
        or not constant_time_equals(key.secret_hash, hash_key_secret(secret, pepper))
    ):
        raise AuthenticationError("The API key is not valid", code="invalid_api_key")
    now = datetime.now(UTC)
    if key.last_used_at is None or now - key.last_used_at > _TOUCH_EVERY:
        await session.execute(update(ApiKey).where(ApiKey.id == key.id).values(last_used_at=now))
        await session.commit()
    request.state.actor = Actor(None, f"api-key:{key.name}", "api_key", client_ip(request))
    return key


def _header_project(request: Request) -> uuid.UUID | None:
    raw = request.headers.get(PROJECT_HEADER)
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise NotFoundError("Project not found") from None


async def resolve(
    request: Request,
    container: ContainerDep,
    session: SessionDep,
    project_id: uuid.UUID | None,
) -> Principal:
    raw_key = api_key_from(request)
    if raw_key:
        key = await _key(request, session, raw_key, container.settings.api_key_pepper)
        wanted = project_id or _header_project(request) or key.project_id
        if wanted != key.project_id:
            # A key for another project: the same answer as a project that does not exist.
            raise NotFoundError("Project not found")
        project = await session.get(Project, key.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        role = "editor" if "manage" in (key.scopes or []) else "viewer"
        return Principal(project, role, request.state.actor, key)
    user = await current_user(request, container, session)
    chosen = project_id or _header_project(request)
    if chosen is None:
        raise AppError(
            "Choose a project: send its id in the X-Project-Id header, or use a project API key",
            code="project_required",
        )
    project = await session.get(Project, chosen)
    if project is None:
        raise NotFoundError("Project not found")
    org_role = await orgs.role_in(session, user, project.org_id)
    if org_role in ("owner", "admin"):
        role = "admin"
    else:
        member = await session.get(ProjectMember, (project.id, user.id)) if org_role else None
        if member is None:
            raise NotFoundError("Project not found")
        role = member.role
    return Principal(project, role, request.state.actor)


def project_role(role: str, scope: str = "read") -> Callable[..., Coroutine[Any, Any, Principal]]:
    """A dependency: the caller holds at least ``role`` in the project (people) or the
    ``scope`` (API keys). The project comes from a ``project_id`` path parameter when the
    route has one, else from the API key or the ``X-Project-Id`` header."""

    async def dependency(
        request: Request, container: ContainerDep, session: SessionDep
    ) -> Principal:
        raw = request.path_params.get("project_id")
        try:
            path_project = uuid.UUID(str(raw)) if raw else None
        except ValueError:
            raise NotFoundError("Project not found") from None
        p = await resolve(request, container, session, path_project)
        if p.key is not None:
            if scope not in (p.key.scopes or []):
                raise PermissionDeniedError(
                    f"This API key lacks the {scope!r} scope", code="insufficient_scope"
                )
            return p
        if not p.at_least(role):
            raise PermissionDeniedError(
                f"This action needs the {role} role in this project", code="insufficient_role"
            )
        return p

    return dependency


Viewer = Annotated[Principal, Depends(project_role("viewer", "read"))]
Editor = Annotated[Principal, Depends(project_role("editor", "manage"))]
Admin = Annotated[Principal, Depends(project_role("admin", "__admin_only__"))]
Querier = Annotated[Principal, Depends(project_role("editor", "query"))]
