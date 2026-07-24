"""Production stability guards — pump scan lock + cache-only sparklines."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

from internal.analytics.root_context import spark_closes_cached_only
from internal.pump.state import load_state, scan_all_subnets


def test_spark_closes_cached_only_skips_lazy_fill(monkeypatch):
    with patch("internal.council.state_vector._lazy_fill_price_candles") as lazy:
        spark_closes_cached_only({"netuid": 29})
        lazy.assert_not_called()


def test_scan_all_subnets_fetch_outside_state_lock(tmp_path, monkeypatch):
    """load_state must not block for the full signal fetch (Fly wedge fix)."""
    state_path = str(tmp_path / "pump_ladder.json")
    monkeypatch.setenv("PUMP_LADDER_STATE_PATH", state_path)
    from internal.pump import constants

    monkeypatch.setattr(constants, "STATE_PATH", state_path)

    fetch_started = threading.Event()
    release_fetch = threading.Event()

    def slow_fetch():
        fetch_started.set()
        release_fetch.wait(timeout=2.0)
        return [
            {
                "netuid": 29,
                "name": "Coldint",
                "buy_ratio": 0.6,
                "volume_intensity": 0.4,
                "price_change_24h": 1.0,
                "price_change_1h": 0.5,
            }
        ]

    with patch("internal.pump.state.fetch_all_subnet_signals", side_effect=slow_fetch):
        with patch("internal.pump.state.apply_phase_transitions", return_value={}):
            t = threading.Thread(target=scan_all_subnets, daemon=True)
            t.start()
            assert fetch_started.wait(timeout=2.0)
            t0 = time.monotonic()
            load_state()
            assert time.monotonic() - t0 < 0.25
            release_fetch.set()
            t.join(timeout=3.0)
            assert not t.is_alive()
