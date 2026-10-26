"""An explicit ``grace_multiple`` must be honoured by ``resolver._is_expired`` (#1506)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def resolver():
    import internal.council.resolver as resolver_mod

    return resolver_mod


RESOLVE_AT = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def test_explicit_huge_grace_bypasses_expiry(resolver):
    pred = {"horizon_hours": 1}
    now = RESOLVE_AT + timedelta(hours=100)

    assert resolver._is_expired(pred, RESOLVE_AT, now, 1_000_000.0) is False


def test_explicit_grace_of_two_expires_at_two_horizons(resolver):
    pred = {"horizon_hours": 1}

    assert resolver._is_expired(pred, RESOLVE_AT, RESOLVE_AT + timedelta(hours=1.9), 2.0) is False
    assert resolver._is_expired(pred, RESOLVE_AT, RESOLVE_AT + timedelta(hours=2), 2.0) is True


def test_row_without_horizon_hours_keeps_the_24h_default_grace(resolver):
    pred = {"horizon_type": "hour"}

    assert resolver._is_expired(pred, RESOLVE_AT, RESOLVE_AT + timedelta(hours=5)) is False
    assert resolver._is_expired(pred, RESOLVE_AT, RESOLVE_AT + timedelta(hours=96)) is True


def test_finite_huge_grace_does_not_overflow_the_expiry_window(resolver):
    row = {"id": 1, "horizon_hours": 24, "resolve_attempts": resolver._PRICE_RETRY_CAP}

    assert resolver._is_expired(row, RESOLVE_AT, RESOLVE_AT + timedelta(days=365), 1e308) is False


@pytest.mark.parametrize("huge_horizon", [1e308, sys.float_info.max])
def test_overflowing_horizon_threshold_falls_back_to_the_default_threshold(resolver, huge_horizon):
    """A finite horizon whose grace window overflows must expire at the default threshold, not pend forever (MC finding 1, #1515)."""
    row = {"id": 1, "horizon_hours": huge_horizon, "resolve_attempts": resolver._PRICE_RETRY_CAP}

    assert (
        resolver._is_expired(row, RESOLVE_AT, RESOLVE_AT + timedelta(hours=95, minutes=59), 4.0) is False
    )
    assert resolver._is_expired(row, RESOLVE_AT, RESOLVE_AT + timedelta(hours=96), 4.0) is True


@pytest.mark.parametrize("raw_horizon", [float("inf"), float("nan"), "inf", "nan", 10**400, 1.8e308 / 4])
def test_non_finite_horizon_falls_back_to_the_default_horizon(resolver, raw_horizon):
    row = {"id": 1, "horizon_hours": raw_horizon, "resolve_attempts": resolver._PRICE_RETRY_CAP}

    assert resolver._is_expired(row, RESOLVE_AT, RESOLVE_AT + timedelta(hours=95), 4.0) is False
    assert resolver._is_expired(row, RESOLVE_AT, RESOLVE_AT + timedelta(hours=96), 4.0) is True


@pytest.mark.parametrize("huge_horizon", [1e100])
def test_finite_huge_horizon_above_one_year_uses_the_default_horizon(resolver, huge_horizon):
    """A finite horizon above the one-year max gets the default-horizon treatment, not an unreachable threshold (MC B1, #1515)."""
    row = {"id": 1, "horizon_hours": huge_horizon, "resolve_attempts": resolver._PRICE_RETRY_CAP}

    assert (
        resolver._is_expired(row, RESOLVE_AT, RESOLVE_AT + timedelta(hours=95, minutes=59), 4.0) is False
    )
    assert resolver._is_expired(row, RESOLVE_AT, RESOLVE_AT + timedelta(hours=96), 4.0) is True


def test_horizon_at_the_one_year_cap_keeps_its_own_window(resolver):
    """The max-horizon bound must not overreach: a legit 8760h horizon keeps its own grace window (MC B1, #1515)."""
    row = {"id": 1, "horizon_hours": 8760, "resolve_attempts": resolver._PRICE_RETRY_CAP}

    assert resolver._is_expired(row, RESOLVE_AT, RESOLVE_AT + timedelta(hours=96), 4.0) is False
    assert (
        resolver._is_expired(row, RESOLVE_AT, RESOLVE_AT + timedelta(hours=8760 * 4), 4.0) is True
    )


@pytest.mark.parametrize("env_grace", ["1e300", "1e308"])
def test_env_grace_above_ceiling_falls_back_to_default_and_expires(env_grace):
    """RESOLVER_EXPIRY_GRACE_MULTIPLE above the ceiling falls back to 4.0, so a past-grace at-cap row still expires (MC B1, #1515)."""
    probe = (
        "import internal.council.resolver as r;"
        "from datetime import datetime, timedelta, timezone;"
        "t = datetime(2026, 8, 9, 12, tzinfo=timezone.utc);"
        "row = {'id': 1, 'horizon_hours': 24, 'resolve_attempts': r._PRICE_RETRY_CAP};"
        "print(r._is_expired(row, t, t + timedelta(days=365)))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env={**os.environ, "RESOLVER_EXPIRY_GRACE_MULTIPLE": env_grace},
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert done.returncode == 0, done.stderr[-800:]
    assert done.stdout.strip().splitlines()[-1] == "True"


def test_late_recovery_million_grace_path_is_unchanged(resolver, tmp_path, monkeypatch):
    """Pin the past-grace recovery call site (grace_multiple=1_000_000.0): the row must get its
    lookup attempt before the caller retires it as a cold cache. A final-threshold clamp would
    expire it pre-lookup instead (MC B1, #1515)."""
    now = datetime.now(timezone.utc)
    past = (now - timedelta(hours=200)).isoformat().replace("+00:00", "Z")
    rows = [
        {
            "id": "row-9",
            "netuid": 9,
            "direction": "up",
            "predicted_pct": 5.0,
            "horizon_hours": 24,
            "horizon_type": "hour",
            "reference_price": 1.0,
            "created_at": past,
            "resolve_at": past,
            "status": "pending",
            "resolve_attempts": resolver._PRICE_RETRY_CAP,
        }
    ]
    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({"predictions": rows, "resolved": [], "stats": {}}), encoding="utf-8")
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(path))
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", str(tmp_path / "price_cache.json"))
    monkeypatch.setattr(resolver, "fetch_prices", lambda _s: {})
    monkeypatch.setattr(
        resolver,
        "regrade_expired_predictions",
        lambda **kw: {"regraded": 0, "ledger_mutated": False},
    )
    monkeypatch.setattr(resolver, "_restore_recently_expired_predictions", lambda *a, **k: [])
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda _uid: False)

    resolver.resolve_due_predictions(subnets=[])

    saved = json.loads(path.read_text(encoding="utf-8"))
    expired = [r for r in saved["resolved"] if r["id"] == "row-9"]
    assert len(expired) == 1
    row = expired[0]
    # The 1e6 late-recovery grace kept the row alive inside the helper long
    # enough to burn one real lookup (attempts moved past the cap); the caller
    # then retired it as a cold-cache miss, not a genuine expiry.
    assert row["resolve_attempts"] == resolver._PRICE_RETRY_CAP + 1
    assert row["expired_reason"] == "price_data_unavailable"
    assert row["retirement_reason"] == "missing_price_at_horizon"
