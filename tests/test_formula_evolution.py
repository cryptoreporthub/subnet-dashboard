"""Formula evolution trail tests."""

from internal.council.formula_evolution import build_evolution_trail

_FIXTURE_PREDS = {
    "predictions": [],
    "resolved": [
        {
            "id": "a1",
            "netuid": 1,
            "name": "Alpha",
            "expert": "dark_horse",
            "direction": "up",
            "predicted_pct": 4.0,
            "actual_pct": -5.0,
            "correct": False,
            "resolved_at": "2026-07-15T10:00:00Z",
            "status": "resolved",
        },
        {
            "id": "a2",
            "netuid": 2,
            "name": "Beta",
            "expert": "contrarian",
            "direction": "up",
            "predicted_pct": 3.0,
            "actual_pct": -2.0,
            "correct": False,
            "resolved_at": "2026-07-15T12:00:00Z",
            "status": "resolved",
        },
        {
            "id": "a3",
            "netuid": 3,
            "name": "Gamma",
            "expert": "dark_horse",
            "direction": "down",
            "predicted_pct": -2.0,
            "actual_pct": -4.0,
            "correct": True,
            "resolved_at": "2026-07-16T10:00:00Z",
            "status": "resolved",
        },
        {
            "id": "a4",
            "netuid": 4,
            "name": "Delta",
            "expert": "dark_horse",
            "direction": "up",
            "predicted_pct": 2.0,
            "actual_pct": 1.0,
            "correct": True,
            "resolved_at": "2026-07-16T11:00:00Z",
            "status": "resolved",
        },
    ],
}


def test_evolution_trail_has_origin_and_current(monkeypatch):
    monkeypatch.setattr(
        "internal.council.formula_evolution._lane_predictions",
        lambda lane: _FIXTURE_PREDS["resolved"] if lane == "dark_horse" else [],
    )
    monkeypatch.setattr("internal.council.formula_evolution._weight_events", lambda lane: [])
    monkeypatch.setattr("internal.council.formula_evolution._calibration_episodes", lambda: [])

    trail = build_evolution_trail("dark_horse")
    assert trail is not None
    kinds = [e["kind"] for e in trail["trail"]]
    assert kinds[0] == "origin"
    assert kinds[-1] == "current"
    assert trail["lane_id"] == "dark_horse"
    assert "Martin" in trail["trail"][0].get("narrative", "")


def test_evolution_trail_subnet_episode(monkeypatch):
    monkeypatch.setattr(
        "internal.council.formula_evolution._lane_predictions",
        lambda lane: _FIXTURE_PREDS["resolved"] if lane == "dark_horse" else [],
    )
    monkeypatch.setattr("internal.council.formula_evolution._weight_events", lambda lane: [])
    monkeypatch.setattr("internal.council.formula_evolution._calibration_episodes", lambda: [])

    trail = build_evolution_trail("dark_horse")
    subnet_eps = [e for e in trail["trail"] if e["kind"] == "subnet_divergence"]
    assert subnet_eps
    assert subnet_eps[0]["trigger_subnets"]
