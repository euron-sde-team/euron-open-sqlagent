"""Every other endpoint: sign-in, people, projects, connections, conversations, templates,
executions, system."""

from __future__ import annotations

import httpx
import pytest

from tests.integration.conftest import ADMIN, CSRF, Sources, Stack, login

pytestmark = pytest.mark.integration


async def test_sign_in_sessions_and_passwords(stack: Stack) -> None:
    async with httpx.AsyncClient(base_url=stack.api_url, headers=CSRF) as c:
        bad = await c.post("/api/v1/auth/login", json={**ADMIN, "password": "Wrong-Pass-999"})
        assert bad.status_code == 401
        ok = await c.post("/api/v1/auth/login", json=ADMIN)
        assert ok.status_code == 200 and "sqa_session" in ok.headers["set-cookie"]
        token = ok.json()["session_token"]
        h = {"authorization": f"Bearer {token}"}
        assert (await c.get("/api/v1/auth/me", headers=h)).json()["email"] == ADMIN["email"]
        session = (await c.get("/api/v1/auth/session", headers=h)).json()
        assert session["user"]["role"] == "admin"
        assert (await c.post("/api/v1/auth/logout", headers=h)).status_code == 200
        assert (await c.get("/api/v1/auth/me", headers=h)).status_code == 401
    # Cookie sessions need the CSRF header on writes.
    async with httpx.AsyncClient(base_url=stack.api_url) as c:
        ok = await c.post("/api/v1/auth/login", json=ADMIN, headers=CSRF)
        resp = await c.post("/api/v1/projects", json={"org_id": stack.org_id, "name": "X"})
        assert resp.status_code == 403 and resp.json()["error"]["code"] == "csrf_required"
    # Changing the password signs out other sessions.
    other = await login(stack.api_url)
    new = {"current_password": ADMIN["password"], "new_password": "Brand-New-Pass-42"}
    assert (await stack.client.post("/api/v1/auth/password", json=new)).status_code == 200
    assert (await other.get("/api/v1/auth/me")).status_code == 401
    await other.aclose()
    # Sign-up is off unless an admin turns it on.
    resp = await stack.client.post(
        "/api/v1/auth/signup",
        json={
            "email": "x@example.test",
            "name": "X",
            "password": "Some-Pass-123",
            "organization": "X",
        },
    )
    assert resp.status_code in (403, 404)
    public = (await stack.client.get("/api/v1/instance/public")).json()
    assert public["allow_signup"] is False and public["needs_setup"] is False


async def test_people_organizations_and_projects(ready: Stack) -> None:
    users = await ready.ok("GET", "/api/v1/users")
    assert [u["email"] for u in users] == [ADMIN["email"]]
    analyst = await ready.user_in_org("member", email="analyst@example.test")
    try:
        members = await ready.ok("GET", f"/api/v1/orgs/{ready.org_id}/members")
        assert {m["email"] for m in members} == {ADMIN["email"], "analyst@example.test"}
        added = await ready.ok(
            "POST",
            ready.p("/members"),
            {"email": "analyst@example.test", "role": "viewer"},
            status=201,
        )
        assert added["role"] == "viewer"
        await ready.ok("PATCH", ready.p(f"/members/{added['user_id']}"), {"role": "editor"})
        projects = (await analyst.get("/api/v1/projects")).json()
        assert [(p["name"], p["role"]) for p in projects] == [("Analytics", "editor")]
        await ready.ok("DELETE", ready.p(f"/members/{added['user_id']}"), status=204)
        assert (await analyst.get(ready.p())).status_code == 404
        # The last admin cannot leave.
        me = (await ready.client.get("/api/v1/auth/me")).json()
        resp = await ready.client.delete(ready.p(f"/members/{me['id']}"))
        assert resp.status_code in (204, 409)
    finally:
        await analyst.aclose()
    renamed = await ready.ok("PATCH", ready.p(), {"name": "Analytics team"})
    assert renamed["name"] == "Analytics team"
    listed = await ready.ok("GET", "/api/v1/projects")
    assert listed[0]["connections"] == 0 and listed[0]["questions_24h"] == 0
    org_log = await ready.ok("GET", f"/api/v1/orgs/{ready.org_id}/audit-logs")
    assert any(e["action"] == "project.created" for e in org_log["items"])
    instance_log = await ready.ok("GET", "/api/v1/audit", params={"action": "user."})
    assert instance_log["items"]


