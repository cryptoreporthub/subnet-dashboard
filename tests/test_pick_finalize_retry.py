"""A transient pick-history lock timeout during finalize is retried, not dropped.

Finalize runs after the ledger save. A lock that is busy for a moment should not
cost the pick its outcome, so finalize retries a few times before it gives up.
"""

from __future__ import annotations

import logging

from internal.council import pick_history, prediction_trace, resolver
from internal.learning import trail_events


def _stub_other_effects(monkeypatch):
    monkeypatch.setattr(resolver, "on_prediction_resolved", lambda *_a, **_k: {})
    monkeypatch.setattr(prediction_trace, "record_prediction_resolved", lambda *_a, **_k: None)
    monkeypatch.setattr(trail_events, "emit_prediction_resolved", lambda *_a, **_k: None)


def test_transient_pick_lock_timeout_is_retried(monkeypatch):
    _stub_other_effects(monkeypatch)
    calls = {"n": 0}

    def busy_then_ok(prediction):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("pick history lock busy")
        return {"ok": True}

    monkeypatch.setattr(pick_history, "finalize_from_prediction", busy_then_ok)
    warnings = resolver._finalize_effects({"id": "p1", "horizon_type": "hour"}, apply_judge_nudge=False)

    assert calls["n"] == 3
    assert "pick_history_finalize" not in warnings


def test_persistent_pick_lock_timeout_is_logged_with_prediction_id(monkeypatch, caplog):
    _stub_other_effects(monkeypatch)

    def always_busy(prediction):
        raise TimeoutError("pick history lock busy")

    monkeypatch.setattr(pick_history, "finalize_from_prediction", always_busy)
    with caplog.at_level(logging.ERROR):
        warnings = resolver._finalize_effects({"id": "p9", "horizon_type": "hour"}, apply_judge_nudge=False)

    assert "pick_history_finalize" in warnings
    assert any("p9" in rec.getMessage() for rec in caplog.records if rec.levelno >= logging.ERROR)
