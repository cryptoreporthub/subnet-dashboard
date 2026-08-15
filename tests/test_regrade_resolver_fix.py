"""RF-3 — regrade_expired must survive resolve_due_predictions final save.

Also covers cold-cache expiry (task-88): predictions must not be silently
retired as genuine_expiry when the price cache lacked candles at their
original horizon deadline.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import internal.council.price_reference as price_reference
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


# ---------------------------------------------------------------------------
# Task-88: cold-cache expiry tests
# ---------------------------------------------------------------------------


def _make_pred(pred_id: str, netuid: int, resolve_at: str, **extra) -> dict:
    base = {
        "id": pred_id,
        "netuid": netuid,
        "name": "TestSubnet",
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 100.0,
        "resolve_at": resolve_at,
        "created_at": resolve_at,
        "status": "pending",
        "horizon_type": "hour",
        "horizon_hours": 24.0,
    }
    base.update(extra)
    return base


def test_cold_cache_expiry_marks_missing_price(monkeypatch):
    """Past-grace + no candles → retirement_reason=missing_price_at_horizon (not genuine_expiry)."""
    now = datetime.now(timezone.utc)
    # 50h past horizon → past 48h grace window (horizon_hours=24 * grace_multiple=2)
    resolve_at = (now - timedelta(hours=50)).isoformat().replace("+00:00", "Z")
    pred = _make_pred("pred_cold_1", 99, resolve_at)
    _write_predictions({"predictions": [pred], "resolved": [], "stats": {}})

    # Suppress the rate-limited hydration attempt so no network call happens.
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_a, **_k: False)

    resolver.resolve_due_predictions(subnets=[])

    with open(resolver.PREDICTIONS_PATH) as f:
        saved = json.load(f)

    assert len(saved["predictions"]) == 0, "prediction must move out of pending"
    assert len(saved["resolved"]) == 1
    retired = saved["resolved"][0]
    assert retired["outcome"] in {"expired", "ungradeable"}
    assert retired.get("retirement_reason") == "missing_price_at_horizon", (
        f"Expected missing_price_at_horizon, got {retired.get('retirement_reason')!r}"
    )


def test_past_grace_prediction_graded_when_candles_available(monkeypatch):
    """Past-grace prediction with a candle in cache must be graded, not expired."""
    now = datetime.now(timezone.utc)
    resolve_at_dt = now - timedelta(hours=50)
    resolve_at = resolve_at_dt.isoformat().replace("+00:00", "Z")
    pred = _make_pred("pred_late_grade_1", 42, resolve_at)
    _write_predictions({"predictions": [pred], "resolved": [], "stats": {}})

    # Plant a candle at resolve_at in the price cache.
    candle_ts = resolve_at_dt.isoformat().replace("+00:00", "Z")
    cache = {
        "42": {
            "source": "test",
            "candles": [
                {
                    "timestamp": candle_ts,
                    "open": 102.0,
                    "high": 103.0,
                    "low": 101.0,
                    "close": 103.0,
                    "volume": 500.0,
                }
            ],
        }
    }
    with open(resolver.PRICE_CACHE_PATH, "w") as f:
        json.dump(cache, f)

    # Suppress hydration so the test is deterministic (candle already planted).
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_a, **_k: False)

    resolver.resolve_due_predictions(subnets=[])

    with open(resolver.PREDICTIONS_PATH) as f:
        saved = json.load(f)

    assert len(saved["predictions"]) == 0
    assert len(saved["resolved"]) == 1
    graded = saved["resolved"][0]
    assert graded["outcome"] in {"hit", "miss"}, (
        f"Expected graded outcome, got {graded['outcome']!r}"
    )
    assert graded.get("correct") is not None


def test_regrade_hydrates_missing_price_rows(monkeypatch):
    """regrade_expired_predictions must call hydrate_candles_for_netuid for missing-price rows."""
    now = datetime.now(timezone.utc)
    resolve_at = (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    expired_pred = _make_pred(
        "pred_hydrate_1",
        55,
        resolve_at,
        status="expired",
        outcome="expired",
        retirement_reason="missing_price_at_horizon",
    )
    _write_predictions({"predictions": [], "resolved": [expired_pred], "stats": {}})

    hydrate_calls: list = []

    def _fake_hydrate(netuid, cache_path=None):
        hydrate_calls.append(str(netuid))
        return False  # pretend nothing was newly fetched

    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", _fake_hydrate)

    resolver.regrade_expired_predictions()

    assert "55" in hydrate_calls, (
        f"hydrate_candles_for_netuid not called for netuid 55; calls={hydrate_calls}"
    )


def test_regrade_rescues_missing_price_row_when_candle_appears(monkeypatch):
    """regrade_expired_predictions grades a missing-price row when candles are now in cache."""
    now = datetime.now(timezone.utc)
    resolve_at_dt = now - timedelta(hours=2)
    resolve_at = resolve_at_dt.isoformat().replace("+00:00", "Z")
    expired_pred = _make_pred(
        "pred_rescue_1",
        77,
        resolve_at,
        status="expired",
        outcome="expired",
        retirement_reason="missing_price_at_horizon",
    )
    _write_predictions({"predictions": [], "resolved": [expired_pred], "stats": {}})

    # Plant a candle at resolve_at (within the ±90-minute lookup window).
    candle_ts = resolve_at_dt.isoformat().replace("+00:00", "Z")
    cache = {
        "77": {
            "source": "test",
            "candles": [
                {
                    "timestamp": candle_ts,
                    "open": 101.0,
                    "high": 102.0,
                    "low": 100.0,
                    "close": 101.0,
                    "volume": 1000.0,
                }
            ],
        }
    }
    with open(resolver.PRICE_CACHE_PATH, "w") as f:
        json.dump(cache, f)

    # Suppress network hydration; candle is already planted.
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_a, **_k: False)
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid_historical", lambda *_a, **_k: False)

    result = resolver.regrade_expired_predictions()

    assert result["regraded"] == 1, f"Expected 1 regraded, got {result}"
    with open(resolver.PREDICTIONS_PATH) as f:
        saved = json.load(f)
    graded = saved["resolved"][0]
    assert graded["outcome"] in {"hit", "miss"}, (
        f"Expected graded outcome, got {graded['outcome']!r}"
    )


# ---------------------------------------------------------------------------
# Task-93: historical hydration tests (resolve_at > 24 h in the past)
# ---------------------------------------------------------------------------


def test_regrade_historical_hydration_called_for_old_horizon(monkeypatch):
    """regrade_expired: resolve_at > 24 h triggers hydrate_candles_for_netuid_historical, not the standard one."""
    now = datetime.now(timezone.utc)
    resolve_at_dt = now - timedelta(hours=48)
    resolve_at = resolve_at_dt.isoformat().replace("+00:00", "Z")
    expired_pred = _make_pred(
        "pred_hist_call_1",
        88,
        resolve_at,
        status="expired",
        outcome="expired",
        retirement_reason="missing_price_at_horizon",
    )
    _write_predictions({"predictions": [], "resolved": [expired_pred], "stats": {}})

    hist_calls: list = []
    std_calls: list = []

    monkeypatch.setattr(
        resolver,
        "hydrate_candles_for_netuid_historical",
        lambda netuid, resolve_at_arg, **_k: hist_calls.append(str(netuid)) or False,
    )
    monkeypatch.setattr(
        resolver,
        "hydrate_candles_for_netuid",
        lambda netuid, **_k: std_calls.append(str(netuid)) or False,
    )

    resolver.regrade_expired_predictions()

    assert "88" in hist_calls, (
        f"hydrate_candles_for_netuid_historical not called for netuid 88; calls={hist_calls}"
    )
    assert "88" not in std_calls, (
        f"hydrate_candles_for_netuid (standard) must not be called for a >24 h horizon; calls={std_calls}"
    )


def test_regrade_historical_hydration_48h_regraded(monkeypatch):
    """regrade_expired: a prediction 48 h old is graded when historical hydration supplies a candle."""
    now = datetime.now(timezone.utc)
    resolve_at_dt = now - timedelta(hours=48)
    resolve_at = resolve_at_dt.isoformat().replace("+00:00", "Z")

    expired_pred = _make_pred(
        "pred_hist_grade_1",
        88,
        resolve_at,
        status="expired",
        outcome="expired",
        retirement_reason="missing_price_at_horizon",
    )
    _write_predictions({"predictions": [], "resolved": [expired_pred], "stats": {}})

    def _fake_hist_hydrate(netuid, resolve_at_arg, **_k):
        """Plant a candle at resolve_at in the price cache to simulate a successful historical fetch."""
        candle_ts = resolve_at_dt.isoformat().replace("+00:00", "Z")
        cache = {
            str(netuid): {
                "source": "test",
                "candles": [
                    {
                        "timestamp": candle_ts,
                        "open": 105.0,
                        "high": 106.0,
                        "low": 104.0,
                        "close": 105.0,
                        "volume": 800.0,
                    }
                ],
            }
        }
        with open(resolver.PRICE_CACHE_PATH, "w") as f:
            json.dump(cache, f)
        return True

    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid_historical", _fake_hist_hydrate)
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_a, **_k: False)

    result = resolver.regrade_expired_predictions()

    assert result["regraded"] == 1, f"Expected 1 regraded, got {result}"
    with open(resolver.PREDICTIONS_PATH) as f:
        saved = json.load(f)
    graded = saved["resolved"][0]
    assert graded["outcome"] in {"hit", "miss"}, (
        f"Expected graded outcome after historical hydration, got {graded['outcome']!r}"
    )
    assert graded.get("correct") is not None


# ---------------------------------------------------------------------------
# Task-99: CALIBRATION_HIST_MAX_DAYS cap tests
# ---------------------------------------------------------------------------


def test_hydrate_historical_returns_none_when_too_old(monkeypatch):
    """hydrate_candles_for_netuid_historical returns None when age exceeds CALIBRATION_HIST_MAX_DAYS."""
    # Force a low cap so we don't need a truly ancient resolve_at.
    monkeypatch.setattr(price_reference, "CALIBRATION_HIST_MAX_DAYS", 10)
    # Clear the rate-limit memo so the cap check is the only barrier.
    price_reference._hydrate_hist_memo.clear()

    now = datetime.now(timezone.utc)
    # 12 days old → days_needed = ceil(12*24/24) + 2 = 14 > cap of 10
    resolve_at = now - timedelta(days=12)

    result = price_reference.hydrate_candles_for_netuid_historical(
        netuid=999,
        resolve_at=resolve_at,
    )
    assert result is None, (
        f"Expected None (cap sentinel) but got {result!r}"
    )


def test_hydrate_historical_does_not_cap_within_limit(monkeypatch, tmp_path):
    """hydrate_candles_for_netuid_historical does not return None when within the cap."""
    monkeypatch.setattr(price_reference, "CALIBRATION_HIST_MAX_DAYS", 30)
    price_reference._hydrate_hist_memo.clear()

    import sys, types
    fake_mod = types.ModuleType("internal.indicators.price_fetcher")
    fetch_calls: list = []

    def _fake_fetch(netuid, days=7, **_kw):
        fetch_calls.append((netuid, days))

    fake_mod.fetch_ohlcv = _fake_fetch  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "internal.indicators.price_fetcher", fake_mod)

    now = datetime.now(timezone.utc)
    # 5 days old → days_needed = ceil(120/24) + 2 = 7 ≤ 30 → should proceed
    resolve_at = now - timedelta(days=5)

    result = price_reference.hydrate_candles_for_netuid_historical(
        netuid=998,
        resolve_at=resolve_at,
        cache_path=str(tmp_path / "price_cache.json"),
    )
    assert result is not None, (
        f"Expected True or False (not None) when within the cap; got {result!r}"
    )


def test_regrade_sets_horizon_too_old_when_cap_fires(monkeypatch):
    """regrade_expired_predictions sets retirement_reason=horizon_too_old_for_history when cap fires."""
    now = datetime.now(timezone.utc)
    # 35 days old — well beyond the default 30-day cap
    resolve_at_dt = now - timedelta(days=35)
    resolve_at = resolve_at_dt.isoformat().replace("+00:00", "Z")

    expired_pred = _make_pred(
        "pred_too_old_1",
        66,
        resolve_at,
        status="expired",
        outcome="expired",
        retirement_reason="missing_price_at_horizon",
    )
    _write_predictions({"predictions": [], "resolved": [expired_pred], "stats": {}})

    # Make historical hydration return None (cap fired) for this prediction.
    monkeypatch.setattr(
        resolver,
        "hydrate_candles_for_netuid_historical",
        lambda netuid, resolve_at_arg, **_k: None,
    )
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_a, **_k: False)

    resolver.regrade_expired_predictions()

    with open(resolver.PREDICTIONS_PATH) as f:
        saved = json.load(f)

    # The prediction must stay in resolved (not promoted back to pending).
    assert len(saved["predictions"]) == 0
    assert len(saved["resolved"]) == 1
    retired = saved["resolved"][0]
    assert retired.get("retirement_reason") == "horizon_too_old_for_history", (
        f"Expected horizon_too_old_for_history, got {retired.get('retirement_reason')!r}"
    )
    # outcome must still be expired (we did not regrade it)
    assert retired.get("outcome") == "expired"


def test_regrade_does_not_set_too_old_for_within_cap_prediction(monkeypatch):
    """Predictions within CALIBRATION_HIST_MAX_DAYS cap are not marked horizon_too_old_for_history."""
    now = datetime.now(timezone.utc)
    # 3 days old — well within the 30-day default cap
    resolve_at_dt = now - timedelta(hours=72)
    resolve_at = resolve_at_dt.isoformat().replace("+00:00", "Z")

    expired_pred = _make_pred(
        "pred_within_cap_1",
        77,
        resolve_at,
        status="expired",
        outcome="expired",
        retirement_reason="missing_price_at_horizon",
    )
    _write_predictions({"predictions": [], "resolved": [expired_pred], "stats": {}})

    hist_calls: list = []

    # Historical hydration returns False (rate-limited / no fetch) — NOT None.
    monkeypatch.setattr(
        resolver,
        "hydrate_candles_for_netuid_historical",
        lambda netuid, resolve_at_arg, **_k: hist_calls.append(str(netuid)) or False,
    )
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_a, **_k: False)

    resolver.regrade_expired_predictions()

    with open(resolver.PREDICTIONS_PATH) as f:
        saved = json.load(f)

    retired = saved["resolved"][0]
    assert retired.get("retirement_reason") != "horizon_too_old_for_history", (
        f"retirement_reason must not be horizon_too_old_for_history for a within-cap prediction; "
        f"got {retired.get('retirement_reason')!r}"
    )
    # Historical hydration must have been attempted (prediction is >24 h old).
    assert "77" in hist_calls, f"hydrate_candles_for_netuid_historical not called; calls={hist_calls}"


# ---------------------------------------------------------------------------
# Task-100: historical_hydration_attempted stamp + stats breakdown
# ---------------------------------------------------------------------------


def test_regrade_stamps_historical_hydration_attempted_when_still_ungradeable(monkeypatch):
    """When historical hydration is triggered but grading still fails, stamp historical_hydration_attempted=True."""
    now = datetime.now(timezone.utc)
    resolve_at_dt = now - timedelta(hours=48)
    resolve_at = resolve_at_dt.isoformat().replace("+00:00", "Z")

    expired_pred = _make_pred(
        "pred_stamp_1",
        88,
        resolve_at,
        status="expired",
        outcome="expired",
        retirement_reason="missing_price_at_horizon",
    )
    _write_predictions({"predictions": [], "resolved": [expired_pred], "stats": {}})

    # Historical hydration returns False (rate-limited) — but still a non-None result.
    # Price cache remains empty so grading still fails.
    monkeypatch.setattr(
        resolver,
        "hydrate_candles_for_netuid_historical",
        lambda netuid, resolve_at_arg, **_k: False,
    )
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_a, **_k: False)

    result = resolver.regrade_expired_predictions()

    # Return dict must expose the breakdown.
    assert result["historical_hydration_attempted"] == 1, (
        f"Expected historical_hydration_attempted=1, got {result['historical_hydration_attempted']}"
    )
    assert result["historical_hydration_ungradeable"] == 1, (
        f"Expected historical_hydration_ungradeable=1, got {result['historical_hydration_ungradeable']}"
    )

    # On-disk row must carry the stamp.
    with open(resolver.PREDICTIONS_PATH) as f:
        saved = json.load(f)
    retired = saved["resolved"][0]
    assert retired.get("historical_hydration_attempted") is True, (
        f"Expected historical_hydration_attempted=True on disk, got {retired.get('historical_hydration_attempted')!r}"
    )


def test_regrade_no_stamp_when_cap_fires(monkeypatch):
    """When historical hydration returns None (cap), historical_hydration_attempted must NOT be stamped."""
    now = datetime.now(timezone.utc)
    resolve_at_dt = now - timedelta(days=35)
    resolve_at = resolve_at_dt.isoformat().replace("+00:00", "Z")

    expired_pred = _make_pred(
        "pred_cap_no_stamp_1",
        66,
        resolve_at,
        status="expired",
        outcome="expired",
        retirement_reason="missing_price_at_horizon",
    )
    _write_predictions({"predictions": [], "resolved": [expired_pred], "stats": {}})

    monkeypatch.setattr(
        resolver,
        "hydrate_candles_for_netuid_historical",
        lambda netuid, resolve_at_arg, **_k: None,
    )
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_a, **_k: False)

    result = resolver.regrade_expired_predictions()

    assert result["historical_hydration_attempted"] == 0, (
        f"historical_hydration_attempted must be 0 when cap fires, got {result['historical_hydration_attempted']}"
    )
    assert result["historical_hydration_ungradeable"] == 0, (
        f"historical_hydration_ungradeable must be 0 when cap fires, got {result['historical_hydration_ungradeable']}"
    )

    with open(resolver.PREDICTIONS_PATH) as f:
        saved = json.load(f)
    retired = saved["resolved"][0]
    assert not retired.get("historical_hydration_attempted"), (
        f"historical_hydration_attempted must not be set when cap fires, got {retired.get('historical_hydration_attempted')!r}"
    )


def test_compute_stats_counts_historical_hydration_ungradeable(monkeypatch):
    """_compute_stats must include historical_hydration_ungradeable for stamped rows."""
    now = datetime.now(timezone.utc)
    resolve_at_dt = now - timedelta(hours=50)
    resolve_at = resolve_at_dt.isoformat().replace("+00:00", "Z")

    # A row stamped with historical_hydration_attempted and still expired.
    retired = _make_pred(
        "pred_stats_hist_1",
        88,
        resolve_at,
        status="expired",
        outcome="expired",
        retirement_reason="missing_price_at_horizon",
        historical_hydration_attempted=True,
    )
    # A regular missing-price row without the stamp.
    retired2 = _make_pred(
        "pred_stats_hist_2",
        89,
        resolve_at,
        status="expired",
        outcome="expired",
        retirement_reason="missing_price_at_horizon",
    )
    data = {"predictions": [], "resolved": [retired, retired2]}
    stats = resolver._compute_stats(data)

    assert stats["historical_hydration_ungradeable"] == 1, (
        f"Expected 1 historical_hydration_ungradeable, got {stats['historical_hydration_ungradeable']}"
    )
    assert stats["price_data_unavailable"] == 2, (
        f"Expected 2 price_data_unavailable, got {stats['price_data_unavailable']}"
    )


def test_regrade_stamp_not_duplicated_on_second_pass(monkeypatch):
    """If a row already carries historical_hydration_attempted, a second regrade pass does not double-count it."""
    now = datetime.now(timezone.utc)
    resolve_at_dt = now - timedelta(hours=48)
    resolve_at = resolve_at_dt.isoformat().replace("+00:00", "Z")

    # Row that was already stamped by a previous regrade run.
    expired_pred = _make_pred(
        "pred_stamp_idempotent_1",
        88,
        resolve_at,
        status="expired",
        outcome="expired",
        retirement_reason="missing_price_at_horizon",
        historical_hydration_attempted=True,
    )
    _write_predictions({"predictions": [], "resolved": [expired_pred], "stats": {}})

    monkeypatch.setattr(
        resolver,
        "hydrate_candles_for_netuid_historical",
        lambda netuid, resolve_at_arg, **_k: False,
    )
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_a, **_k: False)

    result = resolver.regrade_expired_predictions()

    # historical_hydration_attempted counter reflects this run's dispatch, not the prior stamp.
    assert result["historical_hydration_attempted"] == 1
    # ungradeable count is still 1 — the row remains ungradeable.
    assert result["historical_hydration_ungradeable"] == 1


def test_resolve_due_preserves_historical_hydration_stamp_when_ungradeable(monkeypatch):
    """resolve_due_predictions must not overwrite the historical_hydration_attempted stamp.

    When regrade_expired_predictions writes the stamp but grading still fails
    (regraded == 0), resolve_due_predictions used to save a stale in-memory
    resolved list, silently erasing the stamp.  The ledger_mutated flag now
    forces a re-sync so the stamp is preserved on disk.
    """
    now = datetime.now(timezone.utc)
    resolve_at_dt = now - timedelta(hours=48)
    resolve_at = resolve_at_dt.isoformat().replace("+00:00", "Z")

    expired_pred = _make_pred(
        "pred_stamp_via_resolve_due_1",
        88,
        resolve_at,
        status="expired",
        outcome="expired",
        retirement_reason="missing_price_at_horizon",
    )
    _write_predictions({"predictions": [], "resolved": [expired_pred], "stats": {}})

    # Historical hydration returns False (rate-limited) — stamp should still be written.
    # Price cache stays empty so grading still fails.
    monkeypatch.setattr(
        resolver,
        "hydrate_candles_for_netuid_historical",
        lambda netuid, resolve_at_arg, **_k: False,
    )
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_a, **_k: False)

    result = resolver.resolve_due_predictions(subnets=[])

    # The regraded_expired breakdown in the return dict must reflect the attempt.
    re = result["regraded_expired"]
    assert re["historical_hydration_attempted"] == 1, (
        f"Expected historical_hydration_attempted=1 in regraded_expired, got {re}"
    )
    assert re["historical_hydration_ungradeable"] == 1, (
        f"Expected historical_hydration_ungradeable=1 in regraded_expired, got {re}"
    )

    # The persisted row must carry the stamp — not be overwritten by the stale list.
    with open(resolver.PREDICTIONS_PATH) as f:
        saved = json.load(f)
    retired = saved["resolved"][0]
    assert retired.get("historical_hydration_attempted") is True, (
        f"Stamp must survive resolve_due_predictions save; got {retired.get('historical_hydration_attempted')!r}"
    )

    # The stats block must also reflect historical_hydration_ungradeable.
    assert saved["stats"].get("historical_hydration_ungradeable", 0) == 1, (
        f"stats.historical_hydration_ungradeable must be 1; got {saved['stats'].get('historical_hydration_ungradeable')!r}"
    )


def test_regrade_stamp_present_when_historical_hydration_succeeds_but_graded(monkeypatch):
    """When historical hydration supplies a candle and grading succeeds, the stamp must also appear on the graded row."""
    now = datetime.now(timezone.utc)
    resolve_at_dt = now - timedelta(hours=48)
    resolve_at = resolve_at_dt.isoformat().replace("+00:00", "Z")

    expired_pred = _make_pred(
        "pred_stamp_graded_1",
        88,
        resolve_at,
        status="expired",
        outcome="expired",
        retirement_reason="missing_price_at_horizon",
    )
    _write_predictions({"predictions": [], "resolved": [expired_pred], "stats": {}})

    def _fake_hist_hydrate(netuid, resolve_at_arg, **_k):
        candle_ts = resolve_at_dt.isoformat().replace("+00:00", "Z")
        cache = {
            str(netuid): {
                "source": "test",
                "candles": [
                    {
                        "timestamp": candle_ts,
                        "open": 105.0,
                        "high": 106.0,
                        "low": 104.0,
                        "close": 105.0,
                        "volume": 800.0,
                    }
                ],
            }
        }
        with open(resolver.PRICE_CACHE_PATH, "w") as f:
            json.dump(cache, f)
        return True

    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid_historical", _fake_hist_hydrate)
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_a, **_k: False)

    result = resolver.regrade_expired_predictions()

    assert result["regraded"] == 1, f"Expected 1 regraded, got {result}"
    assert result["historical_hydration_attempted"] == 1
    assert result["historical_hydration_ungradeable"] == 0, (
        f"Graded row must not count as ungradeable; got {result['historical_hydration_ungradeable']}"
    )

    with open(resolver.PREDICTIONS_PATH) as f:
        saved = json.load(f)
    graded = saved["resolved"][0]
    assert graded.get("historical_hydration_attempted") is True, (
        f"Graded row must carry historical_hydration_attempted=True, got {graded.get('historical_hydration_attempted')!r}"
    )
