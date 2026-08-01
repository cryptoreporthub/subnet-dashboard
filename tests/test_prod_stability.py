"""Production stability guards — pump scan lock + cache-only sparklines."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

from internal.analytics.root_context import spark_closes_cached_only
from internal.pump.state import load_state, scan_all_subnets


from fastapi.testclient import TestClient

from server import app


def test_get_index_returns_instant_shell_without_blocking_on_prime(monkeypatch):
    import server as srv

    monkeypatch.setattr(srv, "_EMERGENCY_HOME_HTML", "")
    monkeypatch.setattr(srv, "_HOMEPAGE_HTML_CACHE", {"at": 0.0, "html": None})

    def _hang_prime():
        time.sleep(30)

    monkeypatch.setattr(srv, "_prime_emergency_home_html", _hang_prime)
    with TestClient(app) as client:
        t0 = time.monotonic()
        r = client.get("/")
        elapsed = time.monotonic() - t0
    assert r.status_code == 200
    assert elapsed < 2.0
    assert "Loading council" in r.text
    assert b"background:#0a0a0f" in r.content or "#04060e" in r.text


def test_spark_closes_cached_only_skips_lazy_fill(monkeypatch):
    with patch("internal.council.state_vector._lazy_fill_price_candles") as lazy:
        spark_closes_cached_only({"netuid": 29})
        lazy.assert_not_called()


def test_scan_all_subnets_fetch_outside_state_lock(tmp_path, monkeypatch):
    """load_state must not block for the full signal fetch (Fly wedge fix)."""
    state_path = str(tmp_path / "pump_ladder.json")
    monkeypatch.setenv("PUMP_LADDER_STATE_PATH", state_path)
    from internal.pump import constants

    monkeypatch.setattr(constants, "STATE_PATH", state_path)

    fetch_started = threading.Event()
    release_fetch = threading.Event()

    def slow_fetch():
        fetch_started.set()
        release_fetch.wait(timeout=2.0)
        return [
            {
                "netuid": 29,
                "name": "Coldint",
                "buy_ratio": 0.6,
                "volume_intensity": 0.4,
                "price_change_24h": 1.0,
                "price_change_1h": 0.5,
            }
        ]

    with patch("internal.pump.state.fetch_all_subnet_signals", side_effect=slow_fetch):
        with patch("internal.pump.state.apply_phase_transitions", return_value={}):
            t = threading.Thread(target=scan_all_subnets, daemon=True)
            t.start()
            assert fetch_started.wait(timeout=2.0)
            t0 = time.monotonic()
            load_state()
            assert time.monotonic() - t0 < 0.25
            release_fetch.set()
            t.join(timeout=3.0)
            assert not t.is_alive()


def test_message_intel_list_route_does_not_block_health():
    """GET /api/message-intel (the most frequently polled endpoint in the app)
    called engine.list_messages() -> build_telegram_proof_band() directly,
    which runs a SQLite query that can block on the DB's write lock while the
    Telegram listener ingests. A live py-spy dump caught this exact route
    holding the event loop in production, causing intermittent /health
    flapping under real traffic. Must dispatch off-thread."""
    started = threading.Event()
    release = threading.Event()

    def slow_list_messages(**kwargs):
        started.set()
        release.wait(timeout=2.0)
        return {"status": "success", "count": 0, "messages": []}

    with patch("internal.message_intel.engine.list_messages", side_effect=slow_list_messages):
        with TestClient(app) as client:
            result = {}

            def _call():
                result["resp"] = client.get("/api/message-intel")

            t = threading.Thread(target=_call, daemon=True)
            t.start()
            assert started.wait(timeout=2.0)

            t0 = time.monotonic()
            health = client.get("/health")
            elapsed = time.monotonic() - t0

            release.set()
            t.join(timeout=3.0)

    assert health.status_code == 200
    assert elapsed < 1.0
    assert result["resp"].status_code == 200


def test_cockpit_sections_route_does_not_block_health():
    """GET /api/cockpit/sections and the SSE stream's periodic sections event
    both called get_cockpit_sections() -> select_hourly_pick() directly. A live
    py-spy dump caught this holding the event loop via /api/cockpit/stream in
    production. Must dispatch off-thread so /health stays responsive."""
    started = threading.Event()
    release = threading.Event()

    def slow_get_cockpit_sections():
        started.set()
        release.wait(timeout=2.0)
        return {"status": "success", "sections": []}

    with patch("internal.cockpit.routes.get_cockpit_sections", side_effect=slow_get_cockpit_sections):
        with TestClient(app) as client:
            result = {}

            def _call():
                result["resp"] = client.get("/api/cockpit/sections")

            t = threading.Thread(target=_call, daemon=True)
            t.start()
            assert started.wait(timeout=2.0)

            t0 = time.monotonic()
            health = client.get("/health")
            elapsed = time.monotonic() - t0

            release.set()
            t.join(timeout=3.0)

    assert health.status_code == 200
    assert elapsed < 1.0
    assert result["resp"].status_code == 200


def test_mindmap_learning_routes_do_not_block_health(monkeypatch):
    """/api/mindmap/summary, /api/mindmap/state, and /api/mindmap/story-path
    each called a full subnet-universe scoring function directly in an async
    route (get_or_create_today_pick / build_mindmap_state). A live py-spy dump
    caught /api/mindmap/story-path holding the event loop in production. All
    three must dispatch through the thread pool so /health stays responsive."""
    import internal.learning.routes as learning_routes

    def slow_build_mindmap_state():
        release.wait(timeout=2.0)
        return {"status": "success", "trail": [], "summaries": {}}

    def slow_get_or_create_today_pick(subnets, market_context):
        release.wait(timeout=2.0)
        return {}

    for path, patches in {
        "/api/mindmap/state": [
            ("internal.learning.mindmap_aggregator.build_mindmap_state", slow_build_mindmap_state),
        ],
        "/api/mindmap/story-path": [
            (
                "internal.council.daily_pick_engine.get_or_create_today_pick",
                slow_get_or_create_today_pick,
            ),
        ],
    }.items():
        release = threading.Event()
        ctx_managers = [patch(target, side_effect=fn) for target, fn in patches]
        for cm in ctx_managers:
            cm.__enter__()
        try:
            with TestClient(app) as client:
                result = {}

                def _call():
                    result["resp"] = client.get(path)

                t = threading.Thread(target=_call, daemon=True)
                t.start()
                time.sleep(0.2)

                t0 = time.monotonic()
                health = client.get("/health")
                elapsed = time.monotonic() - t0

                release.set()
                t.join(timeout=3.0)
        finally:
            for cm in ctx_managers:
                cm.__exit__(None, None, None)

        assert health.status_code == 200
        assert elapsed < 1.0, f"{path} blocked /health for {elapsed}s"
        assert result["resp"].status_code == 200


def test_mindmap_graph_route_does_not_block_health():
    """GET /api/mindmap/graph has repeatedly grown expensive synchronous work
    (TaoStats calls, a soul_map.json rewrite, hourly-pick technical scoring)
    that wedged the whole event loop when run inline in the async route. The
    route must dispatch through the thread pool so /health stays responsive
    even while a slow mindmap build is in flight."""
    started = threading.Event()
    release = threading.Event()

    def slow_get_mindmap_graph(focus_netuid=None):
        started.set()
        release.wait(timeout=2.0)
        return {"status": "success", "nodes": [], "edges": []}

    with patch("internal.mindmap.routes.get_mindmap_graph", side_effect=slow_get_mindmap_graph):
        with TestClient(app) as client:
            result: dict = {}

            def _call_mindmap():
                result["resp"] = client.get("/api/mindmap/graph")

            t = threading.Thread(target=_call_mindmap, daemon=True)
            t.start()
            assert started.wait(timeout=2.0)

            t0 = time.monotonic()
            health = client.get("/health")
            elapsed = time.monotonic() - t0

            release.set()
            t.join(timeout=3.0)

    assert health.status_code == 200
    assert elapsed < 1.0
    assert result["resp"].status_code == 200


def test_mindmap_graph_route_dedupes_concurrent_slow_builds(monkeypatch):
    """A slow build_mindmap_state() (repeatedly reloads council weight files
    per subnet scored, easily minutes) must not fan out into N independent
    computations under repeated polling - that exhausted the whole thread
    pool in production and took down "/" and /api/pump-alerts even though
    /health stayed up. Concurrent requests for the same focus must share one
    in-flight build."""
    import internal.mindmap.routes as routes

    monkeypatch.setattr(routes, "_cache", {})
    monkeypatch.setattr(routes, "_build_locks", {})

    call_count = {"n": 0}
    started = threading.Event()
    release = threading.Event()

    def slow_get_mindmap_graph(focus_netuid=None):
        call_count["n"] += 1
        started.set()
        release.wait(timeout=2.0)
        return {"status": "success", "nodes": [], "edges": []}

    with patch("internal.mindmap.routes.get_mindmap_graph", side_effect=slow_get_mindmap_graph):
        with TestClient(app) as client:
            results = []

            def _call():
                results.append(client.get("/api/mindmap/graph"))

            threads = [threading.Thread(target=_call, daemon=True) for _ in range(3)]
            for t in threads:
                t.start()
            assert started.wait(timeout=2.0)
            release.set()
            for t in threads:
                t.join(timeout=3.0)

    assert all(r.status_code == 200 for r in results)
    assert call_count["n"] == 1


def test_scan_all_subnets_soul_map_write_outside_state_lock(tmp_path, monkeypatch):
    """load_state must not block on apply_phase_transitions' soul_map.json
    rewrite (Fly wedge: mindmap graph -> hourly pick -> pump overlay all call
    load_state() and got stuck behind a slow, unrelated Soul-Map write)."""
    state_path = str(tmp_path / "pump_ladder.json")
    monkeypatch.setenv("PUMP_LADDER_STATE_PATH", state_path)
    from internal.pump import constants

    monkeypatch.setattr(constants, "STATE_PATH", state_path)

    apply_started = threading.Event()
    release_apply = threading.Event()

    def slow_apply_phase_transitions(transitions, ladder_state):
        apply_started.set()
        release_apply.wait(timeout=2.0)
        return {"disposition_updates": 0, "trail_events": 0}

    signal_row = {
        "netuid": 29,
        "name": "Coldint",
        "buy_ratio": 0.6,
        "volume_intensity": 0.4,
        "price_change_24h": 5.0,
        "price_change_1h": 2.0,
    }

    with patch("internal.pump.state.fetch_all_subnet_signals", return_value=[signal_row]):
        with patch(
            "internal.pump.state.apply_phase_transitions",
            side_effect=slow_apply_phase_transitions,
        ):
            t = threading.Thread(target=scan_all_subnets, daemon=True)
            t.start()
            assert apply_started.wait(timeout=2.0)
            t0 = time.monotonic()
            load_state()
            assert time.monotonic() - t0 < 0.25
            release_apply.set()
            t.join(timeout=3.0)
            assert not t.is_alive()
