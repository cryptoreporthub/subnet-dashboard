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

    stored = {
        "date": "2099-01-01",
        "action": "HOLD",
        "candidate": {"subnet": {"netuid": 78}, "final_confidence": 0.3},
    }

    def _boom(*_args, **_kwargs):
        raise AssertionError("subnet hydrate must not run for lite daily-pick read")

    monkeypatch.setattr(srv, "_get_subnets_hydrate", _boom)
    monkeypatch.setattr(srv, "_get_subnets_with_source", _boom)
    monkeypatch.setattr(srv, "_enrich_daily_pick_payload", _boom)
    monkeypatch.setattr("internal.council.daily_pick_engine._find_today", lambda _rows: stored)

    client = TestClient(srv.app)
    resp = client.get("/api/daily-pick")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("date")
    assert "action" in body
    assert body.get("brief") or body.get("pick") or body.get("candidate")


def test_daily_pick_times_out_without_wedging_event_loop(monkeypatch):
    """Sync pick work must not block the ASGI loop past PICK_HANDLER_TIMEOUT."""
    import time

    from fastapi.testclient import TestClient

    import server as srv

    monkeypatch.setattr("internal.council.daily_pick_engine._find_today", lambda _rows: None)
    monkeypatch.setattr(srv, "PICK_HANDLER_TIMEOUT", 0.2)

    def _slow_hydrate():
        time.sleep(2.0)
        return [], "snapshot"

    monkeypatch.setattr(srv, "_get_subnets_hydrate", _slow_hydrate)

    client = TestClient(srv.app)
    t0 = time.time()
    resp = client.get("/api/daily-pick")
    elapsed = time.time() - t0

    assert resp.status_code == 200
    assert elapsed < 2.0, f"daily-pick blocked {elapsed:.1f}s"
    body = resp.json()
    assert body.get("action") == "HOLD"


def test_daily_pick_lite_skips_shortlist_scoring():
    """Lite enrich stays fast — weighed-against is deferred to /api/daily-pick/weighed."""
    import time

    import server as srv

    payload = {
        "action": "HOLD",
        "candidate": {
            "subnet": {"netuid": 78, "name": "SN78"},
            "final_confidence": 0.302,
            "audit": {"concerns": ["Thin volume"]},
        },
    }
    t0 = time.time()
    out = srv._enrich_daily_pick_payload_lite(payload)
    elapsed = time.time() - t0
    assert elapsed < 2.0, f"lite enrich took {elapsed:.1f}s"
    assert out.get("shortlist") == []


def test_daily_pick_weighed_endpoint_returns_shortlist(monkeypatch):
    from fastapi.testclient import TestClient

    import server as srv

    stored = {
        "date": "2099-01-01",
        "action": "HOLD",
        "candidate": {"subnet": {"netuid": 78}, "final_confidence": 0.3},
    }
    fake_shortlist = [
        {"netuid": 1, "name": "Alpha", "conviction": 42, "role": "runner-up"},
        {"netuid": 2, "name": "Beta", "conviction": 38, "role": "volume thin"},
    ]

    monkeypatch.setattr("internal.council.daily_pick_engine._find_today", lambda _rows: stored)
    monkeypatch.setattr(srv, "_daily_pick_weighed_shortlist", lambda _payload: fake_shortlist)

    client = TestClient(srv.app)
    resp = client.get("/api/daily-pick/weighed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["shortlist"] == fake_shortlist
