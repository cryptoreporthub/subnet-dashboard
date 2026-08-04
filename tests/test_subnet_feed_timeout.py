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
    """Missing stored pick must not call subnet hydrate or pick engine."""
    from fastapi.testclient import TestClient

    import server as srv

    monkeypatch.setattr("internal.council.daily_pick_engine._find_today", lambda _rows: None)

    def _boom(*_args, **_kwargs):
        raise AssertionError("hydrate must not run when no stored pick")

    monkeypatch.setattr(srv, "_get_subnets_hydrate", _boom)

    client = TestClient(srv.app)
    resp = client.get("/api/daily-pick")

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "pending"
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


def test_peek_shortlist_returns_cached_without_rebuild():
    from internal.council.shortlist_cache import cached_shortlist, peek_shortlist, clear_shortlist_cache

    clear_shortlist_cache()
    payload = {"date": "2099-02-02", "action": "HOLD", "candidate": {"subnet": {"netuid": 4}}}
    calls = {"n": 0}

    def _builder():
        calls["n"] += 1
        return [{"netuid": 4, "name": "Cached"}]

    assert cached_shortlist(payload, _builder) == [{"netuid": 4, "name": "Cached"}]
    assert calls["n"] == 1
    assert peek_shortlist(payload) == [{"netuid": 4, "name": "Cached"}]
    clear_shortlist_cache()


def test_top_pick_day_does_not_invoke_pick_engine(monkeypatch):
    from fastapi.testclient import TestClient

    import server as srv

    def _boom(*_a, **_k):
        raise AssertionError("get_or_create_today_pick must not run on API read")

    monkeypatch.setattr("internal.council.daily_pick_engine.get_or_create_today_pick", _boom)
    monkeypatch.setattr(
        "internal.council.daily_pick_engine._find_today",
        lambda _rows: {"pick": {"subnet": {"netuid": 9, "name": "Gamma"}}},
    )

    client = TestClient(srv.app)
    resp = client.get("/api/top-pick/day")
    assert resp.status_code == 200
    picks = resp.json()["picks"]
    assert picks and picks[0]["subnet"]["netuid"] == 9
