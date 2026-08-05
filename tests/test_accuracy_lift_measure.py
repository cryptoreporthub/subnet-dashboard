"""Slice 7a PREP — accuracy_lift on ops evidence (read-only)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from internal.accuracy_lift.measure import build_accuracy_lift_snapshot, row_hit
from internal.ops.evidence import build_evidence_report


def _recent_row(*, correct: bool, expert: str = "quant", days_ago: float = 1.0, **extra) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    row = {
        "id": f"row-{expert}-{days_ago}",
        "netuid": 11,
        "created_at": ts,
        "resolved_at": ts,
        "correct": correct,
        "actual_pct": 2.0 if correct else -1.0,
        "expert": expert,
        "pick_source": "council",
    }
    row.update(extra)
    return row


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
    assert "attribution_quality" in block
    assert "published_only" in block
    assert "council_trust" in block
    assert "full_ledger" in block
    assert "by_pick_source" in block
    assert "by_pick_source_30d" in block
    assert "by_horizon_30d" in block
    assert "population" in block
    assert "note" in block
    assert "attribution_quality" in report


def test_accuracy_lift_honest_empty_when_no_graded_rows():
    block = build_accuracy_lift_snapshot(rows=[])
    assert block["data_available"] is False
    assert block["graded_7d"] == 0
    assert block["graded_30d"] == 0
    assert block["hit_rate_7d"] is None
    assert block["hit_rate_30d"] is None
    assert block["by_expert"] == {}
    assert block["full_ledger"]["graded_30d"] == 0
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
    assert block["published_only"]["graded_30d"] == 3
    assert block["note"] == (
        "mixed ledger — includes HOLD/near-miss shadows + pump-desk claims; see published_only"
    )
    assert block["attribution_quality"]["total"] == 3
    assert block["attribution_quality"]["unknown"] == 0


def test_accuracy_lift_attributes_hot_signal_without_expert_field():
    rows = [
        {
            "id": "hot-1",
            "created_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            "resolved_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            "correct": True,
            "actual_pct": 2.0,
            "signal_impact": {
                "impacts": [{"signal_type": "hot", "magnitude_pct": 4.0, "learned_weight": 1.0}],
            },
        }
    ]
    block = build_accuracy_lift_snapshot(rows=rows)
    assert block["by_expert"]["hype"]["graded"] == 1
    assert block["attribution_quality"]["unknown"] == 0


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
    assert report["accuracy_lift"]["full_ledger"]["graded_30d"] == 0
    assert soul.stat().st_mtime == mtime_before


def rows_ts(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def test_accuracy_lift_population_split():
    rows = [
        _recent_row(correct=True, days_ago=1),
        _recent_row(correct=False, days_ago=2),
        _recent_row(correct=False, days_ago=1, pick_source="pump_lead", actual_pct=1.0),
        _recent_row(correct=True, days_ago=1, pick_source="pump_combined_exp"),
        _recent_row(correct=True, days_ago=1, shadow=True),
        _recent_row(correct=True, days_ago=1, pick_source="council_shadow"),
        {"id": "legacy", "created_at": rows_ts(1), "resolved_at": rows_ts(1), "correct": True},
        {"id": "expired", "created_at": rows_ts(1), "resolved_at": rows_ts(1), "outcome": "expired"},
    ]
    block = build_accuracy_lift_snapshot(rows=rows)
    assert block["population"] == "mixed_all_resolved"
    assert block["graded_30d"] == 7
    assert block["council_trust"]["graded_30d"] == 3
    assert block["published_only"]["graded_30d"] == 3
    assert block["full_ledger"]["graded_30d"] == 7
    buckets = block["by_pick_source"]
    assert buckets["council"]["n"] == 3
    assert buckets["pump_lead"]["n"] == 1
    assert buckets["council_shadow"]["n"] == 2
    source_rows = block["by_pick_source_30d"]
    assert sum(row["n"] for row in source_rows) == 7
    shadow_bucket = next(row for row in source_rows if row["label"] == "shadow")
    assert shadow_bucket["n"] == 2


def test_window_actual_days_and_small_move_miss_share():
    t0 = datetime.now(timezone.utc) - timedelta(days=3)
    t1 = t0 + timedelta(days=1, hours=12)
    rows = [
        {
            "id": "a",
            "pick_source": "council",
            "created_at": t0.isoformat().replace("+00:00", "Z"),
            "resolved_at": t0.isoformat().replace("+00:00", "Z"),
            "correct": False,
            "actual_pct": 0.4,
        },
        {
            "id": "b",
            "pick_source": "council",
            "created_at": t1.isoformat().replace("+00:00", "Z"),
            "resolved_at": t1.isoformat().replace("+00:00", "Z"),
            "correct": False,
            "actual_pct": -1.5,
        },
        {
            "id": "pump",
            "pick_source": "pump_lead",
            "created_at": t1.isoformat().replace("+00:00", "Z"),
            "resolved_at": t1.isoformat().replace("+00:00", "Z"),
            "correct": False,
            "actual_pct": 0.2,
        },
    ]
    block = build_accuracy_lift_snapshot(rows=rows)
    assert block["window_actual_days"]["w30"] == 1.5
    noise = block["small_move_miss_share"]
    assert noise["misses"] == 2
    assert noise["small_move_misses"] == 1
    assert noise["share"] == 0.5


def test_row_hit_fallback_without_stored_correct():
    row = {
        "predicted_pct": 2.0,
        "direction": "up",
        "actual_pct": 1.0,
    }
    assert row_hit(row) is True


def test_trust_banner_uses_full_ledger_context():
    from internal.learning.trust_stats import build_trust_banner

    ledger_context = build_accuracy_lift_snapshot(
        rows=[
            _recent_row(correct=True, days_ago=1),
            _recent_row(correct=False, days_ago=1, pick_source="pump_lead", actual_pct=1.0),
        ]
    )
    banner = build_trust_banner({"correct": 1, "wrong": 0}, ledger_context=ledger_context)
    assert banner["ledger_graded_30d"] == ledger_context["full_ledger"]["graded_30d"]
    assert banner["ledger_hit_rate_30d"] == ledger_context["full_ledger"]["hit_rate_30d"]
    assert banner["ledger_published_graded_30d"] == ledger_context["published_only"]["graded_30d"]
    assert banner["ledger_published_hit_rate_30d"] == ledger_context["published_only"]["hit_rate_30d"]


def test_published_only_matches_resolver_stats():
    from internal.council.resolver import _compute_stats

    rows = [
        _recent_row(correct=True, days_ago=1),
        _recent_row(correct=False, days_ago=2),
        _recent_row(correct=True, days_ago=1, shadow=True),
        _recent_row(correct=False, days_ago=1, pick_source="pump_lead"),
    ]
    stats = _compute_stats({"resolved": rows, "predictions": []})
    block = build_accuracy_lift_snapshot(rows=rows)
    pub = block["published_only"]
    assert pub["graded_30d"] == stats["correct"] + stats["wrong"]
    assert pub["hit_rate_30d"] == round(stats["accuracy"], 4)


def test_by_horizon_30d_splits_hour_and_day():
    rows = [
        _recent_row(correct=True, days_ago=1, horizon_type="hour", horizon_hours=4),
        _recent_row(correct=False, days_ago=1, horizon_type="day", horizon_hours=24),
    ]
    block = build_accuracy_lift_snapshot(rows=rows)
    labels = {row["label"] for row in block["by_horizon_30d"]}
    assert "hour" in labels
    assert "day" in labels


def test_acc1_script_reexports_shared_helpers():
    from scripts import measure_accuracy_archive as script

    assert script.load_archive is not None
    assert script.iter_resolved is not None
    fixture = Path("tests/fixtures/acc1_archive_sample.json")
    data = script.load_archive(str(fixture))
    assert len(script.iter_resolved(data)) == 5
