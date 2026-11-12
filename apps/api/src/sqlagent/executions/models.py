"""Every query SQLAgent ran, or refused to run, against a connected database."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from sqlagent.core.db import Base, new_id

EXECUTION_STATUSES = ("succeeded", "refused", "failed", "timeout", "scan_limit")


class QueryExecution(Base):
    """One query against one connection. A refused query is recorded too (it never reached
    the database). The result itself is a snapshot in object storage (``result_key``):
    the row keeps only its shape, so pages and CSV exports read the snapshot and the
    customer's database is queried exactly once per execution."""

    __tablename__ = "query_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'refused', 'failed', 'timeout', 'scan_limit')",
            name="ck_query_executions_status",
        ),
        CheckConstraint("source IN ('chat', 'sql', 'template')", name="ck_query_executions_source"),
        Index("ix_query_executions_project_created", "project_id", "created_at"),
        Index("ix_query_executions_connection_created", "connection_id", "created_at"),
        Index("ix_query_executions_actor", "project_id", "actor_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    sql: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # The database planner's own estimate of rows read, when it gave one.
    estimated_scan_rows: Mapped[int | None] = mapped_column(BigInteger)
    # [{"name", "kind"}] of the result, and the chart that fits it (if any).
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    chart: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result_key: Mapped[str | None] = mapped_column(String(300))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_label: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
