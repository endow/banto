from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator


class SubscribeRule(BaseModel):
    type: str = Field(min_length=1)
    target: str | None = None


class RegisterRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    endpoint: HttpUrl
    heartbeat_interval_sec: int = Field(ge=1)
    down_threshold_sec: int = Field(ge=1)
    subscribe: list[SubscribeRule] = Field(default_factory=list)


class HeartbeatRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    status: dict[str, Any] = Field(default_factory=dict)


class EventRequest(BaseModel):
    event_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    type: str = Field(min_length=1)
    target: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    notify_to: list[str] = Field(default_factory=list)


class ContextRequest(BaseModel):
    query: str
    format: str | None = None


class ContextFanoutRequest(ContextRequest):
    scope: list[str] = Field(min_length=1)

    @field_validator("scope")
    @classmethod
    def scope_items_must_not_be_empty(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("scope items must not be empty")
        return value
