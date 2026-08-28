"""Pump desk trust.ready gate — pump_ladder liveness + signal snapshot honesty."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from internal.liveness import LivenessTracker
from internal.pump.desk_payload import (
    _signal_snapshot_stale,
    attach_pump_freshness,
    gate_pump_desk_trust,
)


def _ok_liveness_tracker() -> LivenessTracker:
    tracker = LivenessTracker("pump_ladder", interval_seconds=60, persist=False)
    tracker.start()
    tracker.record_success(evidence={"scanned": 1, "op": "pump_ladder_scan"})
    return tracker


def _trust_payload(*, ready: bool = True) -> dict:
    return {
        "status": "success",
        "count": 1,
        "alerts": [{"netuid": 12, "timing": "lead"}],
        "trust": {
            "ready": ready,
            "line": "Early alerts: 62% hit 2%+ in 1h (n=12)",
            "headline_pct": 62,
            "headline_n": 12,
        },
    }


def test_signal_snapshot_stale_matches_pump_alert_semantics():
    assert _signal_snapshot_stale({}) is True
    assert _signal_snapshot_stale({"buy_ratio": 0.5, "volume_intensity": 1.0}) is True
    assert _signal_snapshot_stale({"buy_ratio": 0.5, "volume_intensity": 0.0}) is True
    assert _signal_snapshot_stale({"buy_ratio": 0.62, "volume_intensity": 0.25}) is False


@pytest.mark.parametrize(
    "status",
    ["stale", "failing", "no_success_yet", "starved"],
)
def test_trust_ready_false_when_pump_ladder_liveness_not_ok(monkeypatch, status):
    snap = {"name": "pump_ladder", "status": status, "status_reason": f"test-{status}"}
    tracker = MagicMock()
    tracker.snapshot.return_value = snap
    monkeypatch.setattr("internal.liveness.get_tracker", lambda name: tracker if name == "pump_ladder" else None)
    monkeypatch.setattr(
        "internal.pump.desk_payload._ladder_signal_snapshots_untrustworthy",
        lambda: False,
    )

    out = gate_pump_desk_trust(_trust_payload(ready=True))
    assert out["trust"]["ready"] is False
    assert out["trust"]["liveness"]["status"] == status


def test_trust_ready_false_when_tracker_missing(monkeypatch):
    monkeypatch.setattr("internal.liveness.get_tracker", lambda _name: None)
    monkeypatch.setattr(
        "internal.pump.desk_payload._ladder_signal_snapshots_untrustworthy",
        lambda: False,
    )

    out = gate_pump_desk_trust(_trust_payload(ready=True))
    assert out["trust"]["ready"] is False
    assert out["trust"]["liveness"]["status"] == "no_success_yet"


def test_trust_ready_true_only_when_liveness_ok_and_stats_ready(monkeypatch):
    tracker = _ok_liveness_tracker()
    monkeypatch.setattr("internal.liveness.get_tracker", lambda name: tracker if name == "pump_ladder" else None)
    monkeypatch.setattr(
        "internal.pump.desk_payload._ladder_signal_snapshots_untrustworthy",
        lambda: False,
    )

    out = gate_pump_desk_trust(_trust_payload(ready=True))
    assert out["trust"]["ready"] is True
    assert "liveness" not in out["trust"]


def test_trust_ready_false_when_stats_not_ready_even_if_liveness_ok(monkeypatch):
    tracker = _ok_liveness_tracker()
    monkeypatch.setattr("internal.liveness.get_tracker", lambda name: tracker if name == "pump_ladder" else None)
    monkeypatch.setattr(
        "internal.pump.desk_payload._ladder_signal_snapshots_untrustworthy",
        lambda: False,
    )

    out = gate_pump_desk_trust(_trust_payload(ready=False))
    assert out["trust"]["ready"] is False


def test_trust_ready_false_when_placeholder_signal_snapshots(monkeypatch):
    tracker = _ok_liveness_tracker()
    monkeypatch.setattr("internal.liveness.get_tracker", lambda name: tracker if name == "pump_ladder" else None)
    monkeypatch.setattr(
        "internal.pump.desk_payload._ladder_signal_snapshots_untrustworthy",
        lambda: True,
    )

    out = gate_pump_desk_trust(_trust_payload(ready=True))
    assert out["trust"]["ready"] is False
    assert out["trust"]["signal_snapshots_stale"] is True


def test_attach_pump_freshness_applies_trust_gate(monkeypatch):
    tracker = _ok_liveness_tracker()
    monkeypatch.setattr("internal.liveness.get_tracker", lambda name: tracker if name == "pump_ladder" else None)
    monkeypatch.setattr(
        "internal.pump.desk_payload._ladder_signal_snapshots_untrustworthy",
        lambda: False,
    )

    out = attach_pump_freshness(_trust_payload(ready=True))
    assert out["freshness"] == "fresh"
    assert out["trust"]["ready"] is True


def test_ladder_placeholder_snapshots_detected_from_state(monkeypatch, tmp_path):
    from internal.pump import constants

    state_path = tmp_path / "pump_ladder.json"
    state_path.write_text(
        '{"subnets": {"12": {"netuid": 12, "phase": "ACCUMULATING", '
        '"signal_snapshot": {"buy_ratio": 0.5, "volume_intensity": 1.0}}}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("PUMP_LADDER_STATE_PATH", str(state_path))
    monkeypatch.setattr(constants, "STATE_PATH", str(state_path))

    from internal.pump.desk_payload import _ladder_signal_snapshots_untrustworthy

    assert _ladder_signal_snapshots_untrustworthy() is True
