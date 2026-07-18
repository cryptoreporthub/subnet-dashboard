"""Resolver backfills subnet_snapshot at grade time when ledger row is thin."""

from __future__ import annotations

import json

import internal.council.resolver as resolver
import internal.council.weights as weights
from internal.learning import predictions_store


def test_ensure_subnet_snapshot_backfills_from_feed(monkeypatch):
    subnet = {
        "netuid": 42,
        "name": "Testnet",
        "price": 12.5,
        "price_change_24h": 2.5,
        "price_change_7d": 4.0,
        "apy": 0.15,
        "emission": 1.0,
        "volume": 50000,
    }
    monkeypatch.setattr(
        resolver,
        "_lookup_subnet_row",
        lambda netuid: subnet if netuid == 42 else None,
    )

    pred = {"netuid": 42, "reference_price": 12.0}
    assert resolver._ensure_subnet_snapshot(pred, subnet_row=subnet) is True
    snap = pred["subnet_snapshot"]
    assert snap.get("price") == 12.5
    assert snap.get("price_change_24h") == 2.5
    assert pred.get("subnet_snapshot_source") == "resolve_backfill"


def test_ensure_subnet_snapshot_skips_when_complete():
    pred = {
        "netuid": 42,
        "subnet_snapshot": {
            "price": 10.0,
            "price_change_24h": 1.0,
            "price_change_7d": 2.0,
        },
    }
    assert resolver._ensure_subnet_snapshot(pred, subnet_row={"netuid": 42, "price": 99}) is False


def test_resolve_prediction_backfills_snapshot(monkeypatch, tmp_path):
    pred_path = str(tmp_path / "predictions.json")
    soul_path = str(tmp_path / "soul_map.json")
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", soul_path)
    soul_path_obj = tmp_path / "soul_map.json"
    soul_path_obj.write_text(
        json.dumps({"adversarial_state": {"council_weights": {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}}}),
        encoding="utf-8",
    )

    subnet = {
        "netuid": 7,
        "name": "Gamma",
        "price": 20.0,
        "price_change_24h": -1.5,
        "price_change_7d": 3.0,
        "apy": 0.2,
        "emission": 1.0,
    }
    monkeypatch.setattr(
        resolver,
        "_lookup_subnet_row",
        lambda netuid: subnet if netuid == 7 else None,
    )

    pred = {
        "id": "snap-test",
        "netuid": 7,
        "name": "Gamma",
        "direction": "up",
        "predicted_pct": 3.0,
        "reference_price": 19.0,
        "signal_source": "HOT",
    }
    resolved = resolver.resolve_prediction(pred, current_price=20.5)
    assert resolved["subnet_snapshot"]["price_change_24h"] == -1.5
    assert resolved.get("subnet_snapshot_source") == "resolve_backfill"
