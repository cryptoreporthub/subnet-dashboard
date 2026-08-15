"""Tests for the cold-cache alert added to _compute_stats / COLD_CACHE_ALERT_RATIO."""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolved_row(retirement_reason: str = "genuine_expiry", outcome: str = "expired") -> Dict[str, Any]:
    return {
        "outcome": outcome,
        "correct": None,
        "retirement_reason": retirement_reason,
    }


def _hit_row() -> Dict[str, Any]:
    return {"outcome": "hit", "correct": True}


def _make_data(missing_price: int, total: int) -> Dict[str, Any]:
    """Build a predictions data dict with `missing_price` cold-cache rows out of `total` resolved."""
    resolved: List[Dict[str, Any]] = []
    for _ in range(missing_price):
        resolved.append(_resolved_row("missing_price_at_horizon", "expired"))
    for _ in range(total - missing_price):
        resolved.append(_hit_row())
    return {"predictions": [], "resolved": resolved}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def resolver_mod(monkeypatch):
    """Return the resolver module with side-effects neutralised."""
    import internal.council.resolver as mod
    # Avoid touching any on-disk files or network calls during _compute_stats.
    monkeypatch.setattr(mod, "is_pump_desk_claim", lambda _r: False, raising=False)
    monkeypatch.setattr(mod, "_is_shadow", lambda _r: False, raising=False)
    return mod


# ---------------------------------------------------------------------------
# _compute_stats — threshold semantics
# ---------------------------------------------------------------------------

class TestColdCacheAlertThreshold:
    def test_below_threshold_no_alert(self, resolver_mod, monkeypatch):
        monkeypatch.setattr(resolver_mod, "COLD_CACHE_ALERT_RATIO", 0.05)
        # 4 out of 100 → 4.0% < 5.0%
        stats = resolver_mod._compute_stats(_make_data(4, 100))
        assert stats["cold_cache_alert"] is False
        assert stats["cold_cache_ratio"] == pytest.approx(0.04, abs=1e-6)

    def test_above_threshold_fires_alert(self, resolver_mod, monkeypatch):
        monkeypatch.setattr(resolver_mod, "COLD_CACHE_ALERT_RATIO", 0.05)
        # 6 out of 100 → 6.0% > 5.0%
        stats = resolver_mod._compute_stats(_make_data(6, 100))
        assert stats["cold_cache_alert"] is True
        assert stats["cold_cache_ratio"] == pytest.approx(0.06, abs=1e-6)

    def test_exact_threshold_does_not_fire(self, resolver_mod, monkeypatch):
        monkeypatch.setattr(resolver_mod, "COLD_CACHE_ALERT_RATIO", 0.05)
        # exactly 5% — alert condition is strict > not >=
        stats = resolver_mod._compute_stats(_make_data(5, 100))
        assert stats["cold_cache_alert"] is False

    def test_no_resolved_rows_no_alert(self, resolver_mod, monkeypatch):
        monkeypatch.setattr(resolver_mod, "COLD_CACHE_ALERT_RATIO", 0.05)
        stats = resolver_mod._compute_stats({"predictions": [], "resolved": []})
        assert stats["cold_cache_alert"] is False
        assert stats["cold_cache_ratio"] is None

    def test_raw_ratio_used_not_rounded(self, resolver_mod, monkeypatch):
        """Rounding artefact: 5_003 / 100_000 rounds to 0.0500 but raw is 0.05003."""
        monkeypatch.setattr(resolver_mod, "COLD_CACHE_ALERT_RATIO", 0.05)
        stats = resolver_mod._compute_stats(_make_data(5_003, 100_000))
        # Raw ratio is 0.05003 > 0.05 → should alert even though rounded is 0.0500
        assert stats["cold_cache_alert"] is True

    def test_all_missing_price_fires_alert(self, resolver_mod, monkeypatch):
        monkeypatch.setattr(resolver_mod, "COLD_CACHE_ALERT_RATIO", 0.05)
        stats = resolver_mod._compute_stats(_make_data(10, 10))
        assert stats["cold_cache_alert"] is True
        assert stats["cold_cache_ratio"] == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# _parse_cold_cache_alert_ratio — invalid configuration
