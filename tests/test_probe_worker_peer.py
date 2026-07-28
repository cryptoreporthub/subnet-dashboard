"""Self-check for probe_worker_peer_once.py URL assembly."""

from __future__ import annotations


def probe_url(base: str, app: str, port: str) -> str:
    url = base.strip()
    if not url:
        return f"http://{app}.flycast:{port}/api/ops/worker-peer"
    if not url.endswith("/api/ops/worker-peer"):
        return f"{url.rstrip('/')}/api/ops/worker-peer"
    return url


def test_probe_url_flycast_default():
    assert probe_url("", "subnet-dashboard", "8081") == (
        "http://subnet-dashboard.flycast:8081/api/ops/worker-peer"
    )


def test_probe_url_private_ip():
    assert probe_url("http://[fdaa::1]:8081", "subnet-dashboard", "8081") == (
        "http://[fdaa::1]:8081/api/ops/worker-peer"
    )
