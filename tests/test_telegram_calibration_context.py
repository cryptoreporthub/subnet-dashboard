"""A cycle-level calibration context must give the same answer as the per-subnet call, built once."""

import pytest

from internal.message_intel import calibration
from tests.test_telegram_evidence_calibration import _row


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION", "on")
    monkeypatch.setenv("TELEGRAM_EVIDENCE_CALIBRATION_MIN_SAMPLES", "4")


def _rows():
    rows = [_row(i, author=f"a{i}", netuid=7) for i in range(1, 7)]
    rows += [_row(i + 20, author=f"b{i}", direction="down", outcome="dump", netuid=9) for i in range(1, 5)]
    rows += [_row(40, author="c", netuid=11)]
    return rows


def test_context_result_equals_per_subnet_result(enabled, monkeypatch):
    rows = _rows()
    monkeypatch.setattr(calibration, "_conviction_rows", lambda db=None: rows)
    ctx = calibration.build_calibration_context()
    for netuid in (7, 9, 11, 13, "not-a-number"):
        assert calibration.calibration_for_subnet(netuid, context=ctx) == calibration.calibration_for_subnet(netuid)


def test_context_loads_rows_and_health_once_for_many_subnets(enabled, monkeypatch):
    calls = {"rows": 0, "health": 0}
    rows = _rows()

    def counting_rows(db=None):
        calls["rows"] += 1
        return rows

    real_health = calibration.calibration_health

    def counting_health(**kwargs):
        calls["health"] += 1
        return real_health(**kwargs)

    monkeypatch.setattr(calibration, "_conviction_rows", counting_rows)
    monkeypatch.setattr(calibration, "calibration_health", counting_health)
    ctx = calibration.build_calibration_context()
    for netuid in range(1, 166):
        calibration.calibration_for_subnet(netuid, context=ctx)
    assert calls == {"rows": 1, "health": 1}, "per-subnet calls must not reload rows or recompute health"


def test_snapshot_cycle_builds_the_context_once(monkeypatch):
    from internal.council import score_snapshots as snaps

    built = {"n": 0}
    real = calibration.build_calibration_context

    def counting(**kwargs):
        built["n"] += 1
        return real(conviction_rows=[])

    monkeypatch.setattr(calibration, "build_calibration_context", counting)
    monkeypatch.setattr("internal.pump.state.load_state", lambda path=None: {"subnets": {}})
    subnets = [
        {"netuid": n, "name": f"SN{n}", "price": 1.0, "volume": 5000.0, "price_change_24h": 1.0}
        for n in range(1, 9)
    ]
    out = snaps.build_full_universe_snapshot(subnets, {}, score_hour=False)
    assert len(out["day"]) == 8
    assert built["n"] == 1
