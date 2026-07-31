"""Cross-machine worker peer heartbeat (split v2)."""

from __future__ import annotations

from unittest.mock import patch


def test_worker_peer_split_v2_web_http_alive(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    remote = {
        "worker_peer": {
            "alive": True,
            "heartbeat": {"ts": "2026-07-28T16:00:00Z"},
            "peer": "dedicated_worker",
            "source": "file",
        }
    }
    with patch("internal.worker_proxy.fetch_worker_json_sync", return_value=remote):
        from internal.worker_peer import get_worker_peer

        peer = get_worker_peer()
    assert peer["alive"] is True
    assert peer["peer"] == "dedicated_worker"
    assert peer["source"] == "http"


def test_worker_peer_split_v2_web_http_unreachable(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")

    def _boom(*_a, **_k):
        raise OSError("no route to worker")

    with patch("internal.worker_proxy.fetch_worker_json_sync", side_effect=_boom):
        from internal.worker_peer import get_worker_peer

        peer = get_worker_peer()
    assert peer["alive"] is False
    assert peer["note"].startswith("worker_http_unreachable")


def test_worker_peer_dedicated_worker_reads_file(monkeypatch, tmp_path):
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(tmp_path / ".worker_heartbeat"))
    from internal.worker_heartbeat import touch_heartbeat
    from internal.worker_peer import get_worker_peer

    touch_heartbeat()
    peer = get_worker_peer()
    assert peer["alive"] is True
    assert peer["peer"] == "dedicated_worker"
    assert peer["source"] == "file"


def _mock_async_client_factory(calls, handler):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return handler(calls, url)

    return _Client


def test_fetch_worker_json_sync_retries_second_base(monkeypatch):
    monkeypatch.setenv("WORKER_INTERNAL_URL", "http://bad.internal:8080")
    monkeypatch.setenv("FLY_APP_NAME", "subnet-dashboard")
    monkeypatch.delenv("FLY_REGION", raising=False)
    import internal.worker_proxy as wp

    wp._LAST_GOOD_BASE = None
    calls = []

    class _Resp:
        status_code = 200
        request = None

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def _handler(calls, url):
        calls.append(url)
        if "bad.internal" in url:
            bad = _Resp()
            bad.status_code = 503
            return bad
        return _Resp()

    monkeypatch.setattr("httpx.AsyncClient", _mock_async_client_factory(calls, _handler))
    from internal.worker_proxy import fetch_worker_json_sync

    out = fetch_worker_json_sync("/api/ops/worker-peer", timeout=2)
    assert out.get("ok") is True
    assert len(calls) >= 2
    assert "bad.internal" in calls[0]


def test_worker_peer_route_404_on_web(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    from fastapi.testclient import TestClient

    from server import app

    with TestClient(app) as client:
        resp = client.get("/api/ops/worker-peer")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "worker_peer_only_on_worker_machine"


def test_fetch_worker_json_sync_skips_web_misroute(monkeypatch):
    monkeypatch.setenv("WORKER_INTERNAL_URL", "http://bad.internal:8080")
    monkeypatch.setenv("FLY_APP_NAME", "subnet-dashboard")
    monkeypatch.delenv("FLY_REGION", raising=False)
    import internal.worker_proxy as wp

    wp._LAST_GOOD_BASE = None
    calls = []

    class _Resp:
        status_code = 200
        request = None

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "worker_peer": {
                    "alive": False,
                    "source": "http",
                    "note": "worker_http_unreachable",
                }
            }

    def _handler(calls, url):
        calls.append(url)
        if "bad.internal" in url:
            return _Resp()
        good = _Resp()
        good.json = lambda: {
            "worker_peer": {"alive": True, "source": "file", "peer": "dedicated_worker"}
        }
        return good

    monkeypatch.setattr("httpx.AsyncClient", _mock_async_client_factory(calls, _handler))
    from internal.worker_proxy import fetch_worker_json_sync

    out = fetch_worker_json_sync("/api/ops/live", timeout=2)
    assert out["worker_peer"]["alive"] is True
    assert "bad.internal" in calls[0]
    assert any("worker.process" in c for c in calls)


def test_fetch_worker_json_sync_from_async_context(monkeypatch):
    """Peer probe runs inside FastAPI async routes — must not call asyncio.run inline."""
    monkeypatch.setenv("FLY_APP_NAME", "subnet-dashboard")
    import internal.worker_proxy as wp

    wp._LAST_GOOD_BASE = None
    calls = []

    class _Resp:
        status_code = 200
        request = None

        def raise_for_status(self):
            return None

        def json(self):
            return {"worker_peer": {"alive": True, "source": "file", "peer": "dedicated_worker"}}

    async def _handler(calls, url):
        calls.append(url)
        return _Resp()

    async def _mock_fetch(path, query="", timeout=12, fast_path=False):
        return await _handler(calls, path)

    monkeypatch.setattr(wp, "_fetch_worker_http", _mock_fetch)

    async def _route():
        from internal.worker_proxy import fetch_worker_json_sync

        return fetch_worker_json_sync("/api/ops/live", timeout=2)

    import asyncio

    out = asyncio.run(_route())
    assert out["worker_peer"]["alive"] is True


def test_ops_live_split_v2_uses_http_peer(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    remote = {
        "worker_peer": {
            "alive": True,
            "heartbeat": {"ts": "2026-07-28T16:00:00Z"},
            "source": "file",
        }
    }
    with patch("internal.worker_proxy.fetch_worker_json_sync", return_value=remote):
        from internal.ops.readiness import build_liveness_report

        report = build_liveness_report()
    assert report["worker_peer"]["alive"] is True
    assert report["worker_peer"]["source"] == "http"


def test_build_liveness_report_fast_skips_worker_http(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")

    def _boom(*_a, **_k):
        raise AssertionError("worker HTTP probe should not run on fast liveness")

    with patch("internal.worker_proxy.fetch_worker_json_sync", _boom):
        from internal.ops.readiness import build_liveness_report

        report = build_liveness_report(probe_worker=False)
    assert report["worker_peer"]["source"] == "deferred"
