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
