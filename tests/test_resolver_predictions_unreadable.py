"""Predictions ledger: fail-closed writes, degraded read-only API."""

from __future__ import annotations

import json

import pytest

from internal.council import resolver
from internal.store.soul_map_io import StateUnreadable


def test_get_resolved_predictions_degrades_unreadable_without_raise(tmp_path, monkeypatch):
    pred = tmp_path / "predictions.json"
    pred.write_text("not-json{{{", encoding="utf-8")
    before = pred.read_bytes()
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(pred))

    out = resolver.get_resolved_predictions()

    assert out["resolved"] == []
    assert isinstance(out.get("stats"), dict)
    assert pred.read_bytes() == before


def test_corrupt_price_cache_degrades_and_resolution_runs(tmp_path, monkeypatch):
    pred = tmp_path / "predictions.json"
    pred.write_text(
        json.dumps(
            {
                "predictions": [],
                "resolved": [],
                "stats": {"correct": 0, "wrong": 0, "pending": 0},
            }
        ),
        encoding="utf-8",
    )
    cache = tmp_path / "price_cache.json"
    cache.write_text("not-json{{{", encoding="utf-8")
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(pred))
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", str(cache))
    monkeypatch.setattr(resolver, "fetch_prices", lambda _subnets=None: {})

    assert resolver._load_json(str(cache), {}) == {}
    result = resolver._resolve_due_predictions(subnets=[])
    assert isinstance(result, dict)
    assert result.get("stats", {}).get("pending") == 0


def test_corrupt_predictions_read_only_stable_across_calls_before_write_refused(
    tmp_path, monkeypatch
):
    """Ditto bar (a): dashboards keep reading; write paths stay fail-closed."""
    pred = tmp_path / "predictions.json"
    pred.write_text("not-json{{{", encoding="utf-8")
    before = pred.read_bytes()
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(pred))

    for _ in range(2):
        out = resolver.get_resolved_predictions()
        assert out["resolved"] == []

    with pytest.raises(StateUnreadable):
        resolver._resolve_due_predictions(subnets=[])

    assert pred.read_bytes() == before
    out2 = resolver.get_resolved_predictions()
    assert out2["resolved"] == []


def test_unreadable_predictions_json_is_not_persisted_as_empty_default(tmp_path, monkeypatch):
    pred = tmp_path / "predictions.json"
    pred.write_text("not-json{{{", encoding="utf-8")
    before = pred.read_bytes()
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(pred))
    monkeypatch.setattr(
        resolver,
        "fetch_prices",
        lambda _subnets=None: {},
    )

    with pytest.raises(StateUnreadable):
        resolver._resolve_due_predictions(subnets=[])

    assert pred.read_bytes() == before