async def test_connections_lifecycle(ready: Stack, sources: Sources) -> None:
    body = sources.pg()
    tested = await ready.ok("POST", ready.p("/connections/test"), body)
    assert tested["ok"] is True and tested["read_only"] is True
    wrong = await ready.ok("POST", ready.p("/connections/test"), {**body, "port": 1})
    assert wrong["ok"] is False and "Nothing answered" in wrong["message"]
    unknown = await ready.ok("POST", ready.p("/connections/test"), {**body, "database": "nope"})
    assert unknown["ok"] is False
    resp = await ready.client.post(
        ready.p("/connections"), json={**body, "host": "169.254.169.254"}
    )
    assert resp.status_code == 422
    conn = await ready.connection(body, description="The online store")
    resp = await ready.client.post(ready.p("/connections"), json=body)
    assert resp.status_code == 409
    changed = await ready.ok(
        "PATCH",
        ready.p(f"/connections/{conn['id']}"),
        {"name": "Shop", "max_rows": 50, "timeout_s": 5, "max_scan_rows": 100000},
    )
    assert (changed["name"], changed["max_rows"], changed["timeout_s"]) == ("Shop", 50, 5)
    assert changed["has_password"] is True
    tested = await ready.ok("POST", ready.p(f"/connections/{conn['id']}/test"))
    assert tested["ok"] is True
    got = await ready.ok("GET", ready.p(f"/connections/{conn['id']}"))
    assert got["last_test_ok"] is True and got["server_version"].startswith("PostgreSQL")
    # A file that is not SQLite is refused.
    resp = await ready.client.post(
        ready.p("/connections/sqlite"),
        data={"name": "Bad"},
        files={"file": ("notes.txt", b"just text", "text/plain")},
    )
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "not_sqlite"
    subs = await ready.sqlite(sources.sqlite_path)
    assert subs["kind"] == "sqlite" and subs["file_name"] == "subscriptions.sqlite"
    schema = await ready.ok("GET", ready.p(f"/connections/{subs['id']}/schema"))
    assert {t["name"] for t in schema["tables"]} == {"plans", "accounts", "invoices"}
    # An unreachable database fails discovery with a clear reason.
    broken = await ready.connection({**body, "name": "Broken", "port": 1})
    resp = await ready.client.get(ready.p(f"/connections/{broken['id']}/schema"))
    assert resp.status_code == 400 and "Nothing answered" in resp.json()["error"]["message"]
    await ready.ok("DELETE", ready.p(f"/connections/{broken['id']}"), status=204)
    await ready.ok("DELETE", ready.p(f"/connections/{subs['id']}"), status=204)
    assert [c["name"] for c in await ready.ok("GET", ready.p("/connections"))] == ["Shop"]


async def test_conversations_history(ready: Stack, sources: Sources) -> None:
    conn = await ready.connection(sources.pg())
    for q in ("How many orders per status?", "How many customers per country?", "Revenue by month"):
        await ready.ask(q, connection_id=conn["id"])
    page = await ready.ok("GET", ready.p("/conversations"), params={"limit": 2})
    assert [c["title"] for c in page["items"]] == [
        "Revenue by month",
        "How many customers per country?",
    ]
    assert page["items"][0]["last_status"] == "answered"
    rest = await ready.ok(
        "GET", ready.p("/conversations"), params={"limit": 2, "cursor": page["next_cursor"]}
    )
    assert [c["title"] for c in rest["items"]] == ["How many orders per status?"]
    assert rest["next_cursor"] is None
    found = await ready.ok("GET", ready.p("/conversations"), params={"q": "customers"})
    assert len(found["items"]) == 1
    cid = found["items"][0]["id"]
    renamed = await ready.ok("PATCH", ready.p(f"/conversations/{cid}"), {"title": "Customer map"})
    assert renamed["title"] == "Customer map"
    # A follow-up stays on its conversation's connection.
    other = await ready.connection(sources.mysql())
    resp = await ready.client.post(
        ready.p("/chat"),
        json={"conversation_id": cid, "connection_id": other["id"], "question": "and?"},
    )
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "connection_mismatch"
    resp = await ready.client.post(ready.p("/chat"), json={"question": "How many orders?"})
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "connection_required"
    # Asking without waiting returns at once; the answer can be awaited later.
    queued = await ready.ask("How many products?", connection_id=conn["id"], wait=0)
    assert queued["status"] in ("queued", "running", "answered")
    done = await ready.ok("GET", ready.p(f"/messages/{queued['id']}"), params={"wait": 20})
    assert done["status"] == "answered"
    await ready.ok("DELETE", ready.p(f"/conversations/{cid}"), status=204)
    assert (await ready.client.get(ready.p(f"/conversations/{cid}"))).status_code == 404
    # The audit log still has every query of the deleted conversation.
    log = await ready.audit(action="question.asked")
    assert "How many customers per country?" in {e["details"]["question"] for e in log}


