"""Methodology block and coverage fields for judge backtest."""

from internal.analytics.backtest import run_backtest
from internal.analytics.backtest_methodology import build_methodology_payload


_FIXTURE = {
    "predictions": [],
    "resolved": [
        {
            "id": "hit-up",
            "netuid": 1,
            "name": "Alpha",
            "direction": "up",
            "predicted_pct": 5.0,
            "actual_pct": 3.2,
            "status": "resolved",
            "signal_source": "HOT",
            "reference_price": 1.0,
            "subnet_snapshot": {
                "price": 1.0,
                "apy": 0.2,
                "emission": 1.0,
                "price_change_24h": 2.0,
                "price_change_7d": 5.0,
            },
        },
        {
            "id": "miss-down",
            "netuid": 2,
            "name": "Beta",
            "direction": "down",
            "predicted_pct": -4.0,
            "actual_pct": 2.5,
            "status": "resolved",
            "signal_source": "SELL ALERT",
            "reference_price": 1.0,
            "subnet_snapshot": {
                "price": 1.0,
                "apy": 0.2,
                "emission": 1.0,
                "price_change_24h": -1.0,
                "price_change_7d": -2.0,
            },
        },
        {
            "id": "council-miss",
            "netuid": 3,
            "name": "Gamma",
            "direction": "up",
            "predicted_pct": 4.0,
            "actual_pct": -2.0,
            "status": "resolved",
            "signal_source": "council_hour_pick",
            "expert": "quant",
            "reference_price": 1.0,
        },
    ],
    "stats": {},
}


def test_methodology_payload_has_cited_sources():
    payload = build_methodology_payload()
    assert payload["version"] == "1.0"
    assert len(payload["sources"]) >= 4
    assert all(s.get("url") and s.get("citation") for s in payload["sources"])
    metric_ids = {m["id"] for m in payload["metrics"]}
    assert "selective_hit_rate" in metric_ids
    assert "coverage" in metric_ids
    assert "calibration_reliability" in metric_ids


def test_backtest_includes_methodology_coverage_and_risk_coverage():
    result = run_backtest(data=_FIXTURE)
    assert result["status"] == "success"
    assert "methodology" in result
    assert result["methodology"]["sources"]

    council = result["council"]
    assert council["coverage"] == 1.0
    assert council["coverage_pct"] == 100.0
    assert council["metric_id"] == "council_direction_rate"

    for judge in ("oracle", "echo", "pulse"):
        block = result["judges"][judge]
        assert block["metric_id"] == "selective_hit_rate"
        assert block["coverage"] is not None
        assert block["coverage_pct"] is not None
        assert block["endorsed_n"] <= result["sample_size"]
        assert isinstance(block["risk_coverage"], list)
        assert len(block["risk_coverage"]) >= 5
        active = [p for p in block["risk_coverage"] if p["n"] > 0]
        assert active
        assert active[0]["coverage_pct"] is not None
        assert block["calibration"][0].get("score_mid") is not None

    overlap = result["endorsement_overlap"]
    assert overlap["sample_size"] == result["sample_size"]
    assert len(overlap["pairs"]) == 3
