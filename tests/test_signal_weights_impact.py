"""§21 L6 — learned signal weights applied to signal_impact net."""

from internal.council.state_vector import _compute_signal_impact, _compute_technical_indicators
from internal.council.weights import load_signal_weights, save_signal_weights


def test_signal_impact_applies_learned_weights(monkeypatch, tmp_path):
    soul = tmp_path / "soul_map.json"
    soul.write_text('{"adversarial_state": {"council_weights": {}}}')
    weights = load_signal_weights(str(soul))
    weights["day"]["rsi_crossover"] = 1.0
    save_signal_weights(weights, str(soul))

    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))

    sn = {
        "netuid": 1,
        "price": 1.0,
        "price_change_24h": 2.0,
        "apy": 10.0,
        "emission": 1.0,
        "volume": 100_000,
    }
    indicators = _compute_technical_indicators(sn)
    hot = {"active": False, "reasons": []}
    sell = {"active": False, "reasons": []}

    low = _compute_signal_impact(sn, indicators, hot, sell, horizon_type="day")

    high_weights = load_signal_weights(str(soul))
    high_weights["day"]["rsi_crossover"] = 2.0
    save_signal_weights(high_weights, str(soul))
    high = _compute_signal_impact(sn, indicators, hot, sell, horizon_type="day")

    assert any(i.get("learned_weight") for i in high.get("impacts") or [])
    assert abs(high["net_predicted_pct_raw"]) >= abs(low["net_predicted_pct_raw"])
