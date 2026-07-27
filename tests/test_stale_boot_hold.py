"""Stale boot HOLD regen when subnets hydrate."""

from internal.council import daily_pick_engine


def test_stale_boot_hold_regenerates_with_hydrated_subnets(monkeypatch, tmp_path):
    path = str(tmp_path / "daily_picks.json")
    daily_pick_engine.DAILY_PICKS_PATH = path
    today = daily_pick_engine._today_str()

    stale = {
        "status": "ok",
        "date": today,
        "action": "HOLD",
        "pick": None,
        "candidate": {
            "subnet": {"netuid": 1, "name": "Apex"},
            "final_confidence": 0.28,
            "audit": {
                "concerns": ["Missing critical field: price", "Missing critical field: volume"],
            },
        },
        "reason": "Confidence 28% below 40% audit gate — no long call published",
    }
    import json

    with open(path, "w") as f:
        json.dump([stale], f)

    regen_calls = {"n": 0}

    def _fake_select(subnets, ctx):
        regen_calls["n"] += 1
        return {
            "subnet": {"netuid": 42, "name": "Mid"},
            "final_confidence": 0.52,
            "action": "long",
        }

    monkeypatch.setattr(daily_pick_engine, "select_daily_pick", _fake_select)
    monkeypatch.setattr(daily_pick_engine, "classify_regime", lambda ctx: "neutral")
    monkeypatch.setattr(daily_pick_engine, "get_rotation_summary", lambda s: {})
    monkeypatch.setattr(
        "internal.learning.prediction_loop.record_pick_prediction",
        lambda *a, **k: {"id": "p1"},
    )

    subnets = [
        {"netuid": 1, "name": "Apex", "price": 12.5, "volume": 5000, "marketcap_rank": 1},
        {"netuid": 42, "name": "Mid", "price": 2.0, "volume": 8000, "marketcap_rank": 25},
    ]
    out = daily_pick_engine.get_or_create_today_pick(subnets, {}, force=False)

    assert regen_calls["n"] == 1
    assert out["action"] == "long"
    assert out["pick"] is not None
    with open(path) as f:
        rows = json.load(f)
    assert len([r for r in rows if r.get("date") == today]) == 1


def test_fresh_hold_not_regenerated(monkeypatch, tmp_path):
    path = str(tmp_path / "daily_picks.json")
    daily_pick_engine.DAILY_PICKS_PATH = path
    today = daily_pick_engine._today_str()

    hold = {
        "status": "ok",
        "date": today,
        "action": "HOLD",
        "pick": None,
        "candidate": {
            "subnet": {"netuid": 42, "name": "Mid", "price": 2.0, "volume": 8000},
            "final_confidence": 0.35,
            "audit": {"concerns": ["Low liquidity: volume $400 < $500"]},
        },
        "reason": "Confidence 35% below 40% audit gate — no long call published",
    }
    import json

    with open(path, "w") as f:
        json.dump([hold], f)

    monkeypatch.setattr(
        daily_pick_engine,
        "select_daily_pick",
        lambda subnets, ctx: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    subnets = [{"netuid": 42, "name": "Mid", "price": 2.0, "volume": 8000, "marketcap_rank": 25}]
    out = daily_pick_engine.get_or_create_today_pick(subnets, {}, force=False)
    assert out["action"] == "HOLD"
    assert out["reason"] == hold["reason"]
