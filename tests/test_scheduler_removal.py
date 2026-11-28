"""Never-booted indicator/adversarial schedulers are gone and nothing fakes their data."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]


def _client():
    from server import app

    return TestClient(app)


def test_removed_indicator_routes_are_404():
    with _client() as c:
        assert c.get("/api/indicators").status_code == 404
        assert c.get("/api/indicators/scheduler").status_code == 404


def test_convergence_source_names_state_vector(monkeypatch):
    import internal.indicators.routes as routes
    import server

    rows = [{"netuid": 7, "name": "SN7", "emission": 1.0}]
    monkeypatch.setattr(server, "_get_subnets_with_source", lambda: (rows, "registry"))
    monkeypatch.setattr(routes, "_get_price_history", lambda n, sn: {"closes": [], "source": "unavailable"})
    monkeypatch.setattr(routes, "_detect_oversold_convergence", lambda ind: {"convergent": False, "count": 0})
    monkeypatch.setattr(routes, "_detect_overbought_convergence", lambda ind: {"convergent": False, "count": 0})

    monkeypatch.setattr(routes, "_compute_technical_indicators", lambda sn: {"degraded": False})
    with _client() as c:
        body = c.get("/api/indicators-convergence").json()
    assert body["data_available"] is True
    assert body["source"] == "state_vector"

    monkeypatch.setattr(routes, "_compute_technical_indicators", lambda sn: {"degraded": True})
    with _client() as c:
        body = c.get("/api/indicators-convergence").json()
    assert body["data_available"] is False
    assert body["source"] == "none"


def test_metrics_refresh_registers_no_adversarial_scheduler(monkeypatch, tmp_path):
    from internal import liveness
    from internal.metrics import refresh_from_state

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delitem(liveness._REGISTRY, "adversarial_scheduler", raising=False)
    refresh_from_state()
    assert "adversarial_scheduler" not in liveness.all_snapshots()


def test_pump_convergence_ignores_stale_indicator_file(monkeypatch, tmp_path):
    """A leftover data/indicator_state.json (e.g. on the Fly volume) must not move pump proneness."""
    from datastore.pump_tracker import PumpTracker

    (tmp_path / "data").mkdir()
    stale = {"per_subnet": {"1": {"rsi": 10.0, "macd_histogram": 1.0, "stochastic_k": 5.0}}}
    (tmp_path / "data" / "indicator_state.json").write_text(json.dumps(stale), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("INDICATOR_STATE_PATH", str(tmp_path / "data" / "indicator_state.json"))
    tracker = PumpTracker(state_path=str(tmp_path / "pump_state.json"))
    assert tracker.compute_signal_convergence(1) == 0.5