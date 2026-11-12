"""The audit trail: per project (project admins), per organization (organization admins),
whole instance (instance admins). Every question asked and every query run or refused is in
it, with its SQL, status, row count and who ran it."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query

from sqlagent.audit import service
from sqlagent.auth.dependencies import Admin, CurrentUser
from sqlagent.core.deps import SessionDep
from sqlagent.core.schemas import ApiModel, Page, decode_cursor, encode_cursor
from sqlagent.orgs import service as orgs
from sqlagent.projects.access import Admin as ProjectAdmin

router = APIRouter(prefix="/api/v1", tags=["audit"])


class AuditOut(ApiModel):
    id: int
    at: datetime
    actor_id: uuid.UUID | None
    actor_email: str | None
    action: str
    target_type: str | None
    target_id: str | None
    details: dict[str, Any]
    ip: str | None
    org_id: uuid.UUID | None
    project_id: uuid.UUID | None


async def _page(
    session: SessionDep,
    cursor: str | None,
    limit: int,
    action: str | None,
    **scope: uuid.UUID | None,
) -> Page[AuditOut]:
    after = decode_cursor(cursor)
    rows = await service.list_entries(
        session, int(after) if after and after.isdigit() else None, limit, action, **scope
    )
    return Page[AuditOut](
        items=[AuditOut.model_validate(r) for r in rows[:limit]],
        next_cursor=encode_cursor(rows[limit - 1].id) if len(rows) > limit else None,
    )


@router.get(
    "/projects/{project_id}/audit-logs",
    response_model=Page[AuditOut],
    summary="The project's append-only audit log (project admins)",
    description="Filter by `connection_id` (every query run against one database) or "
    "`actor_id` (one person's questions and queries), and by action prefix (`query.`).",
)
async def project_audit(
    p: ProjectAdmin,
    session: SessionDep,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    action: str | None = None,
    connection_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> Page[AuditOut]:
    return await _page(
        session,
        cursor,
        limit,
        action,
        project_id=p.project_id,
        connection_id=connection_id,
        actor_id=actor_id,
    )


@router.get(
    "/orgs/{org_id}/audit-logs",
    response_model=Page[AuditOut],
    summary="The organization's audit log (admins)",
)
async def org_audit(
    org_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    action: str | None = None,
) -> Page[AuditOut]:
    org, _ = await orgs.get_for(session, user, org_id, "admin")
    return await _page(session, cursor, limit, action, org_id=org.id)


@router.get(
    "/audit", response_model=Page[AuditOut], summary="The whole instance's audit log (admins)"
)
async def instance_audit(
    _: Admin,
    session: SessionDep,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    action: str | None = None,
) -> Page[AuditOut]:
    return await _page(session, cursor, limit, action)
