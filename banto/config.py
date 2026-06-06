from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class BantoConfig:
    allow_localhost: bool = False
    allow_open_register: bool = False
    allowed_hosts: set[str] = field(default_factory=set)
    request_timeout_sec: float = 3.0
    fanout_timeout_sec: float = 10.0
    register_token: str | None = None

    @classmethod
    def from_env(cls) -> "BantoConfig":
        allowed_hosts = {
            item.strip().lower()
            for item in os.getenv("BANTO_ALLOWED_HOSTS", "").split(",")
            if item.strip()
        }
        return cls(
            allow_localhost=os.getenv("BANTO_ALLOW_LOCALHOST", "").lower() == "true",
            allow_open_register=os.getenv("BANTO_ALLOW_OPEN_REGISTER", "").lower() == "true",
            allowed_hosts=allowed_hosts,
            request_timeout_sec=float(os.getenv("BANTO_REQUEST_TIMEOUT_SEC", "3")),
            fanout_timeout_sec=float(os.getenv("BANTO_FANOUT_TIMEOUT_SEC", "10")),
            register_token=os.getenv("BANTO_REGISTER_TOKEN") or None,
        )
