"""Task-95: Cache-key format consistency across all subnet feeds.

Verifies:
1. _candles_for_netuid logs a warning (not silently returns []) when a key is
   missing or when candles are empty.
2. _candles_for_netuid logs a warning when a non-string key (write-time bug)
   is found via the defensive fallback.
3. normalize_price_cache_keys rewrites non-canonical string keys to canonical
   form and leaves already-canonical keys untouched.
4. audit_cache_coverage confirms every netuid in predictions resolves to a
   non-empty candle block, and returns useful missing/empty diagnostics.
5. End-to-end: every netuid carried by a pending or resolved prediction in
   predictions.json has at least one candle in price_cache.json.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import pytest

import internal.council.price_reference as price_reference
from internal.council.price_reference import (
    _candles_for_netuid,
    audit_cache_coverage,
    normalize_price_cache_keys,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candle(ts: str, close: float = 1.0) -> dict:
    return {
        "timestamp": ts,
        "open": close,
        "high": close + 0.01,
        "low": close - 0.01,
        "close": close,
        "volume": 100.0,
    }


def _pred(netuid: int, status: str = "pending") -> dict:
    now = datetime.now(timezone.utc)
    resolve_at = (now + timedelta(hours=1)).isoformat()
    return {
        "id": f"pred_{netuid}_{status}",
        "netuid": netuid,
        "name": "TestSubnet",
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 100.0,
        "resolve_at": resolve_at,
        "created_at": resolve_at,
        "status": status,
        "horizon_type": "hour",
    }


# ---------------------------------------------------------------------------
# 1. _candles_for_netuid — missing key logs a warning
# ---------------------------------------------------------------------------


def test_missing_key_logs_warning(caplog):
    """No cache entry → warning logged, empty list returned."""
    cache = {}
    with caplog.at_level(logging.WARNING, logger="internal.council.price_reference"):
        result = _candles_for_netuid(cache, 42)
    assert result == []
    assert any("42" in m for m in caplog.messages), (
        f"Expected a warning mentioning netuid 42, got: {caplog.messages}"
    )


# ---------------------------------------------------------------------------
# 2. _candles_for_netuid — empty candle list logs a warning
# ---------------------------------------------------------------------------


def test_empty_candles_logs_warning(caplog):
    """Cache entry exists but candles=[] → warning logged, empty list returned."""
    cache = {"99": {"source": "test", "candles": []}}
    with caplog.at_level(logging.WARNING, logger="internal.council.price_reference"):
        result = _candles_for_netuid(cache, 99)
    assert result == []
    assert any("99" in m for m in caplog.messages), (
        f"Expected a warning mentioning netuid 99, got: {caplog.messages}"
    )


# ---------------------------------------------------------------------------
# 3. _candles_for_netuid — non-string integer key logs a warning (fallback path)
# ---------------------------------------------------------------------------


def test_non_string_key_fallback_logs_warning(caplog):
    """Integer key in cache dict (write-time bug) triggers a warning."""
    # Python dict can have integer keys even though JSON always serialises to
    # strings.  This simulates an in-memory cache produced by broken writer code.
    cache = {7: {"source": "test", "candles": [_make_candle("2026-01-01T00:00:00+00:00")]}}
    with caplog.at_level(logging.WARNING, logger="internal.council.price_reference"):
        result = _candles_for_netuid(cache, 7)
    # The fallback still returns the candles so grading can proceed.
    assert len(result) == 1
    # A warning about the key inconsistency must have been emitted.
    assert any("inconsistency" in m.lower() or "non-string" in m.lower() for m in caplog.messages), (
        f"Expected a key-inconsistency warning, got: {caplog.messages}"
    )


# ---------------------------------------------------------------------------
# 4. _candles_for_netuid — happy path (string key, non-empty candles)
# ---------------------------------------------------------------------------


def test_string_key_happy_path_no_warning(caplog):
    """Canonical string key with valid candles → no warning, candles returned."""
    ts = "2026-01-01T00:00:00+00:00"
    cache = {"5": {"source": "test", "candles": [_make_candle(ts, close=1.5)]}}
    with caplog.at_level(logging.WARNING, logger="internal.council.price_reference"):
        result = _candles_for_netuid(cache, 5)
    assert len(result) == 1
    assert caplog.messages == [], f"Unexpected warnings: {caplog.messages}"


# ---------------------------------------------------------------------------
# 5. normalize_price_cache_keys — canonical keys left unchanged
# ---------------------------------------------------------------------------


def test_normalize_canonical_keys_unchanged(tmp_path):
    cache_path = str(tmp_path / "price_cache.json")
    cache = {
        "1": {"source": "test", "candles": []},
        "42": {"source": "test", "candles": []},
    }
    with open(cache_path, "w") as f:
        json.dump(cache, f)

    renamed = normalize_price_cache_keys(cache_path)
    assert renamed == 0

    with open(cache_path) as f:
        result = json.load(f)
    assert set(result.keys()) == {"1", "42"}


def test_normalize_strips_leading_zeros(tmp_path):
    """Keys like '01' must be normalised to '1'."""
    cache_path = str(tmp_path / "price_cache.json")
    # JSON keys are always strings, so we can write "01" as a string key.
    cache = {"01": {"source": "test", "candles": []}}
    with open(cache_path, "w") as f:
        json.dump(cache, f)

    renamed = normalize_price_cache_keys(cache_path)
    assert renamed == 1

    with open(cache_path) as f:
        result = json.load(f)
    assert "1" in result
    assert "01" not in result


def test_normalize_non_integer_keys_preserved(tmp_path):
    """Keys like '107.alpha' that are not plain integers are left as-is."""
    cache_path = str(tmp_path / "price_cache.json")
    cache = {
        "107.alpha": {"source": "test", "candles": []},
        "1": {"source": "test", "candles": []},
    }
    with open(cache_path, "w") as f:
        json.dump(cache, f)

    renamed = normalize_price_cache_keys(cache_path)
    assert renamed == 0

    with open(cache_path) as f:
        result = json.load(f)
    assert "107.alpha" in result
    assert "1" in result


# ---------------------------------------------------------------------------
# 6. audit_cache_coverage — all netuids present and non-empty → ok list
# ---------------------------------------------------------------------------


def test_audit_all_present(tmp_path):
    preds_path = str(tmp_path / "predictions.json")
    cache_path = str(tmp_path / "price_cache.json")

    ts = "2026-01-01T00:00:00+00:00"
    preds = {"predictions": [_pred(1), _pred(2)], "resolved": [_pred(3, "resolved")], "stats": {}}
    cache = {
        "1": {"source": "test", "candles": [_make_candle(ts)]},
        "2": {"source": "test", "candles": [_make_candle(ts)]},
        "3": {"source": "test", "candles": [_make_candle(ts)]},
    }
    with open(preds_path, "w") as f:
        json.dump(preds, f)
    with open(cache_path, "w") as f:
        json.dump(cache, f)

    report = audit_cache_coverage(preds_path, cache_path)
    assert set(report["ok"]) == {"1", "2", "3"}
    assert report["missing"] == []
    assert report["empty"] == []


def test_audit_missing_netuid_reported(tmp_path, caplog):
    preds_path = str(tmp_path / "predictions.json")
    cache_path = str(tmp_path / "price_cache.json")

    preds = {"predictions": [_pred(10)], "resolved": [], "stats": {}}
    cache = {}  # netuid 10 is absent
    with open(preds_path, "w") as f:
        json.dump(preds, f)
    with open(cache_path, "w") as f:
        json.dump(cache, f)

    with caplog.at_level(logging.WARNING, logger="internal.council.price_reference"):
        report = audit_cache_coverage(preds_path, cache_path)

    assert "10" in report["missing"]
    assert report["ok"] == []
    assert any("10" in m for m in caplog.messages), (
        f"Expected warning about netuid 10, got: {caplog.messages}"
    )


def test_audit_empty_candles_reported(tmp_path, caplog):
    preds_path = str(tmp_path / "predictions.json")
    cache_path = str(tmp_path / "price_cache.json")

    preds = {"predictions": [_pred(20)], "resolved": [], "stats": {}}
    cache = {"20": {"source": "test", "candles": []}}
    with open(preds_path, "w") as f:
        json.dump(preds, f)
    with open(cache_path, "w") as f:
        json.dump(cache, f)

    with caplog.at_level(logging.WARNING, logger="internal.council.price_reference"):
        report = audit_cache_coverage(preds_path, cache_path)

    assert "20" in report["empty"]
    assert report["missing"] == []
    assert any("20" in m for m in caplog.messages), (
        f"Expected warning about netuid 20, got: {caplog.messages}"
    )


# ---------------------------------------------------------------------------
# 7. End-to-end live-file check: every netuid in predictions.json must resolve
#    to a non-empty candle block in the current price_cache.json.
#    This is the startup-gate / regression guard described in the task spec.
# ---------------------------------------------------------------------------


PREDICTIONS_PATH = os.path.join("data", "predictions.json")
PRICE_CACHE_PATH_LIVE = os.path.join("data", "price_cache.json")


@pytest.mark.skipif(
    not os.path.exists(PREDICTIONS_PATH) or not os.path.exists(PRICE_CACHE_PATH_LIVE),
    reason="Live data files not present in this environment",
)
def test_live_cache_covers_all_prediction_netuids(caplog):
    """Every netuid in the live predictions file must have ≥1 candle in price_cache.

    A failure here means a subnet is silently un-gradeable: resolve_due_predictions
    will retire its predictions with outcome='expired' / retirement_reason='missing_price_at_horizon'
    instead of grading them.
    """
    with caplog.at_level(logging.WARNING, logger="internal.council.price_reference"):
        report = audit_cache_coverage(PREDICTIONS_PATH, PRICE_CACHE_PATH_LIVE)

    uncovered = report["missing"] + report["empty"]

    # Build a readable failure message listing each uncovered netuid.
    if uncovered:
        msg_lines = [
            f"The following netuids in {PREDICTIONS_PATH} have no usable candles "
            f"in {PRICE_CACHE_PATH_LIVE} and are silently un-gradeable:"
        ]
        for uid in sorted(uncovered, key=lambda x: int(x) if x.isdigit() else 0):
            reason = "missing from cache" if uid in report["missing"] else "empty candle list"
            msg_lines.append(f"  netuid {uid}: {reason}")
        pytest.fail("\n".join(msg_lines))
