# Banto

[日本語版](README.ja.md)

Banto is a lightweight REST/JSON hub for agent heartbeat state, event relay, and context forwarding.

The current design is documented in `docs/design.md`.

## What It Is For

Banto is a small hub for quickly connecting local or private agents that you control. It is not trying to define an industry-wide agent protocol or standardize interoperability across external vendors and frameworks.

The intended use case is a small set of trusted agents that only need to share thin operational primitives:

- Which agents are registered.
- Heartbeat status pushed by each agent.
- Event relay by `notify_to` or exact `type` / `target` subscription matching.
- Context forwarding without interpretation, summarization, or merging.

Banto acts as a dispatch desk for a private agent LAN. It does not decide what should be done, which agent is best, or how results should be combined. Those decisions stay with the calling agent, receiving agent, or human operator.

## Relationship to A2A

[Agent2Agent (A2A)](https://a2a-protocol.org/latest/) is an open standard for agent-to-agent interoperability, task delegation, and collaboration across different agent frameworks and vendors.

Banto does not replace A2A. A2A is the better fit when agents need external interoperability or rich task delegation and collaboration. Banto is for local or private agents you control, where much thinner primitives are enough.

If agents need stateful tasks, streaming, artifacts, capability discovery, negotiation, or cross-organization interoperability, use A2A instead of growing Banto into that shape. If needed, individual agents can expose A2A endpoints separately, or an adapter can be written outside Banto.

Banto does not provide:

- A universal agent protocol.
- An A2A-compatible task lifecycle.
- Streaming, artifacts, or capability negotiation.
- Smart routing or task orchestration.
- Built-in prompt inspection or Human-in-the-Loop policy.
- A rule engine, retry queue, or monitoring system.

When those are needed, put A2A or a dedicated policy gateway / approval agent outside Banto or inside the participating agents.

## Current Status

Banto has an initial implementation of the current design scope.

Implemented:

- In-memory agent registry.
- Heartbeat status cache.
- Subscription table with `type` / optional `target` exact matching.
- `POST /register` with registration token by default.
- `POST /heartbeat` with per-agent token authorization.
- `POST /events` synchronous fan-out with `delivered` / `failed` partial result.
- Passive `banto.agent_down` evaluation on heartbeat receipt.
- `GET /agents` and `GET /agents/{id}/status`.
- `POST /agents/{id}/context` single forwarding.
- `POST /context` fan-out forwarding.
- Endpoint allowlist and localhost opt-in.
- Local smoke check and boundary tests.

Known limitations:

- Registry and heartbeat cache are memory-only.
- `agent_down` is passive; if all agents become silent at once, no detection is triggered.
- No subscription update/delete API yet.
- No event retry queue or persistence.
- No event_id deduplication in Banto; receivers own idempotency.
- No rate limiting or overload protection beyond timeout handling.
- MCP external tool forwarding is not implemented in the initial code path.

## Run

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
```

For local agent endpoints, opt in explicitly:

```powershell
$env:BANTO_ALLOW_LOCALHOST = "true"
$env:BANTO_REGISTER_TOKEN = "dev-register-token"
.venv\Scripts\uvicorn banto.app:app --reload
```

Registration requires `BANTO_REGISTER_TOKEN` by default. For local experiments only, open registration can be enabled explicitly instead:

```powershell
$env:BANTO_ALLOW_OPEN_REGISTER = "true"
```

To run with Docker:

```powershell
docker compose up --build -d
```

The Docker service listens on `http://127.0.0.1:18000` and `POST /register` requires `Authorization: Bearer dev-register-token`. To stop it:

```powershell
docker compose down
```

When forwarding from the Docker container to a mock agent on the host, register the agent endpoint as `http://host.docker.internal:9001` and include `host.docker.internal` in `BANTO_ALLOWED_HOSTS` in `compose.yaml`.

## Quickstart

The examples below assume Banto is running on `http://127.0.0.1:8000` and a mock agent is running on `http://127.0.0.1:9001`.

Start a mock agent in another terminal:

```powershell
python examples\mock_agent.py --agent-id agent-b --port 9001
```

Register the agent:

```powershell
$registerHeaders = @{ Authorization = "Bearer dev-register-token" }
$agentB = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/register `
  -Headers $registerHeaders `
  -ContentType "application/json" `
  -Body '{
    "agent_id": "agent-b",
    "endpoint": "http://127.0.0.1:9001",
    "heartbeat_interval_sec": 5,
    "down_threshold_sec": 20,
    "subscribe": [{"type": "demo.notice"}]
  }'
