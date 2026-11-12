"""Model providers (A12): every acceptance criterion runs on the deterministic mock with no
external provider; each real adapter answers a question through its own wire format
against the mock service; nothing is configured by default."""

from __future__ import annotations

import pytest

from tests.integration.conftest import Sources, Stack

pytestmark = pytest.mark.integration


async def test_a12_no_provider_is_configured_by_default(stack: Stack, sources: Sources) -> None:
    await stack.project("Fresh")
    assert await stack.ok("GET", stack.p("/providers")) == []
    conn = await stack.connection(sources.pg())
    resp = await stack.client.post(
        stack.p("/chat"), json={"connection_id": conn["id"], "question": "How many orders?"}
    )
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "no_provider"
    # Explaining from the syntax tree needs no provider at all.
    out = await stack.ok(
        "POST",
        stack.p("/sql/explain"),
        {"dialect": "postgresql", "sql": "SELECT 1", "use_model": False},
    )
    assert out["source"] == "syntax"


@pytest.mark.parametrize("kind", ["openai", "openai_compatible", "anthropic", "gemini", "ollama"])
async def test_a12_each_real_adapter_answers_through_its_wire_format(
    ready: Stack, sources: Sources, kind: str
) -> None:
    prov = await ready.provider(f"real-{kind.replace('_', '-')}", kind)
    test = await ready.ok("POST", ready.p(f"/providers/{prov['id']}/test"))
    assert test["ok"] is True and test["models"], test
    conn = await ready.connection(sources.pg())
    msg = await ready.ask(
        "How many orders per status?", connection_id=conn["id"], provider_id=prov["id"]
    )
    assert msg["status"] == "answered", msg
    assert msg["provider_name"] == prov["name"] and msg["model"] == "mock-sql-small"
    assert msg["input_tokens"] > 0 and msg["output_tokens"] > 0
    # The same deterministic answer as the built-in mock provider.
    baseline = await ready.ask("How many orders per status?", connection_id=conn["id"])
    assert msg["sql"] == baseline["sql"] and msg["page"]["rows"] == baseline["page"]["rows"]
    family = {
        "openai": "v1",
        "openai_compatible": "v1",
        "anthropic": "anthropic",
        "gemini": "gemini",
        "ollama": "ollama",
    }[kind]
    auth = (await ready.client.get(f"{ready.mock_ai_url}/_mock/auth")).json()
    assert prov["name"] in auth[family]
    calls = (await ready.client.get(f"{ready.mock_ai_url}/_mock/calls")).json()
    assert any(c["family"] == family and c["task"] == "TASK: generate" for c in calls)


async def test_retries_ride_out_a_brief_provider_outage(ready: Stack, sources: Sources) -> None:
    prov = await ready.provider("flaky", "openai_compatible")
    conn = await ready.connection(sources.pg())
    await ready.client.post(f"{ready.mock_ai_url}/_mock/fail", params={"status": 503, "times": 2})
    msg = await ready.ask(
        "How many orders per status?", connection_id=conn["id"], provider_id=prov["id"]
    )
    assert msg["status"] == "answered", msg
    await ready.client.post(f"{ready.mock_ai_url}/_mock/fail", params={"status": 401, "times": 1})
    msg = await ready.ask("How many customers?", connection_id=conn["id"], provider_id=prov["id"])
    assert msg["status"] == "failed" and msg["error_code"] == "provider_auth"


async def test_default_provider_and_turning_one_off(ready: Stack, sources: Sources) -> None:
    providers = await ready.ok("GET", ready.p("/providers"))
    assert [p["is_default"] for p in providers] == [True]
    gw = await ready.provider("gateway", "openai_compatible", is_default=True)
    listed = await ready.ok("GET", ready.p("/providers"))
    assert [(p["name"], p["is_default"]) for p in listed] == [("gateway", True), ("mock", False)]
    conn = await ready.connection(sources.pg())
    msg = await ready.ask("How many orders per status?", connection_id=conn["id"])
    assert msg["provider_name"] == "gateway"
    await ready.ok("PATCH", ready.p(f"/providers/{gw['id']}"), {"enabled": False})
    msg = await ready.ask("How many orders per status?", connection_id=conn["id"])
    assert msg["provider_name"] == "mock"
    resp = await ready.client.post(
        ready.p("/chat"),
        json={"connection_id": conn["id"], "question": "x", "provider_id": gw["id"]},
    )
    assert resp.status_code == 201
    # A provider that is turned off fails the question with a clear reason.
    out = await ready.ok("GET", ready.p(f"/messages/{resp.json()['id']}"), params={"wait": 20})
    assert out["status"] == "failed" and "turned off" in out["error"]
    await ready.ok("DELETE", ready.p(f"/providers/{gw['id']}"), status=204)
    # Validation: a private address is allowed (local Ollama); metadata never is.
    resp = await ready.client.post(
        ready.p("/providers"),
        json={"name": "meta", "kind": "openai_compatible", "base_url": "http://169.254.169.254/v1"},
    )
    assert resp.status_code == 422
    resp = await ready.client.post(
        ready.p("/providers"), json={"name": "x", "kind": "openai_compatible"}
    )
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "base_url_required"
