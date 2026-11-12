from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from sqlagent.core.schemas import ApiModel
from sqlagent.executions.schemas import ExecutionOut, RowsPage


class AskRequest(ApiModel):
    question: str = Field(min_length=1, max_length=4000)
    # A new conversation needs the connection; a follow-up names its conversation.
    connection_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    provider_id: uuid.UUID | None = Field(
        None, description="Ask this provider instead of the project's default"
    )
    wait: float = Field(
        30.0, ge=0, le=120, description="Seconds to wait for the answer before returning"
    )
    page_size: int = Field(50, ge=1, le=1000)


class MessageOut(ApiModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    connection_id: uuid.UUID
    seq: int
    question: str
    status: str = Field(description="queued, running, answered, refused, failed or no_answer")
    sql: str | None
    explanation: str | None
    error: str | None
    error_code: str | None
    # True when the guard accepted the SQL (shown as the validated read-only badge).
    validated: bool
    provider_name: str | None
    model: str | None
    input_tokens: int
    output_tokens: int
    model_ms: float
    total_ms: float
    template_id: uuid.UUID | None
    actor_label: str
    created_at: datetime
    finished_at: datetime | None
    execution: ExecutionOut | None = None
    # The first page of the result, when there is one.
    page: RowsPage | None = None


class ConversationOut(ApiModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    connection_name: str
    title: str
    message_count: int
    last_message_at: datetime
    created_by_label: str
    created_at: datetime
    last_status: str | None = None


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class ConversationUpdate(ApiModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationPage(ApiModel):
    items: list[ConversationOut]
    next_cursor: str | None = None


def page_dict(page: RowsPage | None) -> dict[str, Any] | None:
    return page.model_dump() if page else None