```

Send a heartbeat with the agent token returned by registration:

```powershell
$agentHeaders = @{ Authorization = "Bearer $($agentB.token)" }
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/heartbeat `
  -Headers $agentHeaders `
  -ContentType "application/json" `
  -Body '{
    "agent_id": "agent-b",
    "status": {"alive": true, "load": "idle", "accepting": true}
  }'
```

Query cached status:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/agents/agent-b/status
```

Forward a context query:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/agents/agent-b/context `
  -ContentType "application/json" `
  -Body '{"query": "ping", "format": "raw"}'
```

Run the automated local smoke check:

```powershell
python examples\smoke_check.py
```

## Configuration

| Variable | Default | Description |
|---|---:|---|
| `BANTO_REGISTER_TOKEN` | unset | Bearer token required by `POST /register`. Required unless open registration is explicitly enabled. |
| `BANTO_ALLOW_OPEN_REGISTER` | `false` | Allows unauthenticated `POST /register` only when set to `true`. Use for local experiments only. |
| `BANTO_ALLOWED_HOSTS` | unset | Comma-separated allowlist of endpoint hostnames. Example: `agent-a.example.com,agent-b.example.com`. |
| `BANTO_ALLOW_LOCALHOST` | `false` | Allows `localhost` / loopback endpoints only when set to `true`. Use for local development only. |
| `BANTO_REQUEST_TIMEOUT_SEC` | `3` | Per-recipient timeout for event delivery and context forwarding. |
| `BANTO_FANOUT_TIMEOUT_SEC` | `10` | Overall timeout for fan-out operations. Unfinished recipients are reported as `global_timeout`. |

Endpoint registration is allowlist-based. Hostnames must appear in `BANTO_ALLOWED_HOSTS`, except local loopback endpoints when `BANTO_ALLOW_LOCALHOST=true`. IP literal endpoints are rejected unless they are loopback and localhost opt-in is enabled.

## Agent Contract

An agent that participates in Banto implements two endpoints.

### `POST /context`

The agent receives a context query and answers in its own context. Banto forwards the request body without interpreting it.

Request:

```json
{
  "query": "string",
  "format": "summary | raw"
}
```

Response is agent-defined JSON. Banto returns it as-is for `POST /agents/{id}/context`, or wraps it in a per-agent result for `POST /context`.

### `POST /event`

The agent receives an event delivered by Banto. Unknown event types must be ignored safely by the receiver.

Request:

```json
{
  "event_id": "string",
  "source": "agent_id",
  "type": "string",
  "target": "optional target",
  "payload": {}
}
```

Response body is not interpreted by Banto. Any 2xx response counts as delivered. Redirects are not followed and are reported as `redirect_error`. 4xx and 5xx responses are reported to the event source as `http_4xx` and `http_5xx`. If `notify_to` contains an unregistered `agent_id`, the event is still processed and that recipient is reported in `failed` as `not_found`.

## Banto API Summary

| Method | Path | Notes |
|---|---|---|
| `POST` | `/register` | Registers an agent and returns its agent token. Requires registration token unless open registration is enabled. |
| `POST` | `/heartbeat` | Updates cached status. Requires agent token matching `agent_id`. |
| `POST` | `/events` | Publishes an event. Requires agent token matching `source`; returns `delivered` / `failed`. |
| `GET` | `/agents` | Returns registered agents and cached status. |
| `GET` | `/agents/{id}/status` | Returns one agent's cached status. |
| `POST` | `/agents/{id}/context` | Forwards one context query to one agent. |
| `POST` | `/context` | Fan-out context query to `scope`; returns per-agent result array. |
