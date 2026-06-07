from __future__ import annotations

from datetime import timedelta
from typing import Any

import anyio
import httpx
import pytest

from banto.app import BantoConfig, create_app, utc_now


def make_outbound_transport(calls: list[dict[str, Any]]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "host": request.url.host,
                "path": request.url.path,
                "json": httpx.Response(200, content=request.content).json(),
            }
        )
        if request.url.path == "/context":
            return httpx.Response(200, json={"from": request.url.host, "ok": True})
        return httpx.Response(204)

    return httpx.MockTransport(handler)


def make_error_transport(error: Exception) -> httpx.MockTransport:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise error

    return httpx.MockTransport(handler)


def make_route_transport(routes: dict[tuple[str, str], httpx.Response | Exception]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        result = routes.get((request.url.host or "", request.url.path))
        if isinstance(result, Exception):
            raise result
        if result is not None:
            return result
        if request.url.path == "/context":
            return httpx.Response(200, json={"from": request.url.host, "ok": True})
        return httpx.Response(204)

    return httpx.MockTransport(handler)


async def register(client: httpx.AsyncClient, agent_id: str, endpoint: str, subscribe: list[dict[str, str]] | None = None) -> str:
    response = await client.post(
        "/register",
        json={
            "agent_id": agent_id,
            "endpoint": endpoint,
            "heartbeat_interval_sec": 5,
            "down_threshold_sec": 10,
            "subscribe": subscribe or [],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


@pytest.fixture
async def banto_client() -> tuple[httpx.AsyncClient, list[dict[str, Any]], Any]:
    calls: list[dict[str, Any]] = []
    app = create_app(
        BantoConfig(allow_open_register=True, allowed_hosts={"agent-a.test", "agent-b.test"}),
        transport=make_outbound_transport(calls),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://banto.test",
    ) as client:
        yield client, calls, app


async def test_events_notify_to_uses_synchronous_fanout_with_partial_result(banto_client: tuple[httpx.AsyncClient, list[dict[str, Any]], Any]) -> None:
    client, calls, _app = banto_client
    agent_a_token = await register(client, "agent-a", "http://agent-a.test")
    await register(client, "agent-b", "http://agent-b.test")

    response = await client.post(
        "/events",
        headers={"Authorization": f"Bearer {agent_a_token}"},
        json={
            "event_id": "evt-1",
            "source": "agent-a",
            "type": "custom.event",
            "payload": {"value": 1},
            "notify_to": ["agent-b"],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"event_id": "evt-1", "delivered": ["agent-b"], "failed": []}
    assert [(call["host"], call["path"]) for call in calls] == [("agent-b.test", "/event")]


async def test_dashboard_serves_thin_ui_for_status_and_context() -> None:
    app = create_app(BantoConfig(allow_open_register=True, allowed_hosts={"agent-b.test"}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        response = await client.get("/dashboard")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Banto Dashboard" in response.text
    assert "Auto refresh" in response.text
    assert "REFRESH_INTERVAL_MS = 5000" in response.text
    assert 'fetch("/agents")' in response.text
    assert 'fetch("/context"' in response.text


async def test_events_reports_recipient_4xx_as_http_4xx() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/event":
            return httpx.Response(404)
        return httpx.Response(200, json={})

    app = create_app(
        BantoConfig(allow_open_register=True, allowed_hosts={"agent-a.test", "agent-b.test"}),
        transport=httpx.MockTransport(handler),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        agent_a_token = await register(client, "agent-a", "http://agent-a.test")
        await register(client, "agent-b", "http://agent-b.test")
        response = await client.post(
            "/events",
            headers={"Authorization": f"Bearer {agent_a_token}"},
            json={
                "event_id": "evt-4xx",
                "source": "agent-a",
                "type": "custom.event",
                "notify_to": ["agent-b"],
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "event_id": "evt-4xx",
        "delivered": [],
        "failed": [{"agent": "agent-b", "reason": "http_4xx"}],
    }


async def test_events_reports_transport_error_separately_from_connection_refused() -> None:
    app = create_app(
        BantoConfig(allow_open_register=True, allowed_hosts={"agent-a.test", "agent-b.test"}),
        transport=make_error_transport(httpx.RemoteProtocolError("bad protocol")),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        agent_a_token = await register(client, "agent-a", "http://agent-a.test")
        await register(client, "agent-b", "http://agent-b.test")
        response = await client.post(
            "/events",
            headers={"Authorization": f"Bearer {agent_a_token}"},
            json={
                "event_id": "evt-transport",
                "source": "agent-a",
                "type": "custom.event",
                "notify_to": ["agent-b"],
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "event_id": "evt-transport",
        "delivered": [],
        "failed": [{"agent": "agent-b", "reason": "transport_error"}],
    }


async def test_events_reports_redirect_response_as_redirect_error() -> None:
    app = create_app(
        BantoConfig(allow_open_register=True, allowed_hosts={"agent-a.test", "agent-b.test"}),
        transport=make_route_transport({("agent-b.test", "/event"): httpx.Response(307)}),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        agent_a_token = await register(client, "agent-a", "http://agent-a.test")
        await register(client, "agent-b", "http://agent-b.test")
        response = await client.post(
            "/events",
            headers={"Authorization": f"Bearer {agent_a_token}"},
            json={
                "event_id": "evt-redirect",
                "source": "agent-a",
                "type": "custom.event",
                "notify_to": ["agent-b"],
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "event_id": "evt-redirect",
        "delivered": [],
        "failed": [{"agent": "agent-b", "reason": "redirect_error"}],
    }


async def test_events_reports_http_5xx_timeout_and_connection_refused_with_partial_results() -> None:
    app = create_app(
        BantoConfig(allow_open_register=True, allowed_hosts={"agent-a.test", "agent-b.test", "alpha.test", "beta.test"}),
        transport=make_route_transport(
            {
                ("agent-b.test", "/event"): httpx.Response(503),
                ("alpha.test", "/event"): httpx.TimeoutException("timeout"),
                ("beta.test", "/event"): httpx.ConnectError("refused"),
            }
        ),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        agent_a_token = await register(client, "agent-a", "http://agent-a.test")
        await register(client, "agent-b", "http://agent-b.test")
        await register(client, "alpha", "http://alpha.test")
        await register(client, "beta", "http://beta.test")

        response = await client.post(
            "/events",
            headers={"Authorization": f"Bearer {agent_a_token}"},
            json={
                "event_id": "evt-partial",
                "source": "agent-a",
                "type": "custom.event",
                "notify_to": ["agent-a", "agent-b", "alpha", "beta"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["event_id"] == "evt-partial"
    assert body["delivered"] == ["agent-a"]
    assert sorted(body["failed"], key=lambda item: item["agent"]) == [
        {"agent": "agent-b", "reason": "http_5xx"},
        {"agent": "alpha", "reason": "timeout"},
        {"agent": "beta", "reason": "connection_refused"},
    ]


async def test_events_reports_global_timeout_for_unfinished_recipient() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "agent-b.test" and request.url.path == "/event":
            await anyio.sleep(1)
        return httpx.Response(204)

    app = create_app(
        BantoConfig(
            allow_open_register=True,
            allowed_hosts={"agent-a.test", "agent-b.test"},
            fanout_timeout_sec=0.01,
        ),
        transport=httpx.MockTransport(handler),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        agent_a_token = await register(client, "agent-a", "http://agent-a.test")
        await register(client, "agent-b", "http://agent-b.test")
        response = await client.post(
            "/events",
            headers={"Authorization": f"Bearer {agent_a_token}"},
            json={
                "event_id": "evt-global-timeout",
                "source": "agent-a",
                "type": "custom.event",
                "notify_to": ["agent-b"],
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "event_id": "evt-global-timeout",
        "delivered": [],
        "failed": [{"agent": "agent-b", "reason": "global_timeout"}],
    }


async def test_events_reports_unknown_notify_to_recipient_as_not_found(
    banto_client: tuple[httpx.AsyncClient, list[dict[str, Any]], Any],
) -> None:
    client, calls, _app = banto_client
    agent_a_token = await register(client, "agent-a", "http://agent-a.test")
    await register(client, "agent-b", "http://agent-b.test")

    response = await client.post(
        "/events",
        headers={"Authorization": f"Bearer {agent_a_token}"},
        json={
            "event_id": "evt-missing-recipient",
            "source": "agent-a",
            "type": "custom.event",
            "notify_to": ["agent-b", "missing"],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "event_id": "evt-missing-recipient",
        "delivered": ["agent-b"],
        "failed": [{"agent": "missing", "reason": "not_found"}],
    }
    assert [(call["host"], call["path"]) for call in calls] == [("agent-b.test", "/event")]


async def test_context_fanout_allows_single_scope_and_returns_array(banto_client: tuple[httpx.AsyncClient, list[dict[str, Any]], Any]) -> None:
    client, _calls, _app = banto_client
    await register(client, "agent-b", "http://agent-b.test")

    response = await client.post("/context", json={"query": "hello", "scope": ["agent-b"], "format": "raw"})

    assert response.status_code == 200
    assert response.json() == {
        "results": [{"agent": "agent-b", "status": "ok", "response": {"from": "agent-b.test", "ok": True}}]
    }


async def test_context_fanout_reports_not_found_timeout_and_http_error() -> None:
    app = create_app(
        BantoConfig(allow_open_register=True, allowed_hosts={"agent-b.test", "alpha.test", "beta.test"}),
        transport=make_route_transport(
            {
                ("alpha.test", "/context"): httpx.TimeoutException("timeout"),
                ("beta.test", "/context"): httpx.Response(500, text="broken"),
            }
        ),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        await register(client, "agent-b", "http://agent-b.test")
        await register(client, "alpha", "http://alpha.test")
        await register(client, "beta", "http://beta.test")

        response = await client.post(
            "/context",
            json={"query": "hello", "scope": ["agent-b", "missing", "alpha", "beta"], "format": "raw"},
        )

    assert response.status_code == 200
    body = response.json()
    results = sorted(body["results"], key=lambda item: item["agent"])
    assert results == [
        {"agent": "agent-b", "status": "ok", "response": {"from": "agent-b.test", "ok": True}},
        {"agent": "alpha", "status": "timeout"},
        {
            "agent": "beta",
            "status": "http_error",
            "response": {"status_code": 500, "body": "broken"},
        },
        {"agent": "missing", "status": "not_found"},
    ]


async def test_context_fanout_reports_redirect_response_as_http_error() -> None:
    app = create_app(
        BantoConfig(allow_open_register=True, allowed_hosts={"agent-b.test"}),
        transport=make_route_transport({("agent-b.test", "/context"): httpx.Response(307)}),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        await register(client, "agent-b", "http://agent-b.test")
        response = await client.post("/context", json={"query": "hello", "scope": ["agent-b"]})

    assert response.status_code == 200
    assert response.json() == {
        "results": [{"agent": "agent-b", "status": "http_error", "response": {"status_code": 307, "body": ""}}]
    }


async def test_context_fanout_reports_invalid_json_2xx_as_invalid_response() -> None:
    app = create_app(
        BantoConfig(allow_open_register=True, allowed_hosts={"agent-b.test"}),
        transport=make_route_transport({("agent-b.test", "/context"): httpx.Response(200, text="not json")}),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        await register(client, "agent-b", "http://agent-b.test")
        response = await client.post("/context", json={"query": "hello", "scope": ["agent-b"]})

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "agent": "agent-b",
                "status": "invalid_response",
                "response": {"reason": "invalid_json", "body": "not json"},
            }
        ]
    }


async def test_context_fanout_reports_global_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "agent-b.test" and request.url.path == "/context":
            await anyio.sleep(1)
        return httpx.Response(200, json={"ok": True})

    app = create_app(
        BantoConfig(
            allow_open_register=True,
            allowed_hosts={"agent-b.test"},
            fanout_timeout_sec=0.01,
        ),
        transport=httpx.MockTransport(handler),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        await register(client, "agent-b", "http://agent-b.test")
        response = await client.post("/context", json={"query": "hello", "scope": ["agent-b"]})

    assert response.status_code == 200
    assert response.json() == {"results": [{"agent": "agent-b", "status": "global_timeout"}]}


async def test_subscription_target_matching_is_exact_or_type_wildcard(banto_client: tuple[httpx.AsyncClient, list[dict[str, Any]], Any]) -> None:
    client, calls, _app = banto_client
    agent_a_token = await register(client, "agent-a", "http://agent-a.test")
    await register(client, "agent-b", "http://agent-b.test", subscribe=[{"type": "notice", "target": "agent-b"}])

    response = await client.post(
        "/events",
        headers={"Authorization": f"Bearer {agent_a_token}"},
        json={"event_id": "evt-2", "source": "agent-a", "type": "notice", "target": "agent-a"},
    )

    assert response.status_code == 200
    assert response.json()["delivered"] == []
    assert calls == []


async def test_events_fanout_uses_subscription_type_wildcard_when_notify_to_is_empty(
    banto_client: tuple[httpx.AsyncClient, list[dict[str, Any]], Any],
) -> None:
    client, calls, _app = banto_client
    agent_a_token = await register(client, "agent-a", "http://agent-a.test")
    await register(client, "agent-b", "http://agent-b.test", subscribe=[{"type": "notice"}])

    response = await client.post(
        "/events",
        headers={"Authorization": f"Bearer {agent_a_token}"},
        json={"event_id": "evt-subscription", "source": "agent-a", "type": "notice", "target": "agent-a"},
    )

    assert response.status_code == 200
    assert response.json() == {"event_id": "evt-subscription", "delivered": ["agent-b"], "failed": []}
    assert [(call["host"], call["path"]) for call in calls] == [("agent-b.test", "/event")]


async def test_passive_agent_down_is_evaluated_on_heartbeat(banto_client: tuple[httpx.AsyncClient, list[dict[str, Any]], Any]) -> None:
    client, calls, app = banto_client
    agent_a_token = await register(client, "agent-a", "http://agent-a.test")
    agent_b_token = await register(
        client,
        "agent-b",
        "http://agent-b.test",
        subscribe=[{"type": "banto.agent_down", "target": "agent-a"}],
    )

    await client.post(
        "/heartbeat",
        headers={"Authorization": f"Bearer {agent_a_token}"},
        json={"agent_id": "agent-a", "status": {"alive": True}},
    )
    app.state.banto.agents["agent-a"].last_heartbeat_at = utc_now() - timedelta(seconds=20)

    response = await client.post(
        "/heartbeat",
        headers={"Authorization": f"Bearer {agent_b_token}"},
        json={"agent_id": "agent-b", "status": {"alive": True}},
    )

    assert response.status_code == 200
    assert response.json()["agent_down"][0]["delivered"] == ["agent-b"]
    assert calls[0]["path"] == "/event"
    assert calls[0]["json"]["type"] == "banto.agent_down"
    assert calls[0]["json"]["target"] == "agent-a"


async def test_agent_without_heartbeat_is_unknown_and_not_reported_down(banto_client: tuple[httpx.AsyncClient, list[dict[str, Any]], Any]) -> None:
    client, calls, _app = banto_client
    await register(client, "agent-a", "http://agent-a.test")
    agent_b_token = await register(
        client,
        "agent-b",
        "http://agent-b.test",
        subscribe=[{"type": "banto.agent_down", "target": "agent-a"}],
    )

    status = await client.get("/agents/agent-a/status")
    heartbeat = await client.post(
        "/heartbeat",
        headers={"Authorization": f"Bearer {agent_b_token}"},
        json={"agent_id": "agent-b", "status": {"alive": True}},
    )

    assert status.status_code == 200
    assert status.json()["state"] == "unknown"
    assert heartbeat.status_code == 200
    assert heartbeat.json()["agent_down"] == []
    assert calls == []


async def test_reregister_preserves_down_reported_until_recovery_heartbeat(
    banto_client: tuple[httpx.AsyncClient, list[dict[str, Any]], Any],
) -> None:
    client, calls, app = banto_client
    agent_a_token = await register(client, "agent-a", "http://agent-a.test")
    agent_b_token = await register(
        client,
        "agent-b",
        "http://agent-b.test",
        subscribe=[{"type": "banto.agent_down", "target": "agent-a"}],
    )

    await client.post(
        "/heartbeat",
        headers={"Authorization": f"Bearer {agent_a_token}"},
        json={"agent_id": "agent-a", "status": {"alive": True}},
    )
    app.state.banto.agents["agent-a"].last_heartbeat_at = utc_now() - timedelta(seconds=20)
    first_down = await client.post(
        "/heartbeat",
        headers={"Authorization": f"Bearer {agent_b_token}"},
        json={"agent_id": "agent-b", "status": {"alive": True}},
    )

    reregister = await client.post(
        "/register",
        json={
            "agent_id": "agent-a",
            "endpoint": "http://agent-a.test",
            "heartbeat_interval_sec": 5,
            "down_threshold_sec": 10,
            "subscribe": [],
        },
    )
    assert first_down.status_code == 200
    assert first_down.json()["agent_down"][0]["delivered"] == ["agent-b"]
    assert reregister.status_code == 200
    assert reregister.json()["token"] == agent_a_token
    assert app.state.banto.agents["agent-a"].down_reported is True

    recovered = await client.post(
        "/heartbeat",
        headers={"Authorization": f"Bearer {agent_a_token}"},
        json={"agent_id": "agent-a", "status": {"alive": True}},
    )
    assert recovered.status_code == 200
    assert app.state.banto.agents["agent-a"].down_reported is False

    app.state.banto.agents["agent-a"].last_heartbeat_at = utc_now() - timedelta(seconds=20)
    second_down = await client.post(
        "/heartbeat",
        headers={"Authorization": f"Bearer {agent_b_token}"},
        json={"agent_id": "agent-b", "status": {"alive": True}},
    )

    assert second_down.status_code == 200
    assert second_down.json()["agent_down"][0]["delivered"] == ["agent-b"]
    assert [call["json"]["type"] for call in calls] == ["banto.agent_down", "banto.agent_down"]


async def test_heartbeat_requires_valid_agent_token(banto_client: tuple[httpx.AsyncClient, list[dict[str, Any]], Any]) -> None:
    client, _calls, _app = banto_client
    await register(client, "agent-b", "http://agent-b.test")

    missing = await client.post("/heartbeat", json={"agent_id": "agent-b", "status": {"alive": True}})
    invalid = await client.post(
        "/heartbeat",
        headers={"Authorization": "Bearer invalid"},
        json={"agent_id": "agent-b", "status": {"alive": True}},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401


async def test_heartbeat_rejects_token_agent_mismatch(banto_client: tuple[httpx.AsyncClient, list[dict[str, Any]], Any]) -> None:
    client, _calls, _app = banto_client
    agent_a_token = await register(client, "agent-a", "http://agent-a.test")
    await register(client, "agent-b", "http://agent-b.test")

    response = await client.post(
        "/heartbeat",
        headers={"Authorization": f"Bearer {agent_a_token}"},
        json={"agent_id": "agent-b", "status": {"alive": True}},
    )

    assert response.status_code == 403


async def test_events_require_valid_agent_token(banto_client: tuple[httpx.AsyncClient, list[dict[str, Any]], Any]) -> None:
    client, _calls, _app = banto_client
    await register(client, "agent-a", "http://agent-a.test")

    missing = await client.post("/events", json={"event_id": "evt-auth", "source": "agent-a", "type": "notice"})
    invalid = await client.post(
        "/events",
        headers={"Authorization": "Bearer invalid"},
        json={"event_id": "evt-auth", "source": "agent-a", "type": "notice"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401


async def test_events_reject_token_source_mismatch(banto_client: tuple[httpx.AsyncClient, list[dict[str, Any]], Any]) -> None:
    client, _calls, _app = banto_client
    agent_a_token = await register(client, "agent-a", "http://agent-a.test")
    await register(client, "agent-b", "http://agent-b.test")

    response = await client.post(
        "/events",
        headers={"Authorization": f"Bearer {agent_a_token}"},
        json={"event_id": "evt-mismatch", "source": "agent-b", "type": "notice"},
    )

    assert response.status_code == 403


async def test_single_context_returns_404_for_unregistered_agent(banto_client: tuple[httpx.AsyncClient, list[dict[str, Any]], Any]) -> None:
    client, _calls, _app = banto_client

    response = await client.post("/agents/missing/context", json={"query": "hello"})

    assert response.status_code == 404


async def test_reregister_preserves_token_and_heartbeat_state_while_updating_routing() -> None:
    app = create_app(BantoConfig(allow_open_register=True, allowed_hosts={"agent-a.test", "agent-b.test"}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        first = await client.post(
            "/register",
            json={
                "agent_id": "agent-b",
                "endpoint": "http://agent-b.test",
                "heartbeat_interval_sec": 5,
                "down_threshold_sec": 10,
                "subscribe": [{"type": "old.notice"}],
            },
        )
        token = first.json()["token"]
        await client.post(
            "/heartbeat",
            headers={"Authorization": f"Bearer {token}"},
            json={"agent_id": "agent-b", "status": {"alive": True, "load": "idle"}},
        )

        second = await client.post(
            "/register",
            json={
                "agent_id": "agent-b",
                "endpoint": "http://agent-a.test",
                "heartbeat_interval_sec": 7,
                "down_threshold_sec": 14,
                "subscribe": [{"type": "new.notice", "target": "agent-b"}],
            },
        )
        status = await client.get("/agents/agent-b/status")

    assert second.status_code == 200
    assert second.json()["token"] == token
    body = status.json()
    assert body["endpoint"] == "http://agent-a.test"
    assert body["status"] == {"alive": True, "load": "idle"}
    assert body["last_heartbeat_at"] is not None
    assert body["heartbeat_interval_sec"] == 7
    assert body["down_threshold_sec"] == 14
    assert body["subscribe"] == [{"type": "new.notice", "target": "agent-b"}]


async def test_register_rejects_non_allowlisted_endpoint() -> None:
    app = create_app(BantoConfig(allow_open_register=True, allowed_hosts={"agent-b.test"}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        response = await client.post(
            "/register",
            json={
                "agent_id": "bad",
                "endpoint": "http://127.0.0.1:8080",
                "heartbeat_interval_sec": 5,
                "down_threshold_sec": 10,
                "subscribe": [],
            },
        )

    assert response.status_code == 400


async def test_register_rejects_public_ip_unless_allowlisted() -> None:
    app = create_app(BantoConfig(allow_open_register=True, allowed_hosts={"agent-b.test"}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        response = await client.post(
            "/register",
            json={
                "agent_id": "bad",
                "endpoint": "http://8.8.8.8:8080",
                "heartbeat_interval_sec": 5,
                "down_threshold_sec": 10,
                "subscribe": [],
            },
        )

    assert response.status_code == 400


async def test_register_allows_loopback_only_with_localhost_opt_in() -> None:
    app = create_app(BantoConfig(allow_open_register=True, allow_localhost=True))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        response = await client.post(
            "/register",
            json={
                "agent_id": "local",
                "endpoint": "http://127.0.0.1:9001",
                "heartbeat_interval_sec": 5,
                "down_threshold_sec": 10,
                "subscribe": [],
            },
        )

    assert response.status_code == 200


async def test_register_requires_registration_token_by_default() -> None:
    app = create_app(BantoConfig(allowed_hosts={"agent-b.test"}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        response = await client.post(
            "/register",
            json={
                "agent_id": "agent-b",
                "endpoint": "http://agent-b.test",
                "heartbeat_interval_sec": 5,
                "down_threshold_sec": 10,
                "subscribe": [],
            },
        )

    assert response.status_code == 401


async def test_register_accepts_configured_registration_token() -> None:
    app = create_app(BantoConfig(register_token="secret", allowed_hosts={"agent-b.test"}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        response = await client.post(
            "/register",
            headers={"Authorization": "Bearer secret"},
            json={
                "agent_id": "agent-b",
                "endpoint": "http://agent-b.test",
                "heartbeat_interval_sec": 5,
                "down_threshold_sec": 10,
                "subscribe": [],
            },
        )

    assert response.status_code == 200
    assert response.json()["agent_id"] == "agent-b"


async def test_single_context_timeout_returns_502() -> None:
    app = create_app(
        BantoConfig(allow_open_register=True, allowed_hosts={"agent-b.test"}),
        transport=make_error_transport(httpx.TimeoutException("timeout")),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        await register(client, "agent-b", "http://agent-b.test")
        response = await client.post("/agents/agent-b/context", json={"query": "hello"})

    assert response.status_code == 502
    assert response.json()["detail"]["reason"] == "timeout"


async def test_single_context_connect_error_returns_502() -> None:
    app = create_app(
        BantoConfig(allow_open_register=True, allowed_hosts={"agent-b.test"}),
        transport=make_error_transport(httpx.ConnectError("refused")),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        await register(client, "agent-b", "http://agent-b.test")
        response = await client.post("/agents/agent-b/context", json={"query": "hello"})

    assert response.status_code == 502
    assert response.json()["detail"]["reason"] == "connection_refused"


async def test_single_context_invalid_json_2xx_returns_502() -> None:
    app = create_app(
        BantoConfig(allow_open_register=True, allowed_hosts={"agent-b.test"}),
        transport=make_route_transport({("agent-b.test", "/context"): httpx.Response(204)}),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://banto.test") as client:
        await register(client, "agent-b", "http://agent-b.test")
        response = await client.post("/agents/agent-b/context", json={"query": "hello"})

    assert response.status_code == 502
    assert response.json()["detail"] == {"reason": "invalid_json", "body": ""}
