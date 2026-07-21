"""Subnet feed must not re-hang after timeout (hydrate wedge regression)."""

import time

from internal.subnets.feed import load_subnets_source


def test_subnet_feed_timeout_does_not_block(monkeypatch):
    def _hang():
        time.sleep(60)
        return []

    monkeypatch.setattr("internal.subnets.feed._load_subnets_inner", _hang)
    monkeypatch.setattr("internal.subnets.feed.SUBNETS_LOAD_TIMEOUT", 0.5)

    t0 = time.time()
    rows = load_subnets_source()
    elapsed = time.time() - t0

    assert elapsed < 3.0, f"feed timeout blocked {elapsed:.1f}s"
    assert rows, "expected registry fallback rows"


def test_daily_pick_read_path_skips_live_feed(monkeypatch):
    """Hydrate daily-pick must return stored JSON without calling live subnet feed."""
    from fastapi.testclient import TestClient

    import server as srv

    def _boom():
        raise AssertionError("live subnet feed must not run for cached daily pick")

    monkeypatch.setattr(srv, "_get_subnets_with_source", lambda **_: _boom())

    client = TestClient(srv.app)
    resp = client.get("/api/daily-pick")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("date")
    assert "action" in body
