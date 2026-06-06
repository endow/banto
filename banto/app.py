from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Request

from banto.config import BantoConfig
from banto.models import ContextFanoutRequest, ContextRequest, EventRequest, HeartbeatRequest, RegisterRequest
from banto.security import bearer_token
from banto.state import AgentRecord, BantoState, agent_view, utc_now


def create_app(config: BantoConfig | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    state = BantoState(config or BantoConfig.from_env(), transport=transport)
    app = FastAPI(title="Banto", version="0.1.0")
    app.state.banto = state

    def get_state(request: Request) -> BantoState:
        return request.app.state.banto

    def require_agent(token: str = Depends(bearer_token), state: BantoState = Depends(get_state)) -> AgentRecord:
        agent = state.agent_for_token(token)
        if not agent:
            raise HTTPException(status_code=401, detail="invalid agent token")
        return agent

    @app.post("/register")
    async def register(
        request: RegisterRequest,
        token: str | None = Header(default=None, alias="Authorization"),
        state: BantoState = Depends(get_state),
    ) -> dict[str, Any]:
        if state.config.register_token:
            expected = f"Bearer {state.config.register_token}"
            if token != expected:
                raise HTTPException(status_code=401, detail="invalid registration token")
        elif not state.config.allow_open_register:
            raise HTTPException(status_code=401, detail="registration token is required")
        record = state.register(request)
        return {"agent_id": record.agent_id, "token": record.token}

    @app.post("/heartbeat")
    async def heartbeat(
        request: HeartbeatRequest,
        agent: AgentRecord = Depends(require_agent),
        state: BantoState = Depends(get_state),
    ) -> dict[str, Any]:
        if request.agent_id != agent.agent_id:
            raise HTTPException(status_code=403, detail="token does not match agent_id")
        agent.status = request.status
        agent.last_heartbeat_at = utc_now()
        agent.down_reported = False
        down_events = await state.evaluate_agent_down()
        return {
            "agent_id": agent.agent_id,
            "received_at": agent.last_heartbeat_at.isoformat(),
            "agent_down": down_events,
        }

    @app.post("/events")
    async def events(
        event: EventRequest,
        agent: AgentRecord = Depends(require_agent),
        state: BantoState = Depends(get_state),
    ) -> dict[str, Any]:
        if event.source != agent.agent_id:
            raise HTTPException(status_code=403, detail="token does not match source")
        return await state.deliver_event(event)

    @app.get("/agents")
    async def agents(state: BantoState = Depends(get_state)) -> dict[str, Any]:
        return {"agents": [agent_view(agent) for agent in state.agents.values()]}

    @app.get("/agents/{agent_id}/status")
    async def agent_status(
        agent_id: str = Path(min_length=1),
        state: BantoState = Depends(get_state),
    ) -> dict[str, Any]:
        agent = state.agents.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="agent not found")
        return agent_view(agent)

    @app.post("/agents/{agent_id}/context")
    async def single_context(
        body: ContextRequest,
        agent_id: str = Path(min_length=1),
        state: BantoState = Depends(get_state),
    ) -> Any:
        agent = state.agents.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="agent not found")
        try:
            status, response = await state.forward_context(agent, body.model_dump(exclude_none=True))
        except httpx.TimeoutException:
            raise HTTPException(status_code=502, detail={"reason": "timeout"}) from None
        except httpx.ConnectError:
            raise HTTPException(status_code=502, detail={"reason": "connection_refused"}) from None
        # Non-2xx responses are returned by forward_context; this catches transport-level request failures.
        except httpx.RequestError:
            raise HTTPException(status_code=502, detail={"reason": "http_error"}) from None
        if status != "ok":
            raise HTTPException(status_code=502, detail=response)
        return response

    @app.post("/context")
    async def fanout_context(
        body: ContextFanoutRequest,
        state: BantoState = Depends(get_state),
    ) -> dict[str, Any]:
        async def query(agent_id: str) -> dict[str, Any]:
            agent = state.agents.get(agent_id)
            if not agent:
                return {"agent": agent_id, "status": "not_found"}
            payload = body.model_dump(exclude_none=True)
            payload.pop("scope", None)
            try:
                status, response = await state.forward_context(agent, payload)
            except httpx.TimeoutException:
                return {"agent": agent_id, "status": "timeout"}
            # Non-2xx responses are returned by forward_context; this catches transport-level request failures.
            except httpx.RequestError:
                return {"agent": agent_id, "status": "http_error"}
            if status == "ok":
                return {"agent": agent_id, "status": "ok", "response": response}
            return {"agent": agent_id, "status": status, "response": response}

        results: list[dict[str, Any]] = []
        task_agents = {asyncio.create_task(query(agent_id)): agent_id for agent_id in body.scope}
        done, pending = await asyncio.wait(task_agents, timeout=state.config.fanout_timeout_sec)
        for task in done:
            results.append(task.result())
        for task in pending:
            task.cancel()
            results.append({"agent": task_agents[task], "status": "global_timeout"})
        return {"results": results}

    return app


app = create_app()
