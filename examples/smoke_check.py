from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class ProcessHandle:
    name: str
    process: subprocess.Popen[Any]


def wait_for(url: str, timeout_sec: float = 10.0) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            response = httpx.get(url, timeout=1.0)
            if response.status_code < 500:
                return
        except httpx.HTTPError:
            time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {url}")


def start_process(
    name: str,
    args: list[str],
    env: dict[str, str] | None = None,
    show_logs: bool = False,
) -> ProcessHandle:
    stdout = None if show_logs else subprocess.DEVNULL
    stderr = None if show_logs else subprocess.STDOUT
    process = subprocess.Popen(args, env=env, stdout=stdout, stderr=stderr)
    return ProcessHandle(name=name, process=process)


def terminate(processes: list[ProcessHandle]) -> None:
    for handle in reversed(processes):
        handle.process.terminate()
    for handle in reversed(processes):
        try:
            handle.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            handle.process.kill()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--banto-port", type=int)
    parser.add_argument("--agent-a-port", type=int)
    parser.add_argument("--agent-b-port", type=int)
    parser.add_argument("--show-server-logs", action="store_true")
    args = parser.parse_args()

    banto_port = args.banto_port or free_port()
    agent_a_port = args.agent_a_port or free_port()
    agent_b_port = args.agent_b_port or free_port()
    processes: list[ProcessHandle] = []
    banto = f"http://127.0.0.1:{banto_port}"
    agent_a = f"http://127.0.0.1:{agent_a_port}"
    agent_b = f"http://127.0.0.1:{agent_b_port}"

    try:
        env = os.environ.copy()
        env["BANTO_ALLOW_LOCALHOST"] = "true"
        env["BANTO_ALLOW_OPEN_REGISTER"] = "true"
        processes.append(
            start_process(
                "banto",
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "banto.app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(banto_port),
                ],
                env=env,
                show_logs=args.show_server_logs,
            )
        )
        processes.append(
            start_process(
                "agent-a",
                [
                    sys.executable,
                    "examples/mock_agent.py",
                    "--agent-id",
                    "agent-a",
                    "--port",
                    str(agent_a_port),
                ],
                show_logs=args.show_server_logs,
            )
        )
        processes.append(
            start_process(
                "agent-b",
                [
                    sys.executable,
                    "examples/mock_agent.py",
                    "--agent-id",
                    "agent-b",
                    "--port",
                    str(agent_b_port),
                ],
                show_logs=args.show_server_logs,
            )
        )

        wait_for(f"{banto}/agents")
        wait_for(f"{agent_a}/events")
        wait_for(f"{agent_b}/events")

        client = httpx.Client(timeout=5.0)
        register_headers = {}
        agent_a_token = client.post(
            f"{banto}/register",
            json={
                "agent_id": "agent-a",
                "endpoint": agent_a,
                "heartbeat_interval_sec": 5,
                "down_threshold_sec": 20,
                "subscribe": [],
            },
            headers=register_headers,
        ).json()["token"]
        agent_b_token = client.post(
            f"{banto}/register",
            json={
                "agent_id": "agent-b",
                "endpoint": agent_b,
                "heartbeat_interval_sec": 5,
                "down_threshold_sec": 20,
                "subscribe": [{"type": "demo.notice"}],
            },
            headers=register_headers,
        ).json()["token"]

        client.post(
            f"{banto}/heartbeat",
            headers={"Authorization": f"Bearer {agent_a_token}"},
            json={"agent_id": "agent-a", "status": {"alive": True, "load": "idle", "accepting": True}},
        ).raise_for_status()
        client.post(
            f"{banto}/heartbeat",
            headers={"Authorization": f"Bearer {agent_b_token}"},
            json={"agent_id": "agent-b", "status": {"alive": True, "load": "normal", "accepting": True}},
        ).raise_for_status()

        event_response = client.post(
            f"{banto}/events",
            headers={"Authorization": f"Bearer {agent_a_token}"},
            json={
                "event_id": "demo-1",
                "source": "agent-a",
                "type": "demo.notice",
                "payload": {"message": "hello"},
            },
        )
        event_response.raise_for_status()

        context_response = client.post(
            f"{banto}/context",
            json={"query": "ping", "scope": ["agent-a", "agent-b"], "format": "raw"},
        )
        context_response.raise_for_status()

        print("event:", event_response.json())
        print("context:", context_response.json())
    finally:
        terminate(processes)


if __name__ == "__main__":
    main()
