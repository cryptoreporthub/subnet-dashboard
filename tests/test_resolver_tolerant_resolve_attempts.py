"""A malformed ``resolve_attempts`` on one ledger row must not abort the cycle (MC M1, #1515)."""

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


def _bad_row_first_ledger(bad_attempts):
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

    return [
        base(9, long_past, resolve_attempts=bad_attempts),
        base(8, long_past, resolve_attempts=resolver._PRICE_RETRY_CAP),
        base(7, slightly_past, horizon_hours=24, resolve_attempts=0),
    ]


@pytest.mark.parametrize("bad_attempts", ["abc", "1.5", float("nan"), float("inf")])
def test_bad_resolve_attempts_row_cannot_abort_the_cycle(isolated_ledger, bad_attempts):
    path = isolated_ledger
    rows = _bad_row_first_ledger(bad_attempts)
    path.write_text(json.dumps({"predictions": rows, "resolved": [], "stats": {}}), encoding="utf-8")

    out = resolver.resolve_due_predictions(subnets=[{"netuid": 7, "price": 1.0}])

    saved = json.loads(path.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in saved["resolved"]}
    # The cycle ran to completion: both control rows were processed and saved.
    assert by_id["row-8"]["status"] == "expired"
    assert by_id["row-7"]["status"] == "resolved"
    assert by_id["row-7"]["correct"] is True
    # The bad row itself was still handled (site 2 counted a miss) instead of
    # aborting the run, and it stays pending rather than silently vanishing.
    pending_ids = [row["id"] for row in saved["predictions"]]
    assert pending_ids == ["row-9"]
    bad_row = saved["predictions"][0]
    assert bad_row["resolve_attempts"] == resolver._parse_resolve_attempts(bad_attempts) + 1
    assert any(entry["id"] == "row-8" for entry in out["expired_now"])