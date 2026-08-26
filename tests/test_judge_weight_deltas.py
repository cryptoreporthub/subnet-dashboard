"""Judge weight deltas for Council Hero jury-move panel."""

from internal.learning.weight_deltas import (
    count_weight_trail_updates,
    recent_judge_weight_deltas,
)


def test_recent_judge_weight_deltas_filters_judges(monkeypatch):
    def fake_events(limit):
        return [
            {
                "event_type": "weight_change",
                "judge": "oracle",
                "evidence": {"delta": 0.02, "dial": "oracle"},
            },
            {
                "event_type": "weight_change",
                "judge": "quant",
                "evidence": {"delta": 0.05, "dial": "quant"},
            },
            {
                "event_type": "weight_change",
                "judge": "pulse",
                "evidence": {"delta": -0.02, "dial": "pulse"},
            },
        ]

    monkeypatch.setattr(
        "internal.learning.mindmap_aggregator.collect_trail_events",
        fake_events,
    )
    deltas = recent_judge_weight_deltas()
    assert deltas == {"oracle": 0.02, "pulse": -0.02}
    assert "quant" not in deltas


def test_recent_judge_weight_deltas_latest_delta_wins(monkeypatch):
    """Trail is oldest-first; the newest row per judge must win."""

    def fake_events(limit):
        return [
            {
                "event_type": "weight_change",
                "judge": "oracle",
                "evidence": {"delta": 0.02, "dial": "oracle"},
            },
            {
                "event_type": "weight_change",
                "judge": "oracle",
                "evidence": {"delta": -0.015, "dial": "oracle"},
            },
        ]

    monkeypatch.setattr(
        "internal.learning.mindmap_aggregator.collect_trail_events",
        fake_events,
    )
    assert recent_judge_weight_deltas() == {"oracle": -0.015}


def test_recent_judge_weight_deltas_default_window_covers_full_trail():
    """Persisted trail caps at 200 rows; default scan window must exceed it."""
    from internal.learning.weight_deltas import _TRAIL_SCAN_LIMIT

    assert _TRAIL_SCAN_LIMIT > 200


def test_count_weight_trail_updates_counts_valid_events_only(monkeypatch):
    """Canonical emit_weight_change event_type is weight_change; aliases normalize.

    Event count across expert, judge, impact_strength, and signal dials.
    Alignment diagnostics, zero-delta, and malformed rows are excluded.
    """
    monkeypatch.setattr(
        "internal.learning.weight_deltas.collect_weight_trail_events",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("counter must not collect")),
    )
    events = [
        {
            "event_type": "weight_change",
            "judge": "hype",
            "evidence": {"delta": -0.03, "dial": "hype", "before": 1.0, "after": 0.97},
        },
        {
            "event_type": "weight_change",
            "judge": "oracle",
            "evidence": {"delta": 0.02, "dial": "oracle", "before": 1.0, "after": 1.02},
        },
        {
            "event_type": "weight_change",
            "judge": "impact_strength",
            "evidence": {
                "delta": 0.02,
                "dial": "impact_strength",
                "before": 1.0,
                "after": 1.02,
            },
        },
        {
            "event_type": "weight_change",
            "judge": "hour:rsi_crossover",
            "evidence": {
                "delta": 0.02,
                "dial": "hour:rsi_crossover",
                "before": 1.0,
                "after": 1.02,
            },
        },
        {
            "event_type": "weight_nudge_up",
            "judge": "quant",
            "evidence": {"delta": 0.02, "dial": "quant", "before": 1.0, "after": 1.02},
        },
        {
            "event_type": "weight_change",
            "judge": "hype",
            "decision": "alignment_hold",
            "evidence": {"delta": 0.01, "dial": "hype", "outcome_weight_changed": False},
        },
        {
            "event_type": "weight_change",
            "judge": "pulse",
            "evidence": {"delta": 0.0, "dial": "pulse", "before": 1.0, "after": 1.0},
        },
        {"event_type": "weight_change", "judge": "echo", "evidence": "bad"},
        {"event_type": "prediction_resolved", "decision": "weight_nudge_up"},
        "not-a-row",
    ]
    assert count_weight_trail_updates(events) == 5
    assert count_weight_trail_updates([]) == 0
    assert count_weight_trail_updates(None) == 0
