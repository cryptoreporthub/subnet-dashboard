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
    assert peer["note"] == "worker_http_unreachable"


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


def test_ops_live_split_v2_uses_http_peer(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    remote = {"worker_peer": {"alive": True, "heartbeat": {"ts": "2026-07-28T16:00:00Z"}}}
    with patch("internal.worker_proxy.fetch_worker_json_sync", return_value=remote):
        from internal.ops.readiness import build_liveness_report

        report = build_liveness_report()
    assert report["worker_peer"]["alive"] is True
    assert report["worker_peer"]["source"] == "http"
