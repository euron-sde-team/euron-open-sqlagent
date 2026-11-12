"""Tenancy, roles, API keys and the audit log (A7, A11)."""

from __future__ import annotations

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.conftest import Sources, Stack, login

pytestmark = pytest.mark.integration


async def _rival(stack: Stack) -> tuple[httpx.AsyncClient, str]:
    """A second organization with its own owner and project."""
    email, password = "rival@example.test", "Rival-Pass-123"
    await stack.ok("PATCH", "/api/v1/instance/settings", {"allow_signup": True})
    resp = await stack.client.post(
        "/api/v1/auth/signup",
        json={"email": email, "name": "Rival", "password": password, "organization": "Rival Inc"},
    )
    assert resp.status_code == 201, resp.text
    rival = await login(stack.api_url, {"email": email, "password": password})
    org = (await rival.get("/api/v1/orgs")).json()[0]
    proj = (
        await rival.post("/api/v1/projects", json={"org_id": org["id"], "name": "Theirs"})
    ).json()
    return rival, proj["id"]


async def test_a11_another_organization_gets_404_for_everything_of_ours(
    ready: Stack, sources: Sources
) -> None:
    conn = await ready.connection(sources.pg())
    msg = await ready.ask("How many orders per status?", connection_id=conn["id"])
    rival, their_project = await _rival(ready)
    try:
        ours = ready.project_id
        for path in (
            "",
            "/connections",
            f"/connections/{conn['id']}",
            f"/connections/{conn['id']}/schema",
            "/conversations",
            f"/conversations/{msg['conversation_id']}",
            f"/messages/{msg['id']}",
            "/executions",
            f"/executions/{msg['execution']['id']}",
            f"/executions/{msg['execution']['id']}/export.csv",
            "/audit-logs",
            "/templates",
            "/providers",
            "/usage",
            "/overview",
        ):
            resp = await rival.get(f"/api/v1/projects/{ours}{path}")
            assert resp.status_code == 404, (path, resp.status_code)
        resp = await rival.post(
            f"/api/v1/projects/{ours}/chat",
            json={"connection_id": conn["id"], "question": "How many orders?"},
        )
        assert resp.status_code == 404
        # Inside their own project, our ids do not exist either.
        theirs = f"/api/v1/projects/{their_project}"
        for path in (
            f"/connections/{conn['id']}",
            f"/conversations/{msg['conversation_id']}",
            f"/executions/{msg['execution']['id']}",
        ):
            assert (await rival.get(theirs + path)).status_code == 404, path
        resp = await rival.post(
            theirs + "/chat", json={"connection_id": conn["id"], "question": "How many orders?"}
        )
        assert resp.status_code == 404
        resp = await rival.post(
            theirs + "/sql/execute", json={"connection_id": conn["id"], "sql": "SELECT 1"}
        )
        assert resp.status_code == 404
        assert (await rival.get(f"/api/v1/orgs/{ready.org_id}/audit-logs")).status_code == 404
        assert [p["name"] for p in (await rival.get("/api/v1/projects")).json()] == ["Theirs"]
    finally:
        await rival.aclose()


async def test_project_roles(ready: Stack, sources: Sources) -> None:
    conn = await ready.connection(sources.pg())
    viewer, _ = await ready.member("viewer")
    editor, _ = await ready.member("editor")
    outsider = await ready.user_in_org("member")
    try:
        # Not in the project: it does not exist.
        assert (await outsider.get(ready.p("/connections"))).status_code == 404
        # Viewers read everything and run nothing.
        assert (await viewer.get(ready.p("/connections"))).status_code == 200
        assert (await viewer.get(ready.p(f"/connections/{conn['id']}/schema"))).status_code == 200
        for method, path, body in (
            ("POST", "/chat", {"connection_id": conn["id"], "question": "How many orders?"}),
            ("POST", "/sql/execute", {"connection_id": conn["id"], "sql": "SELECT 1"}),
            ("POST", "/sql/explain", {"dialect": "postgresql", "sql": "SELECT 1"}),
            ("POST", "/connections", {**sources.pg(), "name": "Another"}),
            ("POST", f"/connections/{conn['id']}/schema/refresh", None),
            ("GET", "/audit-logs", None),
            ("GET", "/api-keys", None),
        ):
            resp = await viewer.request(method, ready.p(path), json=body)
            assert resp.status_code == 403, (path, resp.status_code)
            assert resp.json()["error"]["code"] == "insufficient_role"
        # Editors ask and run, but do not manage members, keys or providers.
        msg = await ready.ask(
            "How many orders per status?", connection_id=conn["id"], client=editor
        )
        assert msg["status"] == "answered" and msg["actor_label"].startswith("member-")
        assert (
            await viewer.get(ready.p(f"/conversations/{msg['conversation_id']}"))
        ).status_code == 200
        for path in ("/audit-logs", "/api-keys"):
            assert (await editor.get(ready.p(path))).status_code == 403
        resp = await editor.post(ready.p("/providers"), json={"name": "x", "kind": "mock"})
        assert resp.status_code == 403
    finally:
        for c in (viewer, editor, outsider):
            await c.aclose()