# ---------------------------------------------------------------------------

class TestParseAlertRatio:
    def _parse(self, mod, raw: str) -> float:
        return mod._parse_cold_cache_alert_ratio(raw)

    def test_valid_ratio(self, resolver_mod):
        assert self._parse(resolver_mod, "0.10") == pytest.approx(0.10)

    def test_zero_is_valid(self, resolver_mod):
        assert self._parse(resolver_mod, "0") == pytest.approx(0.0)

    def test_one_is_valid(self, resolver_mod):
        assert self._parse(resolver_mod, "1") == pytest.approx(1.0)

    def test_none_returns_default(self, resolver_mod):
        result = self._parse(resolver_mod, None)
        assert result == pytest.approx(resolver_mod._COLD_CACHE_ALERT_RATIO_DEFAULT)

    def test_empty_string_returns_default(self, resolver_mod):
        result = self._parse(resolver_mod, "")
        assert result == pytest.approx(resolver_mod._COLD_CACHE_ALERT_RATIO_DEFAULT)

    def test_nan_falls_back_to_default(self, resolver_mod, caplog):
        with caplog.at_level(logging.WARNING, logger="internal.council.resolver"):
            result = self._parse(resolver_mod, "nan")
        assert result == pytest.approx(resolver_mod._COLD_CACHE_ALERT_RATIO_DEFAULT)
        assert any("COLD_CACHE_ALERT_RATIO" in r.message for r in caplog.records)

    def test_inf_falls_back_to_default(self, resolver_mod, caplog):
        with caplog.at_level(logging.WARNING, logger="internal.council.resolver"):
            result = self._parse(resolver_mod, "inf")
        assert result == pytest.approx(resolver_mod._COLD_CACHE_ALERT_RATIO_DEFAULT)

    def test_negative_falls_back_to_default(self, resolver_mod, caplog):
        with caplog.at_level(logging.WARNING, logger="internal.council.resolver"):
            result = self._parse(resolver_mod, "-0.01")
        assert result == pytest.approx(resolver_mod._COLD_CACHE_ALERT_RATIO_DEFAULT)

    def test_above_one_falls_back_to_default(self, resolver_mod, caplog):
        with caplog.at_level(logging.WARNING, logger="internal.council.resolver"):
            result = self._parse(resolver_mod, "1.5")
        assert result == pytest.approx(resolver_mod._COLD_CACHE_ALERT_RATIO_DEFAULT)

    def test_non_numeric_falls_back_to_default(self, resolver_mod, caplog):
        with caplog.at_level(logging.WARNING, logger="internal.council.resolver"):
            result = self._parse(resolver_mod, "bad_value")
        assert result == pytest.approx(resolver_mod._COLD_CACHE_ALERT_RATIO_DEFAULT)


# ---------------------------------------------------------------------------
# Warning emission during resolve_due_predictions
# ---------------------------------------------------------------------------

