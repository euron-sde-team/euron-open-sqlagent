"""The SQLAgent clients. ``SQLAgent`` is synchronous; ``AsyncSQLAgent`` has the same methods
with ``await``. Both authenticate with a project API key (``sqa_...``), which also selects
the project, or with a session token plus ``project_id``.

Every method builds a ``Call`` (method, path, body, how to read the answer) once, and each
client only decides how to send it, so the two clients cannot drift apart.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from typing_extensions import Self

import httpx

from euron_sqlagent.errors import SQLAgentError
from euron_sqlagent.models import Answer, Execution

DEFAULT_URL = "http://localhost:5430"


@dataclass(frozen=True)
class Call:
    method: str
    path: str
    json: Any = None
    params: dict[str, Any] = field(default_factory=dict)
    read: Callable[[Any], Any] = lambda body: body
    raw: bool = False


def _headers(api_key: str | None) -> dict[str, str]:
    h = {"user-agent": "euron-sqlagent-python/0.1.0", "x-sqa-csrf": "1"}
    if api_key:
        h["authorization"] = f"Bearer {api_key}"
    return h


def _check(resp: httpx.Response, raw: bool) -> Any:
    if resp.status_code >= 400:
        try:
            err = resp.json().get("error", {})
        except ValueError:
            err = {}
        raise SQLAgentError(
            resp.status_code,
            str(err.get("code", "http_error")),
            str(err.get("message", resp.text[:300])),
            err.get("details"),
        )
    if raw:
        return resp.text
    if resp.status_code == 204 or not resp.content:
        return None
    return resp.json()


class _Calls:
    """Every operation of the API the SDK covers, as ``Call`` objects."""

    def __init__(self, project_id: str) -> None:
        self.base = f"/api/v1/projects/{project_id}"

    def connections(self) -> Call:
        return Call("GET", f"{self.base}/connections")

    def schema(self, connection_id: str, refresh: bool = False) -> Call:
        path = f"{self.base}/connections/{connection_id}/schema"
        return Call("POST", path + "/refresh") if refresh else Call("GET", path)

    def test(self, connection_id: str) -> Call:
        return Call("POST", f"{self.base}/connections/{connection_id}/test")

    def ask(
        self,
        question: str,
        connection_id: str | None,
        conversation_id: str | None,
        wait: float,
        provider_id: str | None,
    ) -> Call:
        body: dict[str, Any] = {"question": question, "wait": wait}
        if connection_id:
            body["connection_id"] = connection_id
        if conversation_id:
            body["conversation_id"] = conversation_id
        if provider_id:
            body["provider_id"] = provider_id
        return Call("POST", f"{self.base}/chat", json=body, read=Answer.of)

    def message(self, message_id: str, wait: float) -> Call:
        return Call(
            "GET", f"{self.base}/messages/{message_id}", params={"wait": wait}, read=Answer.of
        )

    def generate(self, connection_id: str, question: str) -> Call:
        return Call(
            "POST",
            f"{self.base}/sql/generate",
            json={"connection_id": connection_id, "question": question},
        )

    def validate(self, sql: str, connection_id: str | None, dialect: str | None) -> Call:
        return Call(
            "POST",
            f"{self.base}/sql/validate",
            json={"sql": sql, "connection_id": connection_id, "dialect": dialect},
        )

    def explain(
        self, sql: str, connection_id: str | None, dialect: str | None, use_model: bool
    ) -> Call:
        return Call(
            "POST",
            f"{self.base}/sql/explain",
            json={
                "sql": sql,
                "connection_id": connection_id,
                "dialect": dialect,
                "use_model": use_model,
            },
        )

    def execute(self, connection_id: str, sql: str, page_size: int) -> Call:
        return Call(
            "POST",
            f"{self.base}/sql/execute",
            json={"connection_id": connection_id, "sql": sql, "page_size": page_size},
            read=Execution.of,
        )

    def rows(self, execution_id: str, offset: int, limit: int) -> Call:
        return Call(
            "GET",
            f"{self.base}/executions/{execution_id}/rows",
            params={"offset": offset, "limit": limit},
        )

    def csv(self, execution_id: str) -> Call:
        return Call("GET", f"{self.base}/executions/{execution_id}/export.csv", raw=True)

    def conversations(self, connection_id: str | None) -> Call:
        params = {"connection_id": connection_id} if connection_id else {}
        return Call("GET", f"{self.base}/conversations", params=params, read=lambda b: b["items"])

    def conversation(self, conversation_id: str) -> Call:
        return Call("GET", f"{self.base}/conversations/{conversation_id}")

    def templates(self) -> Call:
        return Call("GET", f"{self.base}/templates")

    def run_template(self, template_id: str, wait: float) -> Call:
        return Call(
            "POST",
            f"{self.base}/templates/{template_id}/run",
            json={"wait": wait},
            read=Answer.of,
        )


def _connection_id(connections: list[dict[str, Any]], name_or_id: str) -> str:
    for c in connections:
        if name_or_id in (c["id"], c["name"]):
            return str(c["id"])
    names = ", ".join(c["name"] for c in connections) or "none"
    raise SQLAgentError(404, "not_found", f"No connection {name_or_id!r} (connections: {names})")


class SQLAgent:
    """Synchronous client.

    >>> client = SQLAgent(api_key="sqa_...")
    >>> answer = client.ask("How many orders per status?", connection="Shop (PostgreSQL)")
    >>> answer.sql, answer.records()
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        project_id: str | None = None,
        timeout: float = 150.0,
    ) -> None:
        self.http = httpx.Client(
            base_url=(base_url or os.environ.get("SQLAGENT_URL") or DEFAULT_URL).rstrip("/"),
            headers=_headers(api_key or os.environ.get("SQLAGENT_API_KEY")),
            timeout=timeout,
        )
        self._project_id = project_id
        self._calls: _Calls | None = None

    def _send(self, call: Call) -> Any:
        resp = self.http.request(call.method, call.path, json=call.json, params=call.params)
        return call.read(_check(resp, call.raw))

    @property
    def calls(self) -> _Calls:
        if self._calls is None:
            pid = self._project_id or self.project()["id"]
            self._calls = _Calls(str(pid))
        return self._calls

    def project(self) -> dict[str, Any]:
        """The project of the API key (or of ``project_id``)."""
        if self._project_id:
            return dict(self._send(Call("GET", f"/api/v1/projects/{self._project_id}")))
        return dict(self._send(Call("GET", "/api/v1/projects/current")))

    def connections(self) -> list[dict[str, Any]]:
        return list(self._send(self.calls.connections()))

    def connection_id(self, name_or_id: str) -> str:
        return _connection_id(self.connections(), name_or_id)

    def schema(self, connection: str, *, refresh: bool = False) -> dict[str, Any]:
        return dict(self._send(self.calls.schema(self.connection_id(connection), refresh)))

    def test(self, connection: str) -> dict[str, Any]:
        return dict(self._send(self.calls.test(self.connection_id(connection))))

    def ask(
        self,
        question: str,
        *,
        connection: str | None = None,
        conversation: str | None = None,
        wait: float = 60.0,
        provider_id: str | None = None,
    ) -> Answer:
        """Ask a question on ``connection`` (name or id), or follow up in ``conversation``.
        Waits for the answer up to ``wait`` seconds (then poll ``answer(id)``)."""
        cid = self.connection_id(connection) if connection else None
        out: Answer = self._send(
            self.calls.ask(question, cid, conversation, min(wait, 120.0), provider_id)
        )
        return out

    def answer(self, message_id: str, *, wait: float = 30.0) -> Answer:
        out: Answer = self._send(self.calls.message(message_id, min(wait, 60.0)))
        return out

    def generate(self, question: str, *, connection: str) -> dict[str, Any]:
        """The SQL for a question, checked by the guard, not executed."""
        return dict(self._send(self.calls.generate(self.connection_id(connection), question)))

    def validate(
        self, sql: str, *, connection: str | None = None, dialect: str | None = None
    ) -> dict[str, Any]:
        cid = self.connection_id(connection) if connection else None
        return dict(self._send(self.calls.validate(sql, cid, dialect)))

    def explain(
        self,
        sql: str,
        *,
        connection: str | None = None,
        dialect: str | None = None,
        use_model: bool = True,
    ) -> dict[str, Any]:
        """A plain-language explanation of any query. It is never executed."""
        cid = self.connection_id(connection) if connection else None
        return dict(self._send(self.calls.explain(sql, cid, dialect, use_model)))

    def execute(self, sql: str, *, connection: str, page_size: int = 50) -> Execution:
        out: Execution = self._send(
            self.calls.execute(self.connection_id(connection), sql, page_size)
        )
        return out

    def rows(self, execution_id: str, *, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        return dict(self._send(self.calls.rows(execution_id, offset, limit)))

    def csv(self, execution_id: str) -> str:
        return str(self._send(self.calls.csv(execution_id)))

    def conversations(self, *, connection: str | None = None) -> list[dict[str, Any]]:
        cid = self.connection_id(connection) if connection else None
        return list(self._send(self.calls.conversations(cid)))

    def conversation(self, conversation_id: str) -> dict[str, Any]:
        return dict(self._send(self.calls.conversation(conversation_id)))

    def templates(self) -> list[dict[str, Any]]:
        return list(self._send(self.calls.templates()))

    def run_template(self, template_id: str, *, wait: float = 60.0) -> Answer:
        out: Answer = self._send(self.calls.run_template(template_id, min(wait, 120.0)))
        return out

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class AsyncSQLAgent:
    """The same client for asyncio code."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        project_id: str | None = None,
        timeout: float = 150.0,
    ) -> None:
        self.http = httpx.AsyncClient(
            base_url=(base_url or os.environ.get("SQLAGENT_URL") or DEFAULT_URL).rstrip("/"),
            headers=_headers(api_key or os.environ.get("SQLAGENT_API_KEY")),
            timeout=timeout,
        )
        self._project_id = project_id
        self._calls: _Calls | None = None

    async def _send(self, call: Call) -> Any:
        resp = await self.http.request(call.method, call.path, json=call.json, params=call.params)
        return call.read(_check(resp, call.raw))

    async def calls(self) -> _Calls:
        if self._calls is None:
            pid = self._project_id or (await self.project())["id"]
            self._calls = _Calls(str(pid))
        return self._calls

    async def project(self) -> dict[str, Any]:
        if self._project_id:
            return dict(await self._send(Call("GET", f"/api/v1/projects/{self._project_id}")))
        return dict(await self._send(Call("GET", "/api/v1/projects/current")))

    async def connections(self) -> list[dict[str, Any]]:
        return list(await self._send((await self.calls()).connections()))

    async def connection_id(self, name_or_id: str) -> str:
        return _connection_id(await self.connections(), name_or_id)

    async def schema(self, connection: str, *, refresh: bool = False) -> dict[str, Any]:
        cid = await self.connection_id(connection)
        return dict(await self._send((await self.calls()).schema(cid, refresh)))

    async def ask(
        self,
        question: str,
        *,
        connection: str | None = None,
        conversation: str | None = None,
        wait: float = 60.0,
        provider_id: str | None = None,
    ) -> Answer:
        cid = await self.connection_id(connection) if connection else None
        call = (await self.calls()).ask(question, cid, conversation, min(wait, 120.0), provider_id)
        out: Answer = await self._send(call)
        return out

    async def answer(self, message_id: str, *, wait: float = 30.0) -> Answer:
        out: Answer = await self._send((await self.calls()).message(message_id, min(wait, 60.0)))
        return out

    async def explain(
        self,
        sql: str,
        *,
        connection: str | None = None,
        dialect: str | None = None,
        use_model: bool = True,
    ) -> dict[str, Any]:
        cid = await self.connection_id(connection) if connection else None
        return dict(await self._send((await self.calls()).explain(sql, cid, dialect, use_model)))

    async def execute(self, sql: str, *, connection: str, page_size: int = 50) -> Execution:
        cid = await self.connection_id(connection)
        out: Execution = await self._send((await self.calls()).execute(cid, sql, page_size))
        return out

    async def csv(self, execution_id: str) -> str:
        return str(await self._send((await self.calls()).csv(execution_id)))

    async def aclose(self) -> None:
        await self.http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
