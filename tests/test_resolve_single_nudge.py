"""Resolve path must not double-nudge expert weights via judge audit."""


def test_resolve_skips_judge_audit_nudge(monkeypatch, tmp_path):
    from internal.council import resolver, weights

    path = str(tmp_path / "soul_map.json")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", path)
    monkeypatch.setattr("internal.judges.weights.SOUL_MAP_PATH", path)
    weights.save_weights(
        {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0},
        path,
    )
    monkeypatch.setattr(resolver, "_in_replay_mode", lambda: False)

    audit_calls = []

    def _boom(*_a, **_k):
        audit_calls.append(True)
        raise AssertionError("judge audit should not run on resolve")

    monkeypatch.setattr(resolver, "_nudge_weights_from_judge_audit", _boom)

    pred = {
        "id": "t1",
        "netuid": 1,
        "name": "Test",
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 10.0,
        "expert": "quant",
        "pick_source": "council",
        "signal_source": "emission_momentum",
        "active_signals": ["emission_momentum"],
        "signal_impact": {
            "impacts": [{"signal_type": "emission_momentum", "magnitude_pct": 1.0}]
        },
        "judge_scores_at_creation": {"oracle": {"score": 0.9}},
    }
    out = resolver.resolve_prediction(pred, current_price=10.2)
    assert out.get("correct") is True
    assert audit_calls == []
    assert abs(weights.load_weights(path)["quant"] - 1.02) < 1e-6
    assert abs(weights.load_weights(path)["technical"] - 1.0) < 1e-6