class TestWarningEmission:
    def test_warning_logged_when_alert_fires(self, resolver_mod, monkeypatch, caplog, tmp_path):
        """resolve_due_predictions must log a WARNING when cold_cache_alert is True."""
        monkeypatch.setattr(resolver_mod, "COLD_CACHE_ALERT_RATIO", 0.05)

        # _compute_stats will return alert=True when we fake stats output
        alert_stats = {
            "cold_cache_alert": True,
            "cold_cache_ratio": 0.10,
            "price_data_unavailable": 5,
            "correct": 0, "wrong": 0, "expired": 0, "expired_genuine": 0,
            "ungradeable": 0, "duplicate": 0, "pending": 0, "council_pending": 0,
            "pump_pending": 0, "total_pending": 0, "total": 10, "shadow_graded": 0,
            "accuracy": 0.0, "historical_hydration_ungradeable": 0,
        }
        monkeypatch.setattr(resolver_mod, "_compute_stats", lambda _d: alert_stats)
        monkeypatch.setattr(resolver_mod, "_load_json", lambda *a, **kw: {
            "predictions": [], "resolved": [], "stats": {},
        })
        monkeypatch.setattr(resolver_mod, "_save_json", lambda *a, **kw: None)
        monkeypatch.setattr(resolver_mod, "check_resolver_watchdog", lambda *a, **kw: {})
        monkeypatch.setattr(resolver_mod, "dedupe_predictions", lambda p, **kw: (p, []))
        monkeypatch.setattr(resolver_mod, "_restore_recently_expired_predictions", lambda *a, **kw: [])
        monkeypatch.setattr(resolver_mod, "regrade_expired_predictions", lambda **kw: {
            "ledger_mutated": False, "attempted": 0, "regraded": 0,
        })
        monkeypatch.setattr(resolver_mod, "fetch_prices", lambda *a, **kw: {})
        monkeypatch.setattr(resolver_mod, "hydrate_candles_for_netuid", lambda *a, **kw: None, raising=False)
        try:
            monkeypatch.setattr(resolver_mod, "emit_accuracy_update", lambda **kw: None, raising=False)
        except Exception:
            pass

        with caplog.at_level(logging.WARNING, logger="internal.council.resolver"):
            resolver_mod.resolve_due_predictions()

        warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("Cold-cache alert" in m for m in warning_msgs), (
            f"Expected 'Cold-cache alert' in WARNING logs; got: {warning_msgs}"
        )

    def test_no_warning_when_alert_not_fired(self, resolver_mod, monkeypatch, caplog):
        """No cold-cache WARNING when the ratio is below threshold."""
        monkeypatch.setattr(resolver_mod, "COLD_CACHE_ALERT_RATIO", 0.05)

        safe_stats = {
            "cold_cache_alert": False,
            "cold_cache_ratio": 0.01,
            "price_data_unavailable": 1,
            "correct": 0, "wrong": 0, "expired": 0, "expired_genuine": 0,
            "ungradeable": 0, "duplicate": 0, "pending": 0, "council_pending": 0,
            "pump_pending": 0, "total_pending": 0, "total": 100, "shadow_graded": 0,
            "accuracy": 0.0, "historical_hydration_ungradeable": 0,
        }
        monkeypatch.setattr(resolver_mod, "_compute_stats", lambda _d: safe_stats)
        monkeypatch.setattr(resolver_mod, "_load_json", lambda *a, **kw: {
            "predictions": [], "resolved": [], "stats": {},
        })
        monkeypatch.setattr(resolver_mod, "_save_json", lambda *a, **kw: None)
        monkeypatch.setattr(resolver_mod, "check_resolver_watchdog", lambda *a, **kw: {})
        monkeypatch.setattr(resolver_mod, "dedupe_predictions", lambda p, **kw: (p, []))
        monkeypatch.setattr(resolver_mod, "_restore_recently_expired_predictions", lambda *a, **kw: [])
        monkeypatch.setattr(resolver_mod, "regrade_expired_predictions", lambda **kw: {
            "ledger_mutated": False, "attempted": 0, "regraded": 0,
        })
        monkeypatch.setattr(resolver_mod, "fetch_prices", lambda *a, **kw: {})
        monkeypatch.setattr(resolver_mod, "hydrate_candles_for_netuid", lambda *a, **kw: None, raising=False)

        with caplog.at_level(logging.WARNING, logger="internal.council.resolver"):
            resolver_mod.resolve_due_predictions()

        cold_cache_warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING and "Cold-cache alert" in r.message
        ]
        assert cold_cache_warnings == []
