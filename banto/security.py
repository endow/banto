from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from fastapi import Header, HTTPException

from banto.config import BantoConfig


def validate_endpoint(endpoint: str, config: BantoConfig) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="endpoint must be http(s) URL")

    host = parsed.hostname.lower()
    if host in config.allowed_hosts:
        return

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if host in {"localhost"} and config.allow_localhost:
            return
        raise HTTPException(status_code=400, detail="endpoint host is not allowlisted")

    if ip.is_loopback and config.allow_localhost:
        return
    raise HTTPException(status_code=400, detail="endpoint IP is not allowlisted")


def bearer_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return authorization.removeprefix("Bearer ").strip()
