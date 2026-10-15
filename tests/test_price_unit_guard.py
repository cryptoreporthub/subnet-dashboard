from datetime import datetime, timedelta, timezone

from internal.council.grading import (
    compute_actual_pct,
    is_price_unit_mismatch,
)
from internal.council.resolver import _compute_stats, lookup_horizon_price, resolve_prediction
from scripts.issue_1375_integrity_impact import _legacy_price_unit_mismatch


def test_price_unit_guard_matches_observed_tao_usd_mismatch():
    assert is_price_unit_mismatch(0.006, 1.3)
    assert compute_actual_pct(0.006, 1.3) > 20_000


def test_price_unit_guard_catches_both_sides_below_one():
    """Production phantom hits: alpha ref vs USD-scale VWAP still both < 1."""
    assert is_price_unit_mismatch(0.00311, 0.63078)
    assert compute_actual_pct(0.00311, 0.63078) > 20_000


def test_price_unit_guard_allows_normal_move():
    assert not is_price_unit_mismatch(0.006, 0.007)
    assert not is_price_unit_mismatch(0.01939, 0.02217)


def test_price_unit_guard_flags_ref_at_or_above_one():
    """Latent hole: ref>=1 with ~190x ratio must still mismatch (#1375)."""
    assert is_price_unit_mismatch(1.5, 285.0)
    assert is_price_unit_mismatch(10.0, 210.0)


# Minimal repro rows for learning-export guard impact (ratio>=20, both sides >= 1).
_ISSUE_1375_BOTH_GE1_EXPORT_ROWS = (
    {"reference_price": 1.5, "resolved_price": 285.0},
    {"reference_price": 10.0, "resolved_price": 210.0},
)


def test_unit_guard_export_rows_both_ge1_ratio20():
    """Rows with both>=1 and ratio>=20: 2 in minimal repro; legacy guard exempted them."""
    assert len(_ISSUE_1375_BOTH_GE1_EXPORT_ROWS) == 2
    for row in _ISSUE_1375_BOTH_GE1_EXPORT_ROWS:
        ref, res = row["reference_price"], row["resolved_price"]
        assert not _legacy_price_unit_mismatch(ref, res)
        assert is_price_unit_mismatch(ref, res)
    assert is_price_unit_mismatch(0.00311, 0.63078)


def test_committed_price_cache_gradeable_subnet_collapse(monkeypatch):
    """#1375 derived refusal is gated: default off matches cache; flag on collapses.

    Default-off gradeable count tracks subnets_with_any_candles (Joshua-approved
    gated rollout per #1375); do not flip REFUSE_DERIVED_FOR_GRADING default to on
    without explicit approval.

    Re-run: ``PYTHONPATH=. python scripts/issue_1375_integrity_impact.py``.
    """
    import json
    from pathlib import Path

    from scripts.issue_1375_integrity_impact import (
        gradeable_subnet_counts,
        subnets_with_any_candles,
    )

    cache_path = Path("data/price_cache.json")
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    with_candles = subnets_with_any_candles(cache)
    assert with_candles > 0

    monkeypatch.delenv("REFUSE_DERIVED_FOR_GRADING", raising=False)
    from internal.council.price_reference import refuse_derived_for_grading_enabled

    assert not refuse_derived_for_grading_enabled()
    flag_off = gradeable_subnet_counts(
        cache, refuse_derived=refuse_derived_for_grading_enabled()
    )
    assert flag_off == with_candles

    monkeypatch.setenv("REFUSE_DERIVED_FOR_GRADING", "on")
    assert refuse_derived_for_grading_enabled()
    flag_on = gradeable_subnet_counts(
        cache, refuse_derived=refuse_derived_for_grading_enabled()
    )
    assert flag_on < flag_off
    assert flag_on == 0


def test_phantom_vwap_quarantine_window():
    from internal.council.grading import is_phantom_vwap_quarantine, is_excluded_from_learning_eval

    row = {
        "price_source": "vwap",
        "created_at": "2026-08-10T12:00:00Z",
        "reference_price": 0.003,
        "resolved_price": 0.63,
        "correct": True,
    }
    assert is_phantom_vwap_quarantine(row)
    assert is_excluded_from_learning_eval(row)
    after = {**row, "created_at": "2026-08-20T00:00:00Z"}
    assert not is_phantom_vwap_quarantine(after)


def test_price_reference_rejects_untagged_geckoterminal_cache():
    from datetime import datetime, timezone

    from internal.council.price_reference import price_at_resolve_at

    resolve_at = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    usd_close = 80.0
    cache = {
        "1": {
            "source": "geckoterminal",
            "candles": [
                {
                    "timestamp": resolve_at.isoformat(),
                    "open": usd_close,
                    "high": usd_close,
                    "low": usd_close,
                    "close": usd_close,
                    "volume": 100.0,
                }
            ],
        }
    }
    status, price, _meta = price_at_resolve_at(1, resolve_at, cache=cache)
    assert status == "ungradeable"
    assert price == 0.0


def test_state_vector_rejects_untagged_geckoterminal_cache(monkeypatch):
    from internal.council import state_vector

    legacy = {
        "source": "geckoterminal",
        "candles": [
            {
                "timestamp": "2026-10-01T12:00:00+00:00",
                "open": 80.0,
                "high": 80.0,
                "low": 80.0,
                "close": 80.0,
                "volume": 1.0,
            }
        ],
    }
    monkeypatch.setattr(state_vector, "_load_price_cache", lambda: {"1": legacy})
    hist = state_vector._get_price_history(1, {}, allow_hydration=False)
    assert hist["closes"] == []


