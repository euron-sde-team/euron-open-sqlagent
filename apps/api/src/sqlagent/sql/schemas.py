from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field, model_validator

from sqlagent.core.schemas import ApiModel

Dialect = Literal["postgresql", "mysql", "sqlite"]


class GenerateRequest(ApiModel):
    connection_id: uuid.UUID
    question: str = Field(min_length=1, max_length=4000)
    provider_id: uuid.UUID | None = None


class GenerateOut(ApiModel):
    sql: str | None
    explanation: str
    valid: bool = Field(description="True when the SQL guard accepts the query as read-only")
    refusal: str | None = None
    refusal_code: str | None = None
    tables: list[str] = Field(default_factory=list)
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    model_ms: float


class SqlInput(ApiModel):
    """A query, and where it would run: a connection (its dialect) or a bare dialect."""

    sql: str = Field(min_length=1, max_length=100_000)
    connection_id: uuid.UUID | None = None
    dialect: Dialect | None = None

    @model_validator(mode="after")
    def _target(self) -> SqlInput:
        if self.connection_id is None and self.dialect is None:
            raise ValueError("give a connection_id or a dialect")
        return self


class Validation(ApiModel):
    valid: bool
    dialect: str
    reason: str | None = None
    code: str | None = None
    sql: str | None = Field(None, description="The accepted query, as it would run")
    tables: list[str] = Field(default_factory=list)


class ExplainRequest(SqlInput):
    provider_id: uuid.UUID | None = None
    use_model: bool = Field(
        True, description="Ask the model; false explains from the syntax tree alone"
    )


class Analysis(ApiModel):
    statement: str
    read_only: bool
    refusal: str | None = None
    refusal_code: str | None = None
    tables: list[str] = Field(default_factory=list)
    joins: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    aggregates: list[str] = Field(default_factory=list)
    order_by: list[str] = Field(default_factory=list)
    limit: int | None = None
    ctes: list[str] = Field(default_factory=list)
    window_functions: int = 0
    subqueries: int = 0
    columns: list[str] = Field(default_factory=list)


class ExplainOut(ApiModel):
    explanation: str
    source: Literal["model", "syntax"]
    model: str
    analysis: Analysis
    executed: bool = Field(False, description="Always false: explaining never runs the query")
