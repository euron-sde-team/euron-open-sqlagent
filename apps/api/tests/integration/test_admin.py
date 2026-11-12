"""Administration: instance users, organizations and their members, member notices, and the
request guards (validation errors, body size limits)."""

from __future__ import annotations

import httpx
import pytest

from sqlagent.core import mail
from tests.integration.conftest import CSRF, Stack, login

pytestmark = pytest.mark.integration


async def test_instance_admins_manage_users(stack: Stack) -> None:
    created = await stack.ok(
        "POST",
        "/api/v1/users",
        {"email": "ops@example.test", "name": "Ops", "password": "Ops-Pass-1234"},
        status=201,
    )
    assert created["role"] == "user"
    resp = await stack.client.post(
        "/api/v1/users",
        json={"email": "ops@example.test", "name": "Again", "password": "Ops-Pass-1234"},
    )
    assert resp.status_code == 409
    weak = await stack.client.post(
        "/api/v1/users", json={"email": "w@example.test", "name": "W", "password": "alllowercase"}
    )
    assert weak.status_code in (400, 422)
    ops = await login(stack.api_url, {"email": "ops@example.test", "password": "Ops-Pass-1234"})
    try:
        assert (
            await ops.post(
                "/api/v1/users",
                json={"email": "x@example.test", "name": "x", "password": "Xx-Pass-12345"},
            )
        ).status_code == 403
        promoted = await stack.ok(
            "PATCH", f"/api/v1/users/{created['id']}", {"role": "admin", "name": "Ops Lead"}
        )
        assert promoted["role"] == "admin" and promoted["name"] == "Ops Lead"
        await stack.ok("PATCH", f"/api/v1/users/{created['id']}", {"disabled": True})
        assert (await ops.get("/api/v1/auth/me")).status_code == 401
    finally:
        await ops.aclose()
    # The last active admin cannot remove their own access.
    me = (await stack.client.get("/api/v1/auth/me")).json()
    resp = await stack.client.patch(f"/api/v1/users/{me['id']}", json={"disabled": True})
    assert resp.status_code in (400, 403, 409)
    settings = await stack.ok("GET", "/api/v1/instance/settings")
    changed = await stack.ok("PATCH", "/api/v1/instance/settings", {"site_name": "Data desk"})
    assert changed["site_name"] == "Data desk" and settings["allow_signup"] is False


async def test_organizations_and_their_members(stack: Stack) -> None:
    orgs = await stack.ok("GET", "/api/v1/orgs")
    assert [o["role"] for o in orgs] == ["owner"]
    second = await stack.ok("POST", "/api/v1/orgs", {"name": "Second Org"}, status=201)
    renamed = await stack.ok("PATCH", f"/api/v1/orgs/{second['id']}", {"name": "Second"})
    assert renamed["name"] == "Second"
    added = await stack.ok(
        "POST",
        f"/api/v1/orgs/{second['id']}/members",
        {
            "email": "lead@example.test",
            "role": "admin",
            "name": "Lead",
            "password": "Lead-Pass-123",
        },
        status=201,
    )
    lead = await login(stack.api_url, {"email": "lead@example.test", "password": "Lead-Pass-123"})
    try:
        got = (await lead.get(f"/api/v1/orgs/{second['id']}")).json()
        assert got["role"] == "admin"
        # Admins may not create owners; owners may.
        resp = await lead.post(
            f"/api/v1/orgs/{second['id']}/members",
            json={
                "email": "boss@example.test",
                "role": "owner",
                "name": "B",
                "password": "Boss-Pass-123",
            },
        )
        assert resp.status_code == 403
        await stack.ok(
            "PATCH", f"/api/v1/orgs/{second['id']}/members/{added['user_id']}", {"role": "member"}
        )
        resp = await lead.patch(f"/api/v1/orgs/{second['id']}", json={"name": "Mine"})
        assert resp.status_code == 403
        members = await stack.ok("GET", f"/api/v1/orgs/{second['id']}/members")
        assert {m["role"] for m in members} == {"owner", "member"}
        await stack.ok(
            "DELETE", f"/api/v1/orgs/{second['id']}/members/{added['user_id']}", status=204
        )
        assert (await lead.get(f"/api/v1/orgs/{second['id']}")).status_code == 404
        me = (await stack.client.get("/api/v1/auth/me")).json()
        resp = await stack.client.delete(f"/api/v1/orgs/{second['id']}/members/{me['id']}")
        assert resp.status_code == 409
    finally:
        await lead.aclose()


async def test_people_added_to_a_project_get_a_notice(ready: Stack) -> None:
    mail.OUTBOX.clear()
    client, _ = await ready.member("viewer")
    await client.aclose()
    notice = mail.OUTBOX[-1]
    assert notice.subject == "You were added to Analytics"
    assert f"/projects/{ready.project_id}" in notice.text and "as viewer" in notice.text


async def test_request_guards(ready: Stack) -> None:
    resp = await ready.client.post(ready.p("/chat"), json={"question": ""})
    body = resp.json()
    assert resp.status_code == 422 and body["error"]["code"] == "validation_error"
    assert body["error"]["details"]["errors"][0]["loc"][-1] == "question"
    resp = await ready.client.get(ready.p("/connections/not-a-uuid"))
    assert resp.status_code == 422
    resp = await ready.client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    async with httpx.AsyncClient(base_url=ready.api_url, headers=CSRF, timeout=60) as c:
        unauthenticated = await c.get(ready.p("/connections"))
        assert unauthenticated.status_code == 401
    resp = await ready.client.get("/api/v1/nothing-here")
    assert resp.status_code == 404 and resp.json()["error"]["code"] == "http_error"
