"""Runtime configuration, validated once at boot.

Every setting comes from the environment and is read here only. The API, the question
worker and the scheduler share one ``Settings``. Security-relevant settings are checked by
``guard()`` so a misconfigured production deployment refuses to start instead of running
with demo secrets.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

INSECURE_SECRETS = {"", "change-me", "replace-with-output-of-make-env", "dev", "secret"}


def _split(v: object) -> object:
    if isinstance(v, str):
        return [item.strip() for item in v.split(",") if item.strip()]
    return v


def _insecure(value: str) -> bool:
    return value in INSECURE_SECRETS or "not-for-production" in value or len(value) < 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    cloud: Literal["local", "floci", "aws"] = Field("local", alias="SQLAGENT_CLOUD")

    database_url: str = "postgresql+asyncpg://sqlagent:sqlagent@localhost:5442/sqlagent"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    # Rate limits and caches. Optional: without it they live in process (one replica).
    redis_url: str = ""
    memory_cache_max_bytes: int = Field(64_000_000, ge=1_000_000)

    session_secret: str = "dev-session-secret-not-for-production"  # noqa: S105 dev default, refused in production by guard()
    api_key_pepper: str = "dev-api-key-pepper-not-for-production"
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5410"]
    )
    # Where people open the app; used in links.
    public_url: str = "http://localhost:5410"

    # Connection passwords and provider keys are sealed before storage.
    key_mode: Literal["local", "kms"] = "local"
    local_master_key: str = "dev-local-master-key-not-for-production"
    kms_key_id: str = "alias/sqlagent-local"

    aws_region: str = "us-east-1"
    aws_endpoint_url: str | None = None
    s3_force_path_style: bool = False
    # Uploaded SQLite databases and query result snapshots (the pages and CSV exports are
    # read from them). Rows keep only the key.
    objects_bucket: str = "sqlagent-local-objects"
    storage: Literal["local", "s3"] = "local"
    local_storage_dir: str = "./.data/objects"

    # Mail for invitations and notices: "log" (development), "smtp" (Mailpit locally, any
    # relay), "ses" (AWS).
    mail_backend: Literal["log", "smtp", "ses"] = "log"
    mail_from: str = "SQLAgent <sqlagent@sqlagent.local>"
    smtp_host: str = "localhost"
    smtp_port: int = Field(1025, ge=1, le=65535)

    # Connected databases usually live on private networks, so private hosts are allowed;
    # link-local and instance metadata addresses never are.
    source_allow_private: bool = True
    # Model providers on private networks (a local Ollama or vLLM) are normal.
    provider_allow_private: bool = True
    max_upload_bytes: int = Field(200_000_000, ge=1_000_000)
    work_dir: str = "./.data/work"

    # Ceilings that a connection's own limits can never exceed.
    max_rows_ceiling: int = Field(100_000, ge=10)
    max_timeout_ceiling_s: int = Field(600, ge=1, le=3600)
    # Schema discovery: at most this many tables are read per connection.
    schema_max_tables: int = Field(2_000, ge=10, le=50_000)
    # The schema part of a prompt stays under this many characters (the most relevant
    # tables first).
    prompt_schema_chars: int = Field(24_000, ge=2_000, le=400_000)
    # Prior turns of a conversation given to the model for follow-up questions.
    history_turns: int = Field(6, ge=0, le=50)
    # Cached schemas are rediscovered by the scheduler when older than this.
    schema_refresh_hours: float = Field(24.0, gt=0, le=24 * 30)

    # The question worker.
    worker_concurrency: int = Field(8, ge=1, le=256)
    lease_s: float = Field(60.0, ge=10, le=3600)
    max_attempts: int = Field(3, ge=1, le=20)
    worker_poll_interval_s: float = Field(2.0, gt=0, le=60)
    task_interval_s: float = Field(10.0, gt=0, le=600)
    worker_metrics_port: int = Field(9464, ge=0, le=65535)
    # Model calls: per request timeout (the provider's own timeout is capped by it).
    model_timeout_s: float = Field(120.0, gt=0, le=1800)

    # Questions per minute per project.
    question_rpm: int = Field(120, ge=1)
    max_body_bytes: int = 2_000_000
    otel_enabled: bool = False
    # Conversations, executions and result snapshots older than this are purged.
    retention_days: int = Field(90, ge=1)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        return _split(v)

    @property
    def cache_backend(self) -> Literal["redis", "memory"]:
        return "redis" if self.redis_url else "memory"

    def guard(self) -> None:
        """Refuse to boot in production with demo secrets or unsafe options."""
        if self.environment != "production":
            return
        names = ("session_secret", "api_key_pepper")
        problems: list[str] = [
            f"{name.upper()} must be a random value of at least 32 chars"
            for name in names
            if _insecure(getattr(self, name))
        ]
        if self.key_mode == "local" and _insecure(self.local_master_key):
            problems.append("LOCAL_MASTER_KEY must be set (or use KEY_MODE=kms)")
        secrets = [getattr(self, n) for n in names]
        if len(set(secrets)) != len(secrets):
            problems.append("SESSION_SECRET and API_KEY_PEPPER must differ")
        if self.cloud == "aws" and self.aws_endpoint_url:
            problems.append("AWS_ENDPOINT_URL must be unset when SQLAGENT_CLOUD=aws")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
        if self.mail_backend == "log":
            problems.append("MAIL_BACKEND must be smtp or ses in production")
        if self.storage == "local":
            problems.append(
                "STORAGE must be s3 in production (several replicas share result snapshots)"
            )
        if problems:
            raise RuntimeError("unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.guard()
    return settings
