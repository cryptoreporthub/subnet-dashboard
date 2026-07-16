"""RF-3 — regrade_expired must survive resolve_due_predictions final save."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import internal.council.resolver as resolver
import internal.council.weights as weights


@pytest.fixture(autouse=True)
def isolate_data_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(tmp_path / "predictions.json"))
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", str(tmp_path / "price_cache.json"))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(tmp_path / "soul_map.json"))


@pytest.fixture
def nudge_spy(monkeypatch):
    calls = []

    def _fake_nudge(correct, expert):
        calls.append((correct, expert))

    monkeypatch.setattr(resolver, "_nudge_weights", _fake_nudge)
    return calls


def _write_predictions(data):
    with open(resolver.PREDICTIONS_PATH, "w") as f:
        json.dump(data, f)


def test_resolve_due_preserves_regraded_expired(nudge_spy):
    """Regrade on disk must not be clobbered by stale in-memory resolved list."""
    now = datetime.now(timezone.utc)
    resolve_at = (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    expired = {
        "id": "pred_regrade_1",
        "netuid": 1,
        "name": "Root",
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 100.0,
        "resolve_at": resolve_at,
        "created_at": resolve_at,
        "status": "expired",
        "outcome": "expired",
        "horizon_type": "hour",
    }
    _write_predictions({"predictions": [], "resolved": [expired], "stats": {}})

    def _fake_regrade(**_kwargs):
        graded = dict(expired)
        graded.update(
            {
                "status": "resolved",
                "outcome": "hit",
                "correct": True,
                "actual_pct": 3.0,
                "resolved_price": 103.0,
                "resolved_at": resolve_at,
            }
        )
        _write_predictions(
            {
                "predictions": [],
                "resolved": [graded],
                "stats": resolver._compute_stats({"resolved": [graded], "predictions": []}),
            }
        )
        return {"attempted": 1, "regraded": 1, "stats": {"expired": 0, "correct": 1, "wrong": 0}}

    import internal.council.resolver as res_mod

    orig = res_mod.regrade_expired_predictions
    res_mod.regrade_expired_predictions = _fake_regrade
    try:
        resolver.resolve_due_predictions(subnets=[])
    finally:
        res_mod.regrade_expired_predictions = orig

    with open(resolver.PREDICTIONS_PATH) as f:
        saved = json.load(f)
    assert saved["stats"]["expired"] == 0
    assert saved["resolved"][0]["outcome"] == "hit"
    assert saved["resolved"][0]["correct"] is True
