"""Expiry-ledger fixes - unit tests.

Covers: trust-gate expired-rate on the resolved flow (C), scenario pending
dedupe (D), and epoch reset preserving in-flight pending rows (E).
"""

from __future__ import annotations

import json

import pytest

from internal.learning.trust_stats import build_trust_banner


def test_trust_banner_expired_rate_uses_resolved_flow() -> None:
    banner = build_trust_banner(
        {"correct": 0, "wrong": 0, "expired": 11, "duplicate": 2, "pending": 3, "total": 16}
    )
    assert banner["expired_rate"] == pytest.approx(11 / 13)  # graded+expired+duplicate
    assert banner["expired_total_rate"] == pytest.approx(11 / 16)
    assert banner["graded"] == 0


def test_trust_banner_gate_does_not_block_before_min_sample() -> None:
    banner = build_trust_banner(
        {"correct": 0, "wrong": 0, "expired": 11, "duplicate": 2, "pending": 3, "total": 16}
    )
    assert banner["integrity_gate"]["expired_ok"] is None  # not graded yet
    assert "expired" in (banner["message"] or "")
    assert banner["expired_note"]


def test_scenario_add_dedupes_pending_same_name_regime(monkeypatch) -> None:
    import internal.council.scenario_memory as sm

    data = {"scenarios": [], "regimes": {r: [] for r in sm.REGIMES}, "meta": {}}
    monkeypatch.setattr(sm, "_load", lambda: data)
    monkeypatch.setattr(sm, "_save", lambda d, path=None: None)

    a = sm.add_scenario("Targon", {"price_change_24h": 5.0}, regime="bull")
    b = sm.add_scenario("Targon", {"price_change_24h": 5.0}, regime="bull")
    assert a["id"] == b["id"]
    assert len(data["scenarios"]) == 1


def test_epoch_archive_preserves_pending(monkeypatch, tmp_path) -> None:
    import internal.learning.ledger_heal as lh
    from internal.learning import predictions_store as ps

    captured: dict = {}
    monkeypatch.setattr(ps, "load_predictions", lambda: {
        "predictions": [
            {"id": "p1", "status": "pending", "netuid": 1, "resolve_at": "2099-01-01T00:00:00Z"},
        ],
        "resolved": [{"id": "r1", "status": "resolved", "correct": True}],
        "stats": {"correct": 1, "wrong": 0, "pending": 1, "total": 2, "accuracy": 1.0},
    })
    monkeypatch.setattr(ps, "save_predictions", lambda d: captured.update(data=d))

    res = lh.archive_predictions_epoch(
        predictions_path="unused.json",
        archive_dir=str(tmp_path / "arc"),
        re_heal_daily=False,
    )
    assert res["ok"] is True
    assert captured["data"]["predictions"]  # in-flight row preserved
    assert captured["data"]["resolved"] == []
    assert captured["data"]["stats"]["pending"] == 1
