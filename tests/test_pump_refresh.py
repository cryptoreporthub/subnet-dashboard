"""Pump ladder freshness tests."""

from __future__ import annotations

import threading
from unittest.mock import patch

from internal.pump.refresh import ensure_ladder_fresh, kick_ladder_fresh, ladder_age_minutes
from internal.pump.state import save_state as pump_save_state


def test_ensure_ladder_fresh_skips_when_recent(tmp_path, monkeypatch):
    state_path = str(tmp_path / "pump_ladder.json")
    monkeypatch.setenv("PUMP_LADDER_STATE_PATH", state_path)
    monkeypatch.setenv("PUMP_LADDER_STALE_MINUTES", "30")
    from internal.pump import constants

    monkeypatch.setattr(constants, "STATE_PATH", state_path)
    pump_save_state(
        {
            "subnets": {},
            "meta": {"last_scan_at": "2099-01-01T00:00:00Z"},
        }
    )
    with patch("internal.pump.state.scan_all_subnets") as scan:
        assert ensure_ladder_fresh() is False
        scan.assert_not_called()


def test_ensure_ladder_fresh_scans_when_stale(tmp_path, monkeypatch):
    state_path = str(tmp_path / "pump_ladder.json")
    monkeypatch.setenv("PUMP_LADDER_STATE_PATH", state_path)
    monkeypatch.setenv("PUMP_LADDER_STALE_MINUTES", "1")
    monkeypatch.setenv("PUMP_LADDER_SCAN_COOLDOWN_SECONDS", "0")
    from internal.pump import constants
    import internal.pump.refresh as refresh_mod

    monkeypatch.setattr(constants, "STATE_PATH", state_path)
    refresh_mod._last_scan_attempt = 0.0
    pump_save_state({"subnets": {}, "meta": {"last_scan_at": "2020-01-01T00:00:00Z"}})
    with patch(
        "internal.pump.state.scan_all_subnets",
        return_value={"ok": True, "scanned": 10, "transitions": []},
    ) as scan:
        assert ensure_ladder_fresh(force=True) is True
        scan.assert_called_once()


def test_kick_ladder_fresh_starts_background(monkeypatch):
    import time

    import internal.pump.refresh as refresh_mod

    # Exercise the real thread path (pytest normally disables kicks).
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("DISABLE_BACKGROUND_SCANS", raising=False)
    refresh_mod._last_scan_attempt = 0.0
    called = []

    def fake_run():
        called.append(True)
        return True

    monkeypatch.setattr(refresh_mod, "_run_ladder_scan", fake_run)
    monkeypatch.setattr(refresh_mod, "_needs_scan", lambda force=False: True)
    out = kick_ladder_fresh(force=True)
    assert out["status"] == "started"
    for _ in range(50):
        if called:
            break
        time.sleep(0.02)
    assert called


def test_kick_ladder_fresh_skips_under_pytest(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_pump_refresh.py::x")
    out = kick_ladder_fresh(force=True)
    assert out["status"] == "skipped"
    assert out["reason"] == "background_disabled"


def test_fetch_all_subnet_signals_loads_intel_maps_once(monkeypatch):
    from unittest.mock import MagicMock

    import internal.pump.signals as sig

    chatter_calls = 0
    scenario_calls = 0

    def chatter():
        nonlocal chatter_calls
        chatter_calls += 1
        return {1: 0.5}

    def scenario():
        nonlocal scenario_calls
        scenario_calls += 1
        return {1: "tag"}

    monkeypatch.setattr(sig, "message_intel_chatter_by_netuid", chatter)
    monkeypatch.setattr(sig, "scenario_tags_by_netuid", scenario)
    monkeypatch.setattr(
        "internal.pump.taostats_overlay.load_subnets_for_pump_signals",
        lambda: [{"netuid": 1, "name": "A"}, {"netuid": 2, "name": "B"}],
    )

    rows = sig.fetch_all_subnet_signals()
    assert len(rows) == 2
    assert chatter_calls == 1
    assert scenario_calls == 1


def test_scan_all_subnets_skips_when_already_running(tmp_path, monkeypatch):
    monkeypatch.setenv("PUMP_LADDER_STATE_PATH", str(tmp_path / "pump_ladder.json"))
    from internal.pump import constants

    monkeypatch.setattr(constants, "STATE_PATH", str(tmp_path / "pump_ladder.json"))

    stub_signal = {
        "netuid": 1,
        "name": "A",
        "price_change_24h": 0.05,
        "momentum_1h": 0.01,
        "volume_intensity": 0.3,
        "buy_ratio": 0.6,
        "chatter_intensity": 0,
        "emission": 1.0,
    }

    started = threading.Event()
    release = threading.Event()

    def slow_locked(state=None, signal_rows=None):
        started.set()
        release.wait(timeout=2.0)
        return {"ok": True, "scanned": len(signal_rows or []), "transitions": []}

    import internal.pump.state as pump_state

    with patch(
        "internal.pump.state.fetch_all_subnet_signals",
        return_value=[stub_signal],
    ):
        with patch("internal.pump.state._scan_all_subnets_locked", side_effect=slow_locked):
            t = threading.Thread(target=pump_state.scan_all_subnets, daemon=True)
            t.start()
            assert started.wait(timeout=2.0)
            dup = pump_state.scan_all_subnets()
            assert dup.get("error") == "scan_in_progress"
            release.set()
            t.join(timeout=3.0)


def test_signal_fetch_timeout_does_not_accumulate_workers(monkeypatch):
    import internal.pump.state as pump_state

    release = threading.Event()
    monkeypatch.setenv("PUMP_LADDER_FETCH_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr(
        pump_state,
        "fetch_all_subnet_signals",
        lambda: (release.wait(timeout=2.0) or []),
    )

    assert pump_state._fetch_signal_rows_with_timeout() == []
    assert pump_state._fetch_thread is not None
    assert pump_state._fetch_thread.daemon is True
    assert pump_state._fetch_signal_rows_with_timeout() == []
    release.set()


def test_ladder_age_minutes_missing_meta(tmp_path, monkeypatch):
    state_path = str(tmp_path / "pump_ladder.json")
    monkeypatch.setenv("PUMP_LADDER_STATE_PATH", state_path)
    from internal.pump import constants

    monkeypatch.setattr(constants, "STATE_PATH", state_path)
    pump_save_state({"subnets": {}, "meta": {}})
    assert ladder_age_minutes() is None
