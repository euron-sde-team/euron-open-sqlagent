from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from sqlagent.core.schemas import ApiModel


class TemplateCreate(ApiModel):
    connection_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=4000)
    sql: str | None = Field(
        None, max_length=100_000, description="Keep this checked SQL and run it as is"
    )
    description: str = Field("", max_length=2000)


class TemplateFromMessage(ApiModel):
    message_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    keep_sql: bool = Field(True, description="Save the answered SQL with the question")
    description: str = Field("", max_length=2000)


class TemplateUpdate(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    question: str | None = Field(None, min_length=1, max_length=4000)
    sql: str | None = Field(None, max_length=100_000)
    description: str | None = Field(None, max_length=2000)


class TemplateOut(ApiModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    connection_name: str
    name: str
    question: str
    sql: str | None
    description: str
    use_count: int
    created_at: datetime


class TemplateRun(ApiModel):
    wait: float = Field(30.0, ge=0, le=120)
