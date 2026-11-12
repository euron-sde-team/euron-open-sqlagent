from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from sqlagent.core.schemas import ApiModel


class SchemaColumn(ApiModel):
    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False
    # Present only when the connection allows sampling: the distinct values of a low
    # cardinality text column, most frequent first.
    sample_values: list[str] = Field(default_factory=list)


class SchemaForeignKey(ApiModel):
    columns: list[str]
    ref_table: str
    ref_columns: list[str]


class SchemaIndex(ApiModel):
    name: str
    columns: list[str]
    unique: bool


class SchemaTable(ApiModel):
    schema_name: str | None = Field(None, description="The database schema; none on SQLite")
    name: str
    kind: str
    row_count: int | None = None
    columns: list[SchemaColumn] = Field(default_factory=list)
    foreign_keys: list[SchemaForeignKey] = Field(default_factory=list)
    indexes: list[SchemaIndex] = Field(default_factory=list)

    @property
    def qualified(self) -> str:
        return f"{self.schema_name}.{self.name}" if self.schema_name else self.name


class SchemaOut(ApiModel):
    connection_id: uuid.UUID
    dialect: str
    tables: list[SchemaTable]
    table_count: int
    column_count: int
    refreshed_at: datetime
    duration_ms: float
    last_error: str | None = None
