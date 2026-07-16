"""Emission monitor deltas vs soul_map snapshot."""

import json

from internal.council.emission_monitor import EmissionMonitor, snapshot_registry_emissions


def test_emission_delta_trend(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        json.dumps(
            {
                "emission_monitor": {
                    "last_emissions": {"1": 100.0, "2": 50.0},
                    "snapshot_at": "2026-01-01T00:00:00Z",
                }
            }
        )
    )
    monkeypatch.setattr("internal.council.emission_monitor.SOUL_MAP_PATH", str(soul))

    mon = EmissionMonitor()
    up = mon.check_emission_deltas(1, 110.0)
    assert up["trend"] == "up"
    assert up["delta"] == 10.0

    down = mon.check_emission_deltas(2, 45.0)
    assert down["trend"] == "down"

    unknown = mon.check_emission_deltas(99, 10.0)
    assert unknown["trend"] == "unknown"


def test_snapshot_registry_emissions():
    reg = {"1": {"netuid": 1, "emission": 12.5}, "2": {"netuid": 2, "emission": 3.0}}
    snap = snapshot_registry_emissions(reg, run_at="t")
    assert snap["1"] == 12.5
    assert snap["2"] == 3.0
