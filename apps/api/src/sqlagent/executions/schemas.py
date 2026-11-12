from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from sqlagent.charts.suggest import ChartSuggestion, ColumnIn
from sqlagent.core.schemas import ApiModel


class ExecutionOut(ApiModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    conversation_id: uuid.UUID | None
    source: str
    sql: str
    status: str
    error: str | None
    error_code: str | None
    row_count: int
    truncated: bool = Field(description="True when the connection's row limit cut the result")
    duration_ms: float
    estimated_scan_rows: int | None
    columns: list[ColumnIn]
    chart: ChartSuggestion | None
    actor_id: uuid.UUID | None
    actor_label: str
    created_at: datetime


class RowsPage(ApiModel):
    execution_id: uuid.UUID
    columns: list[ColumnIn]
    rows: list[list[Any]]
    offset: int
    limit: int
    total: int


class ExecutionWithRows(ExecutionOut):
    # The first page of the result.
    page: RowsPage | None = None


class ExecuteRequest(ApiModel):
    connection_id: uuid.UUID
    sql: str = Field(min_length=1, max_length=100_000)
    page_size: int = Field(50, ge=1, le=1000)
