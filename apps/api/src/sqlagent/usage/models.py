"""Daily usage rollups: one row per project, day, connection and model, incremented as
questions are answered and queries run, so the usage report never scans raw history."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from sqlagent.core.db import Base


class UsageDaily(Base):
    __tablename__ = "usage_daily"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connections.id", ondelete="CASCADE"), primary_key=True
    )
    # "" for queries run directly (no model involved).
    model: Mapped[str] = mapped_column(String(260), primary_key=True, default="")
    questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    answered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refused: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    executions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_returned: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