async def test_api_keys_and_scopes(ready: Stack, sources: Sources) -> None:
    conn = await ready.connection(sources.pg())
    read = await ready.ok(
        "POST", ready.p("/api-keys"), {"name": "dashboards", "scopes": ["read"]}, status=201
    )
    query = await ready.ok(
        "POST", ready.p("/api-keys"), {"name": "reports", "scopes": ["read", "query"]}, status=201
    )
    assert read["key"].startswith("sqa_")
    async with httpx.AsyncClient(base_url=ready.api_url, timeout=60) as c:
        h_read = {"authorization": f"Bearer {read['key']}"}
        h_query = {"x-api-key": query["key"]}
        assert (await c.get(ready.p("/connections"), headers=h_read)).status_code == 200
        resp = await c.post(
            ready.p("/chat"),
            headers=h_read,
            json={"connection_id": conn["id"], "question": "How many orders?"},
        )
        assert resp.status_code == 403 and resp.json()["error"]["code"] == "insufficient_scope"
        resp = await c.post(
            ready.p("/chat"),
            headers=h_query,
            json={"connection_id": conn["id"], "question": "How many orders per status?"},
        )
        assert resp.status_code == 201 and resp.json()["status"] == "answered"
        assert resp.json()["actor_label"] == "api-key:reports"
        # A key belongs to one project.
        other = await ready.ok(
            "POST", "/api/v1/projects", {"org_id": ready.org_id, "name": "Other"}, status=201
        )
        assert (
            await c.get(f"/api/v1/projects/{other['id']}/connections", headers=h_query)
        ).status_code == 404
        # Revoked keys stop working at once.
        await ready.ok("DELETE", ready.p(f"/api-keys/{query['id']}"))
        assert (await c.get(ready.p("/connections"), headers=h_query)).status_code == 401
        assert (
            await c.get(ready.p("/connections"), headers={"x-api-key": "sqa_nope"})
        ).status_code == 401


async def test_a7_every_query_is_in_the_append_only_audit_log_per_connection_and_per_user(
    ready: Stack, sources: Sources
) -> None:
    shop = await ready.connection(sources.pg())
    people = await ready.connection(sources.mysql())
    editor, editor_id = await ready.member("editor")
    try:
        admin_msg = await ready.ask("How many orders per status?", connection_id=shop["id"])
        editor_msg = await ready.ask(
            "Average salary by department", connection_id=people["id"], client=editor
        )
        refused = await ready.ask("Drop table orders", connection_id=shop["id"], client=editor)
        assert refused["status"] == "refused"
        direct = await ready.ok(
            "POST",
            ready.p("/sql/execute"),
            {"connection_id": shop["id"], "sql": "SELECT count(*) AS n FROM customers"},
        )
        shop_log = await ready.audit(connection_id=shop["id"], action="query.")
        assert {e["details"]["execution_id"] for e in shop_log} == {
            admin_msg["execution"]["id"],
            refused["execution"]["id"],
            direct["id"],
        }
        by_id = {e["details"]["execution_id"]: e for e in shop_log}
        first = by_id[admin_msg["execution"]["id"]]
        assert first["details"]["sql"] == admin_msg["sql"]
        assert first["details"]["row_count"] == 5 and first["details"]["status"] == "succeeded"
        assert first["actor_email"] == "admin@example.test" and first["action"] == "query.executed"
        assert by_id[refused["execution"]["id"]]["action"] == "query.refused"
        assert by_id[direct["id"]]["details"]["row_count"] == 1
        people_log = await ready.audit(connection_id=people["id"], action="query.")
        assert [e["details"]["execution_id"] for e in people_log] == [editor_msg["execution"]["id"]]
        mine = await ready.audit(actor_id=editor_id, action="query.")
        assert {e["details"]["execution_id"] for e in mine} == {
            editor_msg["execution"]["id"],
            refused["execution"]["id"],
        }
        assert all(e["actor_id"] == editor_id for e in mine)
        # Questions are audited too.
        asked = await ready.audit(actor_id=editor_id, action="question.asked")
        assert {e["details"]["question"] for e in asked} == {
            "Average salary by department",
            "Drop table orders",
        }
    finally:
        await editor.aclose()
    # Append-only, enforced by the database itself.
    engine = create_async_engine(ready.settings.database_url)
    try:
        for stmt in ("UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log"):
            with pytest.raises(sa.exc.DBAPIError, match="append-only"):
                async with engine.begin() as c:
                    await c.execute(sa.text(stmt))
    finally:
        await engine.dispose()


async def test_usage_and_overview_count_what_ran(ready: Stack, sources: Sources) -> None:
    conn = await ready.connection(sources.pg())
    await ready.ask("How many orders per status?", connection_id=conn["id"])
    await ready.ask("Delete all orders", connection_id=conn["id"])
    usage = await ready.ok("GET", ready.p("/usage"), params={"days": 7})
    today = usage["by_day"][-1]
    assert today["questions"] == 2 and today["answered"] == 1 and today["refused"] == 1
    assert today["executions"] == 1 and today["rows_returned"] == 5
    assert usage["by_connection"][0]["connection"] == conn["name"]
    assert usage["by_model"][0]["model"] == "sqlagent-mock"
    overview = await ready.ok("GET", ready.p("/overview"))
    assert overview["questions_7d"] == 2 and overview["refused_7d"] == 1
    assert overview["conversations"] == 2 and len(overview["recent"]) == 2
    assert overview["median_query_ms"] is not None
    assert overview["connections"][0]["tables"] == 5
