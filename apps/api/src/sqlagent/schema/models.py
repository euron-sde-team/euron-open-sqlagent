"""The cached schema of each connection: discovered from the database itself, refreshed on
a schedule and on demand, and the source of every prompt the model sees."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from sqlagent.core.db import Base


class SchemaCache(Base):
    __tablename__ = "schema_cache"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connections.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Tables with columns, keys, indexes and row counts (``schema.schemas.SchemaTable``).
    # Capped at SCHEMA_MAX_TABLES tables, so the row stays small; reads go through the
    # cache (``schema.service.load``) and only touch this column on a miss.
    tables: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    table_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    # The last refresh's failure, if it failed (the previous schema stays in use).
    last_error: Mapped[str | None] = mapped_column(Text)
