from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from banto.config import BantoConfig
from banto.models import EventRequest, RegisterRequest, SubscribeRule
from banto.security import validate_endpoint


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AgentRecord:
    agent_id: str
    endpoint: str
    heartbeat_interval_sec: int
    down_threshold_sec: int
    subscribe: list[SubscribeRule]
    token: str
    registered_at: datetime = field(default_factory=utc_now)
    last_heartbeat_at: datetime | None = None
    status: dict[str, Any] | None = None
    down_reported: bool = False


class BantoState:
    def __init__(self, config: BantoConfig, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.config = config
        self.agents: dict[str, AgentRecord] = {}
        self.transport = transport

    def agent_for_token(self, token: str) -> AgentRecord | None:
        return next((agent for agent in self.agents.values() if agent.token == token), None)

    def register(self, data: RegisterRequest) -> AgentRecord:
        endpoint = str(data.endpoint).rstrip("/")
        validate_endpoint(endpoint, self.config)
        existing = self.agents.get(data.agent_id)
        token = existing.token if existing else secrets.token_urlsafe(32)
        record = AgentRecord(
            agent_id=data.agent_id,
            endpoint=endpoint,
            heartbeat_interval_sec=data.heartbeat_interval_sec,
            down_threshold_sec=data.down_threshold_sec,
            subscribe=data.subscribe,
            token=token,
            last_heartbeat_at=existing.last_heartbeat_at if existing else None,
            status=existing.status if existing else None,
            down_reported=existing.down_reported if existing else False,
        )
        self.agents[data.agent_id] = record
        return record

    def resolve_recipients(self, event: EventRequest) -> list[AgentRecord]:
        if event.notify_to:
            return [self.agents[agent_id] for agent_id in event.notify_to if agent_id in self.agents]

        recipients: list[AgentRecord] = []
        for agent in self.agents.values():
            for rule in agent.subscribe:
                if rule.type != event.type:
                    continue
                if rule.target is None or rule.target == event.target:
                    recipients.append(agent)
                    break
        return recipients

    async def deliver_event(self, event: EventRequest) -> dict[str, Any]:
        recipients = self.resolve_recipients(event)
        missing = [{"agent": agent_id, "reason": "not_found"} for agent_id in event.notify_to if agent_id not in self.agents]
        return await self._fanout_event(event, recipients, missing)

    async def evaluate_agent_down(self) -> list[dict[str, Any]]:
        now = utc_now()
        results: list[dict[str, Any]] = []
        for agent in list(self.agents.values()):
            if agent.last_heartbeat_at is None or agent.down_reported:
                continue
            expires_at = agent.last_heartbeat_at.timestamp() + agent.down_threshold_sec
            if expires_at >= now.timestamp():
                continue

            agent.down_reported = True
            event = EventRequest(
                event_id=f"banto.agent_down:{agent.agent_id}:{int(now.timestamp())}",
                source="banto",
                type="banto.agent_down",
                target=agent.agent_id,
                payload={
                    "agent_id": agent.agent_id,
                    "last_heartbeat_at": agent.last_heartbeat_at.isoformat(),
                    "down_threshold_sec": agent.down_threshold_sec,
                },
            )
            results.append(await self.deliver_event(event))
        return results

    async def forward_context(self, agent: AgentRecord, body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=self.config.request_timeout_sec,
            follow_redirects=False,
        ) as client:
            response = await client.post(f"{agent.endpoint}/context", json=body)
        if not response.is_success:
            return "http_error", {"status_code": response.status_code, "body": response.text}
        try:
            return "ok", response.json()
        except ValueError:
            return "invalid_response", {"reason": "invalid_json", "body": response.text}

    async def _post_event(self, agent: AgentRecord, event: EventRequest) -> tuple[str, str | None]:
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=self.config.request_timeout_sec,
            follow_redirects=False,
        ) as client:
            response = await client.post(f"{agent.endpoint}/event", json=event.model_dump(exclude_none=True))
        if not response.is_success:
            if 300 <= response.status_code < 400:
                return agent.agent_id, "redirect_error"
            if response.status_code >= 500:
                return agent.agent_id, "http_5xx"
            if response.status_code >= 400:
                return agent.agent_id, "http_4xx"
            return agent.agent_id, "transport_error"
        return agent.agent_id, None

    async def _fanout_event(
        self,
        event: EventRequest,
        recipients: list[AgentRecord],
        initial_failed: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        delivered: list[str] = []
        failed: list[dict[str, str]] = list(initial_failed or [])
        if not recipients:
            return {"event_id": event.event_id, "delivered": delivered, "failed": failed}

        async def deliver(agent: AgentRecord) -> tuple[str, str | None]:
            try:
                return await self._post_event(agent, event)
            except httpx.TimeoutException:
                return agent.agent_id, "timeout"
            except httpx.ConnectError:
                return agent.agent_id, "connection_refused"
            except httpx.RequestError:
                return agent.agent_id, "transport_error"

        task_agents = {asyncio.create_task(deliver(agent)): agent.agent_id for agent in recipients}
        done, pending = await asyncio.wait(task_agents, timeout=self.config.fanout_timeout_sec)
        for task in done:
            agent_id, reason = task.result()
            if reason:
                failed.append({"agent": agent_id, "reason": reason})
            else:
                delivered.append(agent_id)
        for task in pending:
            task.cancel()
            failed.append({"agent": task_agents[task], "reason": "global_timeout"})

        return {"event_id": event.event_id, "delivered": delivered, "failed": failed}


def agent_view(agent: AgentRecord) -> dict[str, Any]:
    state = "unknown"
    if agent.last_heartbeat_at is not None:
        expires_at = agent.last_heartbeat_at.timestamp() + agent.down_threshold_sec
        state = "down" if expires_at < utc_now().timestamp() else "alive"
    return {
        "agent_id": agent.agent_id,
        "endpoint": agent.endpoint,
        "state": state,
        "status": agent.status,
        "last_heartbeat_at": agent.last_heartbeat_at.isoformat() if agent.last_heartbeat_at else None,
        "heartbeat_interval_sec": agent.heartbeat_interval_sec,
        "down_threshold_sec": agent.down_threshold_sec,
        "subscribe": [rule.model_dump(exclude_none=True) for rule in agent.subscribe],
    }
