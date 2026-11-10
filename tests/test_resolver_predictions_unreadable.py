"""Resolver must not overwrite predictions.json when the ledger is unreadable."""

from __future__ import annotations

import json

import pytest

from internal.council import resolver
from internal.store.soul_map_io import StateUnreadable


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
