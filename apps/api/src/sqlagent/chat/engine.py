"""Answering one queued question: the pipeline a worker runs.

1. Load the conversation's prior turns (question, SQL, a summary of the result) so a
   follow-up resolves against them.
2. Ask the model for one query against the connection's real schema
   (``sql.service.generate``), or take a saved template's SQL as is.
3. The SQL guard. A refused query is reported with its reason and never retried against a
   different, unvalidated query.
4. Execute on a read-only connection under the connection's limits
   (``executions.service.execute``), which also writes the audit entry.
5. Finish the question under the worker's lease and wake whoever waits for it.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import select

from sqlagent.audit.service import Actor, audit
from sqlagent.chat import queue
from sqlagent.chat.models import Conversation, ConversationMessage
from sqlagent.connections.models import Connection
from sqlagent.core.container import Container
from sqlagent.core.errors import AppError
from sqlagent.executions import service as executions
from sqlagent.observability import metrics
from sqlagent.sql import service as sql_service
from sqlagent.sql.describe import describe
from sqlagent.sql.prompt import Turn
from sqlagent.usage import service as usage

log = logging.getLogger("sqlagent.chat")
SUMMARY_ROWS = 5


def summarize(
    columns: list[dict[str, Any]], rows: list[list[Any]], truncated: bool
) -> dict[str, Any]:
    """What the next question sees of a result: its shape and first rows, never all of it."""
    return {
        "columns": [c.get("name") for c in columns],
        "row_count": len(rows),
        "truncated": truncated,
        "first_rows": rows[:SUMMARY_ROWS],
    }


def summary_text(msg: ConversationMessage) -> str:
    parts = [msg.explanation or ""]
    s = msg.result_summary or {}
    if s:
        parts.append(
            f"The result had {s.get('row_count', 0)} rows with columns "
            f"{', '.join(str(c) for c in s.get('columns', []))}."
        )
        if s.get("first_rows"):
            parts.append(f"First rows: {s['first_rows'][:3]}")
    return " ".join(p for p in parts if p)[:2000]


async def history(container: Container, msg: ConversationMessage) -> list[Turn]:
    limit = container.settings.history_turns
    if limit == 0:
        return []
    async with container.db.sessionmaker() as session:
        rows = (
            await session.scalars(
                select(ConversationMessage)
                .where(
                    ConversationMessage.conversation_id == msg.conversation_id,
                    ConversationMessage.seq < msg.seq,
                    ConversationMessage.status == "answered",
                )
                .order_by(ConversationMessage.seq.desc())
                .limit(limit)
            )
        ).all()
    return [Turn(question=r.question, sql=r.sql, summary=summary_text(r)) for r in reversed(rows)]


async def answer(container: Container, msg: ConversationMessage, owner: str) -> None:
    started = time.perf_counter()
    actor = Actor(msg.actor_id, msg.actor_label, msg.actor_role)
    final: dict[str, Any] = {}
    # Filled as the pipeline goes, so a failure still records the model and tokens used.
    partial: dict[str, Any] = {}
    project_id, connection_id = msg.project_id, msg.connection_id
    async with container.db.sessionmaker() as session:
        conn = await session.get(Connection, connection_id)
        conversation = await session.get(Conversation, msg.conversation_id)
        if conn is None or conversation is None:
            final = {
                "status": "failed",
                "error": "The connection was removed",
                "error_code": "gone",
            }
        else:
            try:
                final = await _answer(container, session, conn, conversation, msg, actor, partial)
            except AppError as exc:
                await session.rollback()
                final = partial | {"status": "failed", "error": exc.message, "error_code": exc.code}
            except Exception:
                log.exception("question failed", extra={"message_id": str(msg.id)})
                await session.rollback()
                final = partial | {
                    "status": "failed",
                    "error": "Something went wrong while answering. Ask again",
                    "error_code": "internal_error",
                }
        final["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
        if conn is not None:
            await usage.record(
                session,
                project_id,
                connection_id,
                str(final.get("model") or ""),
                questions=1,
                answered=int(final["status"] == "answered"),
                refused=int(final["status"] == "refused"),
                failed=int(final["status"] == "failed"),
                input_tokens=int(final.get("input_tokens", 0)),
                output_tokens=int(final.get("output_tokens", 0)),
            )
        if not await queue.finish(session, msg.id, owner, **final):
            await session.rollback()
            log.warning("lease lost before finishing", extra={"message_id": str(msg.id)})
            return
        await session.commit()
    metrics.QUESTIONS.labels(str(final["status"])).inc()
    log.info(
        "question finished",
        extra={"status": final["status"], "total_ms": final["total_ms"], "message_id": str(msg.id)},
    )
    metrics.QUESTION_SECONDS.observe(time.perf_counter() - started)
    await container.pubsub.publish(queue.message_channel(msg.id), str(final["status"]))


async def _answer(
    container: Container,
    session: Any,
    conn: Connection,
    conversation: Conversation,
    msg: ConversationMessage,
    actor: Actor,
    out: dict[str, Any],
) -> dict[str, Any]:
    if msg.preset_sql:
        sql = msg.preset_sql
        out["explanation"] = "The saved query of this template. " + describe(sql, conn.kind)
    else:
        provider = await sql_service.provider_for(
            session, conn.project_id, conversation.provider_id
        )
        turns = await history(container, msg)
        gen = await sql_service.generate(container, session, conn, msg.question, provider, turns)
        out |= {
            "provider_name": gen.provider,
            "model": gen.model,
            "input_tokens": gen.usage.input_tokens,
            "output_tokens": gen.usage.output_tokens,
            "model_ms": gen.model_ms,
            "explanation": gen.explanation,
            "sql": gen.sql,
        }
        if gen.sql is None:
            return out | {
                "status": "no_answer",
                "error": gen.explanation or "The model did not write a query for this question",
                "error_code": "no_answer",
            }
        sql = gen.sql
    out["sql"] = sql
    outcome = await executions.execute(
        container,
        session,
        conn,
        sql,
        actor,
        source="template" if msg.preset_sql else "chat",
        conversation_id=conversation.id,
        model=str(out.get("model") or ""),
    )
    ex = outcome.execution
    out["execution_id"] = ex.id
    out["sql"] = ex.sql
    if ex.status == "refused":
        audit(
            session,
            actor,
            "question.refused",
            "connection",
            conn.id,
            question=msg.question[:2000],
            reason=ex.error,
            project_id=conn.project_id,
        )
        return out | {"status": "refused", "error": ex.error, "error_code": ex.error_code}
    if ex.status != "succeeded":
        return out | {"status": "failed", "error": ex.error, "error_code": ex.error_code}
    out["result_summary"] = summarize(ex.columns, outcome.rows, ex.truncated)
    return out | {"status": "answered"}
