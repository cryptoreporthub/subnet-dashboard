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


def _assert_rotating_xff_shares_one_bucket(base_url: str) -> None:
    """2/min limit: two distinct X-Forwarded-For hops must share one bucket (3rd → 429)."""
    client = httpx.Client(base_url=base_url, timeout=10.0)
    assert client.get("/api/registry", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 200
    assert client.get("/api/registry", headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 200
    assert client.get("/api/registry", headers={"X-Forwarded-For": "198.51.100.99"}).status_code == 429


@pytest.fixture(scope="module")
def uvicorn_off_fly_server(request):
    """Indirect param: False = pinned launch (--no-proxy-headers); True = pre-fix trust path."""
    use_pre_fix_proxy_launch = bool(getattr(request, "param", False))
    assert UVICORN_WEB_KWARGS["proxy_headers"] is False

    env = {
        **os.environ,
        "DISABLE_BACKGROUND_SCANS": "1",
        "ENABLE_RATE_LIMIT": "1",
        "RATE_LIMIT_DEFAULT": "2/minute",
    }
    env.pop("FLY_APP_NAME", None)
    port = _free_port()
    fwd = UVICORN_WEB_KWARGS["forwarded_allow_ips"]
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
        f"--forwarded-allow-ips={fwd}",
    ]
    if use_pre_fix_proxy_launch:
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


@pytest.mark.parametrize("uvicorn_off_fly_server", [False], indirect=True)
def test_off_fly_uvicorn_xff_does_not_split_limit_buckets(uvicorn_off_fly_server):
    _assert_rotating_xff_shares_one_bucket(uvicorn_off_fly_server)


@pytest.mark.parametrize("uvicorn_off_fly_server", [True], indirect=True)
@pytest.mark.xfail(
    strict=True,
    reason="Pre-fix launcher (--proxy-headers + loopback forwarded_allow_ips) splits XFF buckets",
)
def test_off_fly_uvicorn_xff_pre_fix_proxy_launch_splits_buckets(uvicorn_off_fly_server):
    """RED guard: same 429 assert as green test; fails on shared-bucket line until launch is pinned."""
    _assert_rotating_xff_shares_one_bucket(uvicorn_off_fly_server)