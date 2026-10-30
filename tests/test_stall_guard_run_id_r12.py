"""PR #1485 R12: identity-less (None, ·) cap continuity; R11 flap regression (MC repro)."""

from __future__ import annotations

import pytest

from internal import loop_stall_guard as g
from tests.test_stall_guard_missing_receipt_wedge import (
    _old_receipt,
    _run_guard,
    _wire,
)

# MC r11-break-repro: r10 killed ~11 checks at interval 240 (~2400s); R11 never in 120.
_R10_WORST_KILL_SECONDS = 2400


# MC r15: frozen ``run_id``/``progress`` None behind flapping probe exits at no-progress
# deadline (outage 3→9, 4→7, 5→8 checks @ 240s). Outage 2 still hits absolute cap (~11).
_DOCUMENTED_FLAP_KILL_CHECKS = {2: 11, 3: 9, 4: 7, 5: 8}


def _documented_flap_kill_bound_checks(outage_every: int) -> int:
    """Exact kill check for hung identity-less write + periodic probe-unknown (incl. 3 strikes)."""
    return _DOCUMENTED_FLAP_KILL_CHECKS[outage_every]


def _flapping_hung_none_none_ticks(*, outage_every: int, ticks: int, monkeypatch, tmp_path):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    monkeypatch.setattr(g, "INTERVAL_SECONDS", 240)
    monkeypatch.setattr(g, "CONSECUTIVE_CHECKS", 3)
    _old_receipt(6001)
    calls = {"n": 0}

    def _tick():
        calls["n"] += 1
        if calls["n"] % outage_every == 0:
            return g.TickProgressSnapshot(None, False)
        return g.TickProgressSnapshot({"token": (None, None)}, True)

    monkeypatch.setattr(g, "_tick_progress", _tick)
    return _run_guard(monkeypatch, ticks=ticks)


@pytest.mark.parametrize("outage_every", [2, 3, 4, 5])
def test_hung_none_none_flapping_probe_exits_within_documented_bound(
    tmp_path, monkeypatch, outage_every
):
    """Port of MC r11-break-repro: hung write-phase (``run_id`` and ``progress`` None) with periodic probe-unknown."""
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    monkeypatch.setattr(g, "INTERVAL_SECONDS", 240)
    monkeypatch.setattr(g, "CONSECUTIVE_CHECKS", 3)
    bound = _documented_flap_kill_bound_checks(outage_every)
    assert bound * g.INTERVAL_SECONDS <= _R10_WORST_KILL_SECONDS + (
        g.CONSECUTIVE_CHECKS * g.INTERVAL_SECONDS
    )
    calls = {"n": 0}

    def _tick():
        calls["n"] += 1
        if calls["n"] % outage_every == 0:
            return g.TickProgressSnapshot(None, False)
        return g.TickProgressSnapshot({"token": (None, None)}, True)

    monkeypatch.setattr(g, "_tick_progress", _tick)
    _old_receipt(6001)
    code, _ = _run_guard(monkeypatch, ticks=bound)
    assert code == 1
    calls["n"] = 0
    code_survive, _ = _run_guard(monkeypatch, ticks=bound - 1)
    assert code_survive is None


def test_new_run_id_after_identity_less_window_gets_full_cap(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(g, "TICK_MAX_BASE_SECONDS", 1200)
    _old_receipt(6001)
    window = 7
    calls = {"n": 0}

    def _controlled():
        calls["n"] += 1
        n = calls["n"]
        if n <= window:
            return g.TickProgressSnapshot(None, False)
        if n == window + 1:
            return g.TickProgressSnapshot({"token": (None, None)}, True)
        step = n - window - 1
        return g.TickProgressSnapshot({"token": ("healthy-b", f"{step}/128")}, True)

    monkeypatch.setattr(g, "_tick_progress", _controlled)
    code, _ = _run_guard(monkeypatch, ticks=window + 6)
    assert code is None
