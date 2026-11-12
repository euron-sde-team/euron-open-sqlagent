from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from sqlagent.core.schemas import ApiModel, Email

ProjectRole = Literal["viewer", "editor", "admin"]
Scope = Literal["read", "query", "manage"]


class ProjectCreate(ApiModel):
    # The organization it belongs to (you need the admin role there).
    org_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(None, max_length=64, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    description: str = Field("", max_length=2000)


class ProjectUpdate(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)


class ProjectOut(ApiModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    slug: str
    description: str
    created_at: datetime
    role: ProjectRole = "viewer"
    connections: int = 0
    # Questions asked in the last 24 hours.
    questions_24h: int = 0


class MemberOut(ApiModel):
    user_id: uuid.UUID
    email: str
    name: str
    role: ProjectRole
    created_at: datetime


class MemberAdd(ApiModel):
    email: Email
    role: ProjectRole = "viewer"


class MemberUpdate(ApiModel):
    role: ProjectRole


def _default_scopes() -> list[Scope]:
    return ["read", "query"]


class ApiKeyCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[Scope] = Field(default_factory=_default_scopes, min_length=1)

    @field_validator("scopes")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        return sorted(set(v))


class ApiKeyOut(ApiModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    key: str = Field(description="Shown once. Store it now; only a hash is kept")
