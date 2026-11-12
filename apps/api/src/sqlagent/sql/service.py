"""Text to SQL: generate a query from a question against the real schema, explain any
query in plain language, validate a query with the guard. None of these executes anything;
execution is ``executions.service.execute`` alone."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from sqlagent.connections.models import Connection
from sqlagent.core.container import Container
from sqlagent.core.errors import AppError
from sqlagent.observability import metrics
from sqlagent.providers import gateway
from sqlagent.providers import service as providers
from sqlagent.providers.models import ModelProvider
from sqlagent.providers.types import Message, ModelRequest, ProviderError, Usage
from sqlagent.schema import service as schemas
from sqlagent.sql import guard, prompt
from sqlagent.sql.describe import analyze, describe
from sqlagent.sql.schemas import Analysis, ExplainOut, Validation

log = logging.getLogger("sqlagent.sql")


@dataclass
class Generation:
    sql: str | None
    explanation: str
    valid: bool
    refusal: str | None
    refusal_code: str | None
    tables: list[str] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    usage: Usage = field(default_factory=Usage)
    model_ms: float = 0.0
    prompt_tables: int = 0


async def provider_for(
    session: AsyncSession, project_id: uuid.UUID, provider_id: uuid.UUID | None
) -> ModelProvider:
    if provider_id is not None:
        row = await providers.get_provider(session, project_id, provider_id)
        if not row.enabled:
            raise AppError("That model provider is turned off", code="provider_disabled")
        return row
    return await providers.default_provider(session, project_id)


async def _call(
    container: Container, provider: ModelProvider, messages: tuple[Message, ...], max_tokens: int
) -> tuple[str, Usage, float]:
    adapter = await gateway.adapter(container, provider)
    started = time.perf_counter()
    try:
        response = await gateway.complete(
            adapter,
            ModelRequest(
                model=provider.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.0,
                stream=False,
            ),
        )
    except ProviderError as exc:
        metrics.MODEL_CALLS.labels(provider.kind, "error").inc()
        raise AppError(exc.message, code=exc.code) from exc
    elapsed = time.perf_counter() - started
    metrics.MODEL_CALLS.labels(provider.kind, "ok").inc()
    metrics.MODEL_LATENCY.labels(provider.kind).observe(elapsed)
    metrics.TOKENS.labels("input").inc(response.usage.input_tokens)
    metrics.TOKENS.labels("output").inc(response.usage.output_tokens)
    return response.text, response.usage, round(elapsed * 1000, 1)


async def generate(
    container: Container,
    session: AsyncSession,
    conn: Connection,
    question: str,
    provider: ModelProvider,
    history: list[prompt.Turn] | None = None,
) -> Generation:
    """Ask the model for one query answering ``question`` against ``conn``'s real schema,
    then run the guard over it (the caller decides whether to execute)."""
    schema = await schemas.ensure(container, session, conn)
    messages = prompt.generate_messages(
        dialect=conn.kind,
        tables=schema.tables,
        question=question,
        history=history or [],
        max_schema_chars=container.settings.prompt_schema_chars,
        connection_note=conn.description,
    )
    text, usage, model_ms = await _call(container, provider, messages, 1500)
    answer = prompt.parse_answer(text)
    gen = Generation(
        sql=answer.sql,
        explanation=answer.explanation,
        valid=False,
        refusal=None,
        refusal_code=None,
        provider=provider.name,
        model=provider.model,
        usage=usage,
        model_ms=model_ms,
        prompt_tables=messages[0].content.count("\n- "),
    )
    if answer.sql is None:
        return gen
    try:
        verdict = guard.check(answer.sql, conn.kind)
    except guard.UnsafeSqlError as exc:
        gen.refusal, gen.refusal_code = exc.message, exc.code
        return gen
    gen.sql, gen.valid, gen.tables = verdict.sql, True, verdict.tables
    if not gen.explanation:
        gen.explanation = describe(verdict.sql, conn.kind)
    return gen


def validate(sql: str, dialect: str) -> Validation:
    try:
        verdict = guard.check(sql, dialect)
    except guard.UnsafeSqlError as exc:
        return Validation(valid=False, reason=exc.message, code=exc.code, dialect=dialect)
    return Validation(valid=True, dialect=dialect, sql=verdict.sql, tables=verdict.tables)


def analysis(sql: str, dialect: str) -> Analysis:
    a = analyze(sql, dialect)
    return Analysis(**a.__dict__)


async def explain(
    container: Container,
    sql: str,
    dialect: str,
    provider: ModelProvider | None,
) -> ExplainOut:
    """A plain-language explanation of ``sql`` (any query, read-only or not). The query is
    parsed, never executed. With a provider the model explains it; the structured facts
    from the syntax tree come back either way, so the words can be checked."""
    facts = analysis(sql, dialect)
    explanation = describe(sql, dialect)
    source = "syntax"
    model = ""
    if provider is not None:
        text, _, _ = await _call(
            container, provider, prompt.explain_messages(dialect=dialect, sql=sql), 800
        )
        explained = prompt.parse_explanation(text)
        if explained:
            explanation, source, model = explained, "model", provider.model
    return ExplainOut(
        explanation=explanation,
        source=source,
        model=model,
        analysis=facts,
        executed=False,
    )