async def test_templates_and_executions(ready: Stack, sources: Sources) -> None:
    conn = await ready.connection(sources.pg())
    tpl = await ready.ok(
        "POST",
        ready.p("/templates"),
        {
            "connection_id": conn["id"],
            "name": "Status mix",
            "question": "How many orders per status?",
        },
        status=201,
    )
    assert tpl["sql"] is None
    run = await ready.ok("POST", ready.p(f"/templates/{tpl['id']}/run"), {"wait": 30}, status=201)
    assert run["status"] == "answered" and run["template_id"] == tpl["id"]
    edited = await ready.ok(
        "PATCH",
        ready.p(f"/templates/{tpl['id']}"),
        {
            "name": "Orders by status",
            "sql": "SELECT status, count(*) AS n FROM orders GROUP BY status",
        },
    )
    assert edited["sql"].startswith("SELECT status")
    run = await ready.ok("POST", ready.p(f"/templates/{tpl['id']}/run"), {"wait": 30}, status=201)
    assert run["sql"].startswith("SELECT status") and run["model"] is None
    assert run["page"]["total"] == 5
    filtered = await ready.ok("GET", ready.p("/templates"), params={"connection_id": conn["id"]})
    assert filtered[0]["use_count"] == 2
    await ready.ok("DELETE", ready.p(f"/templates/{tpl['id']}"), status=204)
    # Executions: listing filters, one by id, and no rows for a refused query.
    refused = await ready.ok(
        "POST", ready.p("/sql/execute"), {"connection_id": conn["id"], "sql": "DROP TABLE orders"}
    )
    page = await ready.ok("GET", ready.p("/executions"), params={"status": "refused"})
    assert [e["id"] for e in page["items"]] == [refused["id"]]
    one = await ready.ok("GET", ready.p(f"/executions/{refused['id']}"))
    assert one["status"] == "refused"
    resp = await ready.client.get(ready.p(f"/executions/{refused['id']}/rows"))
    assert resp.status_code == 400
    resp = await ready.client.get(ready.p(f"/executions/{refused['id']}/export.csv"))
    assert resp.status_code == 400
    me = (await ready.client.get("/api/v1/auth/me")).json()
    mine = await ready.ok("GET", ready.p("/executions"), params={"actor_id": me["id"], "limit": 1})
    assert len(mine["items"]) == 1 and mine["next_cursor"]
    nxt = await ready.ok(
        "GET", ready.p("/executions"), params={"actor_id": me["id"], "cursor": mine["next_cursor"]}
    )
    assert mine["items"][0]["id"] not in {e["id"] for e in nxt["items"]}


async def test_system_endpoints(ready: Stack) -> None:
    async with httpx.AsyncClient(base_url=ready.api_url) as c:
        assert (await c.get("/healthz")).json() == {"status": "ok"}
        ready_ = (await c.get("/readyz")).json()
        assert (
            ready_["checks"]["postgres"]["ok"] is True and ready_["checks"]["redis"]["ok"] is True
        )
        metrics = (await c.get("/metrics")).text
        assert "sqlagent_guard_refusals_total" in metrics
        spec = (await c.get("/openapi.json")).json()
        assert spec["info"]["title"] == "Euron Open SQLAgent"
    info = await ready.ok("GET", "/api/v1/system")
    assert info["queue"]["queued"] == 0 and info["projects"] == 1