def test_derived_candle_cache_refused_for_grading(monkeypatch):
    from datetime import datetime, timezone

    from internal.council.price_reference import price_at_resolve_at

    monkeypatch.setenv("REFUSE_DERIVED_FOR_GRADING", "on")
    resolve_at = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    cache = {
        "1": {
            "source": "taomarketcap_derived",
            "candles": [
                {
                    "timestamp": resolve_at.isoformat(),
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "volume": 100.0,
                }
            ],
        }
    }
    status, price, meta = price_at_resolve_at(1, resolve_at, cache=cache)
    assert status == "ungradeable"
    assert price == 0.0
    assert meta.get("ungradeable_reason") == "derived_candle_source"


def test_derived_candle_cache_allowed_when_refuse_flag_off(monkeypatch):
    from datetime import datetime, timezone

    from internal.council.price_reference import price_at_resolve_at

    monkeypatch.delenv("REFUSE_DERIVED_FOR_GRADING", raising=False)
    resolve_at = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    cache = {
        "1": {
            "source": "taomarketcap_derived",
            "candles": [
                {
                    "timestamp": resolve_at.isoformat(),
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "volume": 100.0,
                }
            ],
        }
    }
    status, price, _meta = price_at_resolve_at(1, resolve_at, cache=cache)
    assert status == "ok"
    assert price == 1.0


def test_compute_stats_excludes_learning_eval_rows():
    """Trust stats gradable must match learning/eval exclusion (unit + phantom)."""
    row = {
        "outcome": "hit",
        "correct": True,
        "reference_price": 1.5,
        "resolved_price": 285.0,
        "price_source": "vwap",
        "created_at": "2026-08-10T12:00:00Z",
    }
    stats = _compute_stats({"predictions": [], "resolved": [row]})
    assert stats["correct"] == 0
    assert stats["wrong"] == 0


def test_mismatched_resolution_is_ungradeable_without_learning_side_effects():
    prediction = {
        "id": "unit-mismatch",
        "netuid": 1,
        "reference_price": 0.006,
        "resolve_at": datetime.now(timezone.utc).isoformat(),
        "predicted_pct": -0.4,
        "direction": "down",
    }

    resolved = resolve_prediction(prediction, current_price=1.3)

    assert resolved["outcome"] == "ungradeable"
    assert resolved["retirement_reason"] == "price_unit_mismatch"
    assert resolved["correct"] is None
    stats = _compute_stats({"predictions": [], "resolved": [resolved]})
    assert stats["correct"] == 0
    assert stats["wrong"] == 0


def test_lookup_prefers_same_unit_live_over_mismatched_vwap(monkeypatch):
    """Going forward: don't grade VWAP in a different unit when live matches ref."""
    now = datetime.now(timezone.utc)
    resolve_at = now - timedelta(minutes=5)
    prediction = {
        "id": "same-unit-salvage",
        "netuid": 24,
        "reference_price": 0.00374,
        "resolve_at": resolve_at.isoformat().replace("+00:00", "Z"),
        "predicted_pct": 2.3,
        "direction": "up",
    }

    monkeypatch.setattr(
        "internal.council.resolver.price_at_resolve_at",
        lambda *args, **kwargs: (
            "ok",
            0.79476,
            {"price_source": "vwap", "candles_in_window": 1},
        ),
    )
    status, price, meta = lookup_horizon_price(
        prediction,
        resolve_at=resolve_at,
        now=now,
        live_prices={24: 0.00399},
    )
    assert status == "ok"
    assert abs(price - 0.00399) < 1e-9
    assert meta["price_source"] == "live_oracle"
    assert meta.get("rejected_price_source") == "vwap"


def test_sub_one_vwap_mismatch_is_ungradeable_when_live_unavailable(monkeypatch):
    now = datetime.now(timezone.utc)
    resolve_at = now - timedelta(minutes=5)
    prediction = {
        "id": "sub-one-mismatch",
        "netuid": 65,
        "reference_price": 0.00311,
        "resolve_at": resolve_at.isoformat().replace("+00:00", "Z"),
        "predicted_pct": 13.85,
        "direction": "up",
    }
    monkeypatch.setattr(
        "internal.council.resolver.price_at_resolve_at",
        lambda *args, **kwargs: (
            "ok",
            0.63078,
            {"price_source": "vwap", "candles_in_window": 1},
        ),
    )
    status, price, _meta = lookup_horizon_price(
        prediction, resolve_at=resolve_at, now=now, live_prices={}
    )
    assert status == "ungradeable"
    assert price == 0.0
    resolved = resolve_prediction(prediction, current_price=0.63078)
    assert resolved["outcome"] == "ungradeable"
    assert resolved["retirement_reason"] == "price_unit_mismatch"


def test_pump_recover_finalize_rejects_unit_mismatch():
    from internal.learning.pump_lead_recover import _finalize_grade

    now = datetime.now(timezone.utc)
    out = _finalize_grade(
        {
            "id": "pump-mismatch",
            "pick_source": "pump_lead",
            "reference_price": 0.00311,
            "predicted_pct": 2.0,
            "direction": "up",
        },
        price=0.63078,
        meta={"price_source": "vwap"},
        resolve_at=now,
    )
    assert out["outcome"] == "ungradeable"
    assert out.get("ungradeable_reason") == "price_unit_mismatch"
    assert out["correct"] is None

