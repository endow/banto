from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel


class ContextRequest(BaseModel):
    query: str
    format: str | None = None


def create_app(agent_id: str) -> FastAPI:
    app = FastAPI(title=f"Banto mock agent: {agent_id}")
    events: list[dict[str, Any]] = []

    @app.post("/context")
    async def context(request: ContextRequest) -> dict[str, Any]:
        return {
            "agent_id": agent_id,
            "query": request.query,
            "format": request.format,
            "answered_at": datetime.now(timezone.utc).isoformat(),
        }

    @app.post("/event")
    async def event(payload: dict[str, Any]) -> dict[str, Any]:
        events.append(payload)
        return {"agent_id": agent_id, "received": True, "event_count": len(events)}

    @app.get("/events")
    async def list_events() -> dict[str, Any]:
        return {"agent_id": agent_id, "events": events}

    return app


app = create_app("mock")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-id", default="mock")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9001)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(create_app(args.agent_id), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
