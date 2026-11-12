from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from sqlagent.core.net import as_ip, canonical_host, is_forbidden_ip
from sqlagent.core.schemas import ApiModel

ServerKind = Literal["postgresql", "mysql"]
ConnectionKind = Literal["postgresql", "mysql", "sqlite"]
SslMode = Literal["disable", "prefer", "require", "verify-full"]


def _host(v: str) -> str:
    host = canonical_host(v)
    if not host or any(c in host for c in "/?#@ "):
        raise ValueError("enter a host name or IP address, without a scheme or path")
    ip = as_ip(host)
    if ip is not None and is_forbidden_ip(ip):
        raise ValueError("link-local and instance metadata addresses are not allowed")
    return host


class Limits(ApiModel):
    max_rows: int = Field(1000, ge=1, le=100_000, description="Rows a result may return")
    max_scan_rows: int = Field(
        10_000_000,
        ge=1,
        le=10_000_000_000,
        description="Rows the database's planner may expect to read; bigger plans are refused",
    )
    timeout_s: int = Field(30, ge=1, le=600, description="Seconds a statement may run")


class ServerConnection(Limits):
    """A database server. The password is write-only: it is sealed and never returned."""

    name: str = Field(min_length=1, max_length=120)
    kind: ServerKind
    host: str = Field(min_length=1, max_length=255)
    port: int | None = Field(None, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    password: str | None = Field(None, max_length=1000)
    ssl_mode: SslMode = "prefer"
    default_schema: str | None = Field(None, max_length=128)
    sample_values: bool = False
    description: str = Field("", max_length=2000)

    @field_validator("host")
    @classmethod
    def _check_host(cls, v: str) -> str:
        return _host(v)


class ConnectionUpdate(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    host: str | None = Field(None, min_length=1, max_length=255)
    port: int | None = Field(None, ge=1, le=65535)
    database: str | None = Field(None, min_length=1, max_length=128)
    username: str | None = Field(None, min_length=1, max_length=128)
    # A new password replaces the sealed one; omit it to keep the current one.
    password: str | None = Field(None, max_length=1000)
    ssl_mode: SslMode | None = None
    default_schema: str | None = Field(None, max_length=128)
    max_rows: int | None = Field(None, ge=1, le=100_000)
    max_scan_rows: int | None = Field(None, ge=1, le=10_000_000_000)
    timeout_s: int | None = Field(None, ge=1, le=600)
    sample_values: bool | None = None
    description: str | None = Field(None, max_length=2000)

    @field_validator("host")
    @classmethod
    def _check(cls, v: str | None) -> str | None:
        return _host(v) if v is not None else None


class ConnectionOut(ApiModel):
    id: uuid.UUID
    name: str
    kind: ConnectionKind
    description: str
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    ssl_mode: str | None = None
    default_schema: str | None = None
    # Never the password: only whether one is stored.
    has_password: bool = False
    file_name: str | None = None
    file_size: int | None = None
    max_rows: int
    max_scan_rows: int
    timeout_s: int
    sample_values: bool
    last_tested_at: datetime | None
    last_test_ok: bool | None
    last_test_message: str | None
    server_version: str | None
    tables: int | None = None
    schema_refreshed_at: datetime | None = None
    conversations: int = 0
    created_at: datetime


class TestResult(ApiModel):
    ok: bool
    message: str
    server_version: str | None = None
    tables: int | None = None
    # Round trip of the connection test (connect, version, list tables), measured.
    latency_ms: float
    read_only: bool | None = Field(
        None, description="Whether the database confirmed the session is read-only"
    )
