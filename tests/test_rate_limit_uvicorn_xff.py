"""Off-Fly rate limit keys must not split on client X-Forwarded-For through uvicorn (#1633)."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

from internal.web_uvicorn import UVICORN_WEB_KWARGS


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def uvicorn_off_fly_server():
    env = {**os.environ, "DISABLE_BACKGROUND_SCANS": "1", "ENABLE_RATE_LIMIT": "1", "RATE_LIMIT_DEFAULT": "2/minute"}
    env.pop("FLY_APP_NAME", None)
    port = _free_port()
    kwargs = UVICORN_WEB_KWARGS
    assert kwargs["proxy_headers"] is False
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "server:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
        f"--forwarded-allow-ips={kwargs['forwarded_allow_ips']}",
    ]
    if kwargs.get("proxy_headers"):
        cmd.append("--proxy-headers")
    else:
        cmd.append("--no-proxy-headers")
    proc = subprocess.Popen(
        cmd,
        env=env,
        cwd=os.path.dirname(os.path.dirname(__file__)),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            try:
                if httpx.get(f"{base}/health", timeout=0.5).status_code == 200:
                    break
            except Exception:
                time.sleep(0.15)
        else:
            err = proc.stderr.read().decode() if proc.stderr else ""
            pytest.fail(f"uvicorn did not become ready: {err[:500]}")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_off_fly_uvicorn_xff_does_not_split_limit_buckets(uvicorn_off_fly_server):
    client = httpx.Client(base_url=uvicorn_off_fly_server, timeout=10.0)
    assert client.get("/api/registry", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 200
    assert client.get("/api/registry", headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 200
    assert client.get("/api/registry", headers={"X-Forwarded-For": "198.51.100.99"}).status_code == 429