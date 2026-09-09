"""P0.3 — MFE instrumentation math, resolve stamp, backfill marking."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from internal.learning.pump_mfe import (
    backfill_pump_mfe,
    mfe_hit,
    mfe_max_1h,
    report_mfe_hit_rates,
    stamp_pump_mfe_fields,
    terminal_return_1h,
)
from internal.learning.pump_lead_recover import _finalize_grade


def _ts(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def test_terminal_return_and_known_mfe_synthetic_series():
    ref = 100.0
    # Series: spike to 108 mid-window, close at 101 → terminal +1%, MFE +8%
    prices = [100.0, 104.0, 108.0, 102.0, 101.0]
    assert terminal_return_1h(ref, prices[-1]) == pytest.approx(1.0)
    assert mfe_max_1h(ref, prices, direction="up") == pytest.approx(8.0)

    candles = [
        {"timestamp": "2026-01-01T00:00:00Z", "high": 100.5, "close": 100.0},
        {"timestamp": "2026-01-01T00:20:00Z", "high": 107.0, "close": 105.0},
        {"timestamp": "2026-01-01T00:40:00Z", "high": 109.0, "close": 106.0},
        {"timestamp": "2026-01-01T01:00:00Z", "high": 102.0, "close": 101.0},
    ]
    assert mfe_max_1h(ref, candles, direction="up") == pytest.approx(9.0)
    assert terminal_return_1h(ref, 101.0) == pytest.approx(1.0)


def test_stamp_does_not_mutate_signal_snapshot_or_correct():
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    resolve = created + timedelta(hours=1)
    snap = {"price": 100.0, "buy_ratio": 0.6, "frozen": True}
    pred = {
        "id": "p1",
        "netuid": 42,
        "pick_source": "pump_lead",
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 100.0,
        "created_at": _ts(created),
        "resolve_at": _ts(resolve),
        "signal_snapshot": snap,
        "correct": False,
        "outcome": "miss",
        "actual_pct": 0.5,
        "resolved_price": 100.5,
    }
    candles = [
        {"timestamp": _ts(created + timedelta(minutes=m)), "high": h, "close": c}
        for m, h, c in [(0, 100.0, 100.0), (30, 105.0, 104.0), (60, 101.0, 100.5)]
    ]
    snap_copy = copy.deepcopy(snap)
    stamp_pump_mfe_fields(pred, terminal_price=100.5, candles=candles)
    assert pred["signal_snapshot"] is snap
    assert pred["signal_snapshot"] == snap_copy
    assert pred["correct"] is False
    assert pred["outcome"] == "miss"
    assert pred["terminal_return_1h"] == pytest.approx(0.5)
    assert pred["mfe_max_1h"] == pytest.approx(5.0)
    assert pred["mfe_regradable"] is True
    assert mfe_hit(pred) is True  # MFE hit while terminal miss


def test_finalize_grade_stamps_mfe_and_keeps_terminal_miss():
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    resolve = created + timedelta(hours=1)
    snap = {"price": 100.0}
    pred = {
        "id": "p2",
        "netuid": 7,
        "pick_source": "pump_lead",
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 100.0,
        "created_at": _ts(created),
        "resolve_at": _ts(resolve),
        "signal_snapshot": snap,
    }
    cache = {
        "7": {
            "candles": [
                {"timestamp": _ts(created + timedelta(minutes=0)), "high": 100.0, "close": 100.0, "volume": 1},
                {"timestamp": _ts(created + timedelta(minutes=20)), "high": 108.0, "close": 107.0, "volume": 1},
                {"timestamp": _ts(created + timedelta(minutes=60)), "high": 101.0, "close": 100.5, "volume": 1},
            ]
        }
    }
    out = _finalize_grade(
        pred,
        price=100.5,
        meta={"price_source": "vwap", "candles_in_window": 1},
        resolve_at=resolve,
        cache=cache,
    )
    assert out["correct"] is False  # +0.5% < +2% claim
    assert out["actual_pct"] == pytest.approx(0.5)
    assert out["terminal_return_1h"] == pytest.approx(0.5)
    assert out["mfe_max_1h"] == pytest.approx(8.0)
    assert out["mfe_regradable"] is True
    assert out["signal_snapshot"] == snap


def test_backfill_marks_regradable_vs_not(tmp_path):
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    resolve = created + timedelta(hours=1)
    good = {
        "id": "good",
        "netuid": 3,
        "pick_source": "pump_lead",
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 50.0,
        "created_at": _ts(created),
        "resolve_at": _ts(resolve),
        "resolved_price": 51.0,
        "correct": True,
        "actual_pct": 2.0,
        "outcome": "hit",
        "signal_snapshot": {"x": 1},
    }
    bad = {
        "id": "bad",
        "netuid": 4,
        "pick_source": "pump_lead",
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 50.0,
        "created_at": _ts(created),
        "resolve_at": _ts(resolve),
        "resolved_price": 49.0,
        "correct": False,
        "actual_pct": -2.0,
        "outcome": "miss",
        "signal_snapshot": {"x": 2},
    }
    data = {"predictions": [], "resolved": [good, bad]}
    cache = {
        "3": {
            "candles": [
                {"timestamp": _ts(created), "high": 50.0, "close": 50.0},
                {"timestamp": _ts(created + timedelta(minutes=30)), "high": 52.0, "close": 51.5},
                {"timestamp": _ts(resolve), "high": 51.2, "close": 51.0},
            ]
        }
        # netuid 4 missing → not regradable for MFE
    }
    out, summary = backfill_pump_mfe(data, cache=cache, dry_run=True)
    assert summary["dry_run"] is True
    assert summary["regradable"] == 1
    assert summary["not_regradable"] == 1
    rows = {r["id"]: r for r in out["resolved"]}
    assert rows["good"]["mfe_regradable"] is True
    assert rows["good"]["mfe_max_1h"] == pytest.approx(4.0)
    assert rows["good"]["terminal_return_1h"] == pytest.approx(2.0)
    assert rows["good"]["signal_snapshot"] == {"x": 1}
    assert rows["bad"]["mfe_regradable"] is False
    assert rows["bad"]["mfe_ungradeable_reason"] == "missing_horizon_candles"
    # dry-run must not mutate input rows
    assert "mfe_max_1h" not in good
    assert "mfe_max_1h" not in bad


def test_report_terminal_vs_mfe_side_by_side():
    rows = [
        {
            "pick_source": "pump_lead",
            "pump_claim": "ACCUMULATING",
            "correct": False,
            "actual_pct": 0.5,
            "predicted_pct": 2.0,
            "mfe_regradable": True,
            "mfe_max_1h": 5.0,
        },
        {
            "pick_source": "pump_lead",
            "pump_claim": "JUST_STARTED",
            "correct": True,
            "actual_pct": 3.0,
            "predicted_pct": 2.0,
            "mfe_regradable": True,
            "mfe_max_1h": 3.0,
        },
    ]
    report = report_mfe_hit_rates({"resolved": rows})
    early = report["early_pump"]
    assert early["terminal_only"]["n"] == 1
    assert early["terminal_only"]["hits"] == 0
    assert early["terminal_only"]["hit_rate"] == 0.0
    assert early["mfe"]["n"] == 1
    assert early["mfe"]["hits"] == 1
    assert early["mfe"]["hit_rate"] == 1.0
    just = report["just_started"]
    assert just["terminal_only"]["hits"] == 1
    assert just["mfe"]["hits"] == 1
