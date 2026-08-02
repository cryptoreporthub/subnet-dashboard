"""Slice 7a PREP — accuracy_lift on ops evidence (read-only)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from internal.accuracy_lift.measure import build_accuracy_lift_snapshot
from internal.ops.evidence import build_evidence_report


def _recent_row(*, correct: bool, expert: str = "quant", days_ago: float = 1.0) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    return {
        "id": f"row-{expert}-{days_ago}",
        "netuid": 11,
        "created_at": ts,
        "resolved_at": ts,
        "correct": correct,
        "actual_pct": 2.0 if correct else -1.0,
        "expert": expert,
    }


def test_evidence_includes_accuracy_lift():
    report = build_evidence_report()
    assert "accuracy_lift" in report
    block = report["accuracy_lift"]
    assert "data_available" in block
    assert "graded_7d" in block
    assert "graded_30d" in block
    assert "hit_rate_7d" in block
    assert "hit_rate_30d" in block
    assert "by_expert" in block
    assert "note" in block


def test_accuracy_lift_honest_empty_when_no_graded_rows():
    block = build_accuracy_lift_snapshot(rows=[])
    assert block["data_available"] is False
    assert block["graded_7d"] == 0
    assert block["graded_30d"] == 0
    assert block["hit_rate_7d"] is None
    assert block["hit_rate_30d"] is None
    assert block["by_expert"] == {}
    assert block["note"] == "honest empty until graded>0"


def test_accuracy_lift_counts_recent_graded_rows():
    rows = [
        _recent_row(correct=True, expert="quant", days_ago=2),
        _recent_row(correct=False, expert="hype", days_ago=3),
        _recent_row(correct=True, expert="quant", days_ago=20),
    ]
    block = build_accuracy_lift_snapshot(rows=rows)
    assert block["data_available"] is True
    assert block["graded_7d"] == 2
    assert block["graded_30d"] == 3
    assert block["hit_rate_7d"] == 0.5
    assert block["hit_rate_30d"] == round(2 / 3, 4)
    assert block["by_expert"]["quant"]["graded"] == 2
    assert block["by_expert"]["hype"]["graded"] == 1
    assert block["note"] is None


def test_evidence_accuracy_lift_no_weight_writes(monkeypatch, tmp_path):
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"adversarial_state": {"council_weights": {"quant": 1.0}}}), encoding="utf-8")
    mtime_before = soul.stat().st_mtime

    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(
        "internal.accuracy_lift.measure.build_accuracy_lift_snapshot",
        lambda rows=None: build_accuracy_lift_snapshot(rows=[]),
    )

    report = build_evidence_report()
    assert report["accuracy_lift"]["data_available"] is False
    assert soul.stat().st_mtime == mtime_before


def test_acc1_script_reexports_shared_helpers():
    from scripts import measure_accuracy_archive as script

    assert script.load_archive is not None
    assert script.iter_resolved is not None
    fixture = Path("tests/fixtures/acc1_archive_sample.json")
    data = script.load_archive(str(fixture))
    assert len(script.iter_resolved(data)) == 5
