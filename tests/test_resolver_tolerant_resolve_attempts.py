"""Malformed ledger values must neither abort the cycle nor pin a row forever (MC M1/M3/M4/T1, #1515)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from internal.council import resolver


@pytest.fixture
def isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(tmp_path / "predictions.json"))
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", str(tmp_path / "price_cache.json"))
    monkeypatch.setattr(resolver, "fetch_prices", lambda _s: {7: 2.0})
    monkeypatch.setattr(
        resolver,
        "regrade_expired_predictions",
        lambda **kw: {"regraded": 0, "ledger_mutated": False},
    )
    monkeypatch.setattr(resolver, "_restore_recently_expired_predictions", lambda *a, **k: [])
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda _uid: False)
    return tmp_path / "predictions.json"


def _bad_row_first_ledger(bad_attempts, **bad_row_updates):
    """Bad row first, then an expired control and a live-gradeable control."""
    now = datetime.now(timezone.utc)
    long_past = (now - timedelta(hours=200)).isoformat().replace("+00:00", "Z")
    slightly_past = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")

    def base(netuid, resolve_at, **extra):
        row = {
            "id": f"row-{netuid}",
            "netuid": netuid,
            "direction": "up",
            "predicted_pct": 5.0,
            "horizon_hours": 1,
            "horizon_type": "hour",
            "reference_price": 1.0,
            "created_at": long_past,
            "resolve_at": resolve_at,
            "status": "pending",
        }
        row.update(extra)
        return row

    bad_row = base(9, long_past, resolve_attempts=bad_attempts)
    bad_row.update(bad_row_updates)
    return [
        bad_row,
        base(8, long_past, resolve_attempts=resolver._PRICE_RETRY_CAP),
        base(7, slightly_past, horizon_hours=24, resolve_attempts=0),
    ]


def _run_cycle(path):
    return resolver.resolve_due_predictions(subnets=[{"netuid": 7, "price": 1.0}])


def _saved_rows(path):
    saved = json.loads(path.read_text(encoding="utf-8"))
    resolved = {row["id"]: row for row in saved["resolved"]}
    pending = [row["id"] for row in saved["predictions"]]
    return saved, resolved, pending


@pytest.mark.parametrize("bad_attempts", ["abc", "1.5", float("nan"), float("inf")])
def test_bad_resolve_attempts_row_cannot_abort_the_cycle(isolated_ledger, bad_attempts):
    path = isolated_ledger
    rows = _bad_row_first_ledger(bad_attempts)
    path.write_text(json.dumps({"predictions": rows, "resolved": [], "stats": {}}), encoding="utf-8")

    out = _run_cycle(path)

    saved, resolved, pending_ids = _saved_rows(path)
    # The cycle ran to completion: both control rows were processed and saved.
    assert resolved["row-8"]["status"] == "expired"
    assert resolved["row-7"]["status"] == "resolved"
    assert resolved["row-7"]["correct"] is True
    # The bad row itself was still handled (site 2 counted a miss) instead of
    # aborting the run, and it stays pending rather than silently vanishing.
    # Literal expectations (T1): "abc"/NaN/inf parse to 0 so the first miss
    # writes 1; "1.5" parses to 1 so the first miss writes 2.
    assert pending_ids == ["row-9"]
    assert saved["predictions"][0]["resolve_attempts"] == (2 if bad_attempts == "1.5" else 1)
    assert any(entry["id"] == "row-8" for entry in out["expired_now"])


@pytest.mark.parametrize("bad_value,expected", [
    ("abc", 0),
    ("1.5", 1),
    (float("nan"), 0),
    (float("inf"), 0),
    (None, 0),
    ("", 0),
    (True, 1),
    (False, 0),
    (3, 3),
    (-1, 0),
    ("-5", 0),
    (-10**18, 0),
])
def test_parse_resolve_attempts_literal_expectations(bad_value, expected):
    """Pin the helper literally so mutants like 'drop the float fallback' die (T1, M4)."""
    assert resolver._parse_resolve_attempts(bad_value) == expected


@pytest.mark.parametrize("bad_attempts", [-10**18, "-5"])
def test_negative_attempts_row_still_expires_within_the_cap(isolated_ledger, bad_attempts):
    """A negative attempts value must not buy unlimited retries (M4)."""
    path = isolated_ledger
    rows = _bad_row_first_ledger(bad_attempts)
    path.write_text(json.dumps({"predictions": rows, "resolved": [], "stats": {}}), encoding="utf-8")

    for _ in range(resolver._PRICE_RETRY_CAP + 3):
        _run_cycle(path)

    _, resolved, pending_ids = _saved_rows(path)
    assert "row-9" not in pending_ids
    assert resolved["row-9"]["status"] == "expired"
    # The control rows still ran their normal lifecycle.
    assert resolved["row-8"]["status"] == "expired"
    assert resolved["row-7"]["status"] == "resolved"


def test_huge_int_horizon_row_cannot_abort_the_cycle(isolated_ledger):
    """A JSON int too large for float() must not abort the cycle (M3)."""
    path = isolated_ledger
    rows = _bad_row_first_ledger(resolver._PRICE_RETRY_CAP, horizon_hours=10**400)
    path.write_text(json.dumps({"predictions": rows, "resolved": [], "stats": {}}), encoding="utf-8")

    out = _run_cycle(path)

    _, resolved, pending_ids = _saved_rows(path)
    assert resolved["row-8"]["status"] == "expired"
    assert resolved["row-7"]["status"] == "resolved"
    assert "row-9" not in pending_ids
    assert resolved["row-9"]["status"] == "expired"
    assert any(entry["id"] == "row-8" for entry in out["expired_now"])