"""HOLD must write trail + soul-map (no silent brain)."""

from internal.learning import prediction_loop


def test_record_hold_decision_writes_soul_map(monkeypatch, tmp_path):
    saved = {}

    def _load():
        return {"soul_map_state": {}}

    def _save(data):
        import copy

        saved.clear()
        saved.update(copy.deepcopy(data))

    events = []

    def _emit(event_type, **kwargs):
        events.append({"event_type": event_type, **kwargs})

    monkeypatch.setattr("internal.council.weights._load_raw", _load)
    monkeypatch.setattr("internal.council.weights._save_raw", _save)
    monkeypatch.setattr(
        "internal.learning.trail_events.emit_trail_event", _emit
    )

    prediction_loop.record_hold_decision(
        candidate={
            "subnet": {"netuid": 42, "name": "TestSN"},
            "final_confidence": 0.32,
        },
        reason="Confidence 32% below 45% audit gate — no long call published",
        horizon_type="day",
    )

    assert events
    assert events[0]["event_type"] == "conviction_update"
    assert events[0]["decision"] == "HOLD"
    assert saved["soul_map_state"]["last_day_pick"]["action"] == "HOLD"
    assert saved["soul_map_state"]["last_day_hold"]["action"] == "HOLD"
    assert saved["soul_map_state"]["last_day_pick"]["pick"] is None


def test_daily_engine_hold_calls_record(monkeypatch, tmp_path):
    from internal.council import daily_pick_engine

    daily_pick_engine.DAILY_PICKS_PATH = str(tmp_path / "daily_picks.json")
    called = {}

    def _fake_hold(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(
        "internal.learning.prediction_loop.record_hold_decision", _fake_hold
    )
    monkeypatch.setattr(
        daily_pick_engine,
        "select_daily_pick",
        lambda subnets, ctx: {
            "subnet": {"netuid": 9, "name": "Low"},
            "final_confidence": 0.2,
            "action": "long",
        },
    )
    monkeypatch.setattr(daily_pick_engine, "classify_regime", lambda ctx: "neutral")
    monkeypatch.setattr(daily_pick_engine, "get_rotation_summary", lambda s: {})

    out = daily_pick_engine.get_or_create_today_pick(
        [{"netuid": 9, "name": "Low", "price": 1.0}],
        {},
    )
    assert out["action"] == "HOLD"
    assert called.get("horizon_type") == "day"
    assert called.get("candidate") is not None
