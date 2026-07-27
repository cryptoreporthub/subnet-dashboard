"""Daily pick creation uses scheduler cap universe (not full hydrate list)."""

from internal.council import daily_pick_engine


def test_subnets_for_pick_creation_caps(monkeypatch):
    subnets = [{"netuid": i, "marketcap_rank": i, "price": 1.0} for i in range(1, 60)]
    monkeypatch.setenv("PICK_SCHEDULER_UNIVERSE_CAP", "24")
    monkeypatch.setenv("TOP_SCORING_UNIVERSE", "40")
    monkeypatch.setenv("SCORING_CAP_MEGA_CEILING_RANK", "10")
    capped = daily_pick_engine._subnets_for_pick_creation(subnets)
    assert len(capped) <= 24


def test_regen_calls_select_on_capped_universe(monkeypatch, tmp_path):
    path = str(tmp_path / "daily_picks.json")
    daily_pick_engine.DAILY_PICKS_PATH = path
    today = daily_pick_engine._today_str()

    stale = {
        "status": "ok",
        "date": today,
        "action": "HOLD",
        "pick": None,
        "candidate": {
            "subnet": {"netuid": 78, "name": "SN78"},
            "audit": {"concerns": ["Missing critical field: price"]},
        },
    }
    import json

    with open(path, "w") as f:
        json.dump([stale], f)

    full = [{"netuid": i, "name": f"SN{i}", "price": 1.0, "marketcap_rank": i} for i in range(1, 60)]
    capped = full[:24]
    monkeypatch.setattr(daily_pick_engine, "_subnets_for_pick_creation", lambda s: capped)

    select_args = {}

    def _fake_select(subnets, ctx):
        select_args["n"] = len(subnets)
        select_args["netuids"] = [s.get("netuid") for s in subnets]
        return {
            "subnet": {"netuid": 40, "name": "Chunking"},
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

    hydrated = [{"netuid": 78, "name": "SN78", "price": 1.0, "marketcap_rank": 78}]
    out = daily_pick_engine.get_or_create_today_pick(hydrated + full, {}, force=False)

    assert select_args["n"] == 24
    assert out["action"] == "long"
    assert (out.get("pick") or {}).get("subnet", {}).get("netuid") == 40
