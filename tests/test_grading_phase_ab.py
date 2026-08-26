"""REV 6 Phase A/B: idempotency, three-tier capture scaling, degraded payloads."""

from __future__ import annotations

import json

import pytest

from internal.council.capture import (
    BAND_HIT,
    BAND_MISS,
    BAND_NEAR_HIT,
    BAND_NOISE,
    BAND_UNGRADEABLE,
    compute_capture,
)
from internal.council.weights import (
    _LEARNING_DELTA_CORRECT,
    _LEARNING_DELTA_WRONG,
    load_signal_weights,
    load_weights,
    nudge_signal_weight,
    save_signal_weights,
    save_weights,
)
from internal.judges.weights import load_judge_weights, nudge_judge, save_judge_weights


@pytest.fixture
def soul(tmp_path, monkeypatch):
    path = str(tmp_path / "soul_map.json")
    save_weights(
        {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0},
        path,
    )
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", path)
    monkeypatch.setattr("internal.judges.weights.SOUL_MAP_PATH", path)
    return path


def _council_pred(**extra):
    pred = {
        "id": "cap-1",
        "netuid": 1,
        "name": "Test",
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 100.0,
        "expert": "quant",
        "pick_source": "council",
        "horizon_type": "hour",
        "signal_source": "emission_momentum",
        "active_signals": ["emission_momentum"],
        "signal_contributions": {"emission_momentum": {"score": 0.8}},
        "signal_impact": {
            "impacts": [{"signal_type": "emission_momentum", "magnitude_pct": 1.0}]
        },
    }
    pred.update(extra)
    return pred


def test_double_resolve_does_not_double_nudge(soul, monkeypatch):
    from internal.council import resolver

    monkeypatch.setattr(resolver, "_in_replay_mode", lambda: False)
    pred = _council_pred()
    resolver.resolve_prediction(pred, current_price=102.0)
    after_first = load_weights(soul)["quant"]
    resolver.resolve_prediction(pred, current_price=102.0)
    after_second = load_weights(soul)["quant"]
    assert after_second == after_first


def test_capture_mode_near_hit_scales_expert(soul, monkeypatch):
    monkeypatch.setenv("GRADING_MODE", "capture")
    from internal.council import resolver

    monkeypatch.setattr(resolver, "_in_replay_mode", lambda: False)
    # +4% claim, +1.0% actual → c=0.25 NEAR-HIT (clears 0.5% deadband)
    pred = _council_pred(predicted_pct=4.0)
    before = load_weights(soul)["quant"]
    resolver.resolve_prediction(pred, current_price=101.0)
    after = load_weights(soul)["quant"]
    cap = compute_capture(4.0, 1.0)
    assert cap.band == BAND_NEAR_HIT
    assert after == pytest.approx(before + _LEARNING_DELTA_CORRECT * cap.capture_capped, abs=1e-4)


def test_capture_mode_hit_full_delta(soul, monkeypatch):
    monkeypatch.setenv("GRADING_MODE", "capture")
    from internal.council import resolver

    monkeypatch.setattr(resolver, "_in_replay_mode", lambda: False)
    pred = _council_pred(predicted_pct=2.0)
    before = load_weights(soul)["quant"]
    resolver.resolve_prediction(pred, current_price=102.0)
    after = load_weights(soul)["quant"]
    assert compute_capture(2.0, 2.0).band == BAND_HIT
    assert after == pytest.approx(before + _LEARNING_DELTA_CORRECT, abs=1e-4)


def test_capture_mode_miss_flat_penalty(soul, monkeypatch):
    monkeypatch.setenv("GRADING_MODE", "capture")
    from internal.council import resolver

    monkeypatch.setattr(resolver, "_in_replay_mode", lambda: False)
    pred = _council_pred(predicted_pct=2.0)
    before = load_weights(soul)["quant"]
    resolver.resolve_prediction(pred, current_price=97.0)  # -3%
    after = load_weights(soul)["quant"]
    assert compute_capture(2.0, -3.0).band == BAND_MISS
    assert after == pytest.approx(before + _LEARNING_DELTA_WRONG, abs=1e-4)


def test_capture_mode_noise_zero_nudge(soul, monkeypatch):
    monkeypatch.setenv("GRADING_MODE", "capture")
    from internal.council import resolver

    monkeypatch.setattr(resolver, "_in_replay_mode", lambda: False)
    pred = _council_pred(predicted_pct=2.0)
    before = load_weights(soul)["quant"]
    resolver.resolve_prediction(pred, current_price=100.3)  # +0.3% deadband
    after = load_weights(soul)["quant"]
    assert compute_capture(2.0, 0.3).band == BAND_NOISE
    assert after == before


def test_capture_mode_ungradeable_zero_nudge(soul, monkeypatch):
    monkeypatch.setenv("GRADING_MODE", "capture")
    from internal.council import resolver

    monkeypatch.setattr(resolver, "_in_replay_mode", lambda: False)
    pred = _council_pred(predicted_pct=0.0)
    before = load_weights(soul)["quant"]
    resolver.resolve_prediction(pred, current_price=101.0)
    after = load_weights(soul)["quant"]
    assert compute_capture(0.0, 1.0).band == BAND_UNGRADEABLE
    assert after == before
    assert pred.get("capture_raw") is None
    assert pred.get("capture_capped") is None


def test_nudge_signal_weight_five_outcomes(soul, monkeypatch):
    monkeypatch.setenv("GRADING_MODE", "capture")
    save_signal_weights(
        {"hour": {"rsi_crossover": 1.0}, "day": {"rsi_crossover": 1.0}},
        soul,
    )
    base = 1.0
    hit = compute_capture(2.0, 2.0)
    near = compute_capture(4.0, 1.0)
    miss = compute_capture(2.0, -3.0)
    noise = compute_capture(2.0, 0.3)
    ungrad = compute_capture(0.0, 1.0)

    after_hit = nudge_signal_weight("hour", "rsi_crossover", True, soul, scale=1.0)
    assert after_hit == pytest.approx(base + _LEARNING_DELTA_CORRECT, abs=1e-4)

    save_signal_weights({"hour": {"rsi_crossover": 1.0}, "day": {}}, soul)
    after_near = nudge_signal_weight(
        "hour", "rsi_crossover", True, soul, scale=near.capture_capped
    )
    assert after_near == pytest.approx(
        1.0 + _LEARNING_DELTA_CORRECT * near.capture_capped, abs=1e-4
    )

    save_signal_weights({"hour": {"rsi_crossover": 1.0}, "day": {}}, soul)
    after_miss = nudge_signal_weight("hour", "rsi_crossover", False, soul, scale=1.0)
    assert after_miss == pytest.approx(1.0 + _LEARNING_DELTA_WRONG, abs=1e-4)

    save_signal_weights({"hour": {"rsi_crossover": 1.0}, "day": {}}, soul)
    # Callers skip NOISE/UNGRADEABLE; scale 0 is the dedicated zero-nudge check.
    after_noise = nudge_signal_weight("hour", "rsi_crossover", True, soul, scale=0.0)
    assert after_noise == pytest.approx(1.0, abs=1e-4)
    assert noise.band == BAND_NOISE
    assert ungrad.band == BAND_UNGRADEABLE
    from internal.council.capture import nudge_multiplier

    assert nudge_multiplier(noise) is None
    assert nudge_multiplier(ungrad) is None
    assert nudge_multiplier(hit) == 1.0
    assert nudge_multiplier(miss) == 1.0
    assert nudge_multiplier(near) == pytest.approx(near.capture_capped)


def test_replay_option_a_uses_stored_capture(monkeypatch):
    """Live capture-mode replay consumes stored band/capture; pre-A uses legacy map."""
    monkeypatch.setenv("GRADING_MODE", "capture")
    from internal.council import weights as w

    rows = [
        {
            "correct": True,
            "band": "near_hit",
            "capture_capped": 0.25,
            "signal_impact": {
                "impacts": [{"signal_type": "emission_momentum", "magnitude_pct": 1.0}]
            },
        },
        {
            "correct": False,
            "band": "miss",
            "signal_impact": {
                "impacts": [{"signal_type": "emission_momentum", "magnitude_pct": 1.0}]
            },
        },
        {
            "correct": True,
            "signal_impact": {
                "impacts": [{"signal_type": "momentum_shift", "magnitude_pct": 1.0}]
            },
        },
    ]
    monkeypatch.setattr(w, "merged_replay_rows", lambda *_a, **_k: (rows, {}))
    out = w.replay_weights_from_predictions()
    assert out["quant"] == pytest.approx(
        1.0 + _LEARNING_DELTA_CORRECT * 0.25 + _LEARNING_DELTA_WRONG, abs=1e-4
    )
    assert out["hype"] == pytest.approx(1.0 + _LEARNING_DELTA_CORRECT, abs=1e-4)


def test_replay_signal_weights_capture_scale(monkeypatch):
    monkeypatch.setenv("GRADING_MODE", "capture")
    from internal.council import weights as w

    rows = [
        {
            "correct": True,
            "band": "near_hit",
            "capture_capped": 0.25,
            "horizon_type": "hour",
            "active_signals": ["emission_momentum"],
            "signal_contributions": {"emission_momentum": {"score": 0.8}},
        },
        {
            "correct": False,
            "band": "miss",
            "horizon_type": "hour",
            "active_signals": ["emission_momentum"],
            "signal_contributions": {"emission_momentum": {"score": 0.8}},
        },
        {
            "correct": True,
            "horizon_type": "hour",
            "active_signals": ["momentum_shift"],
            "signal_contributions": {"momentum_shift": {"score": 0.8}},
        },
    ]
    monkeypatch.setattr(w, "merged_replay_rows", lambda *_a, **_k: (rows, {}))
    out = w.replay_signal_weights_from_predictions()
    hour = out["hour"]
    assert hour["emission_momentum"] == pytest.approx(
        1.0 + _LEARNING_DELTA_CORRECT * 0.25 + _LEARNING_DELTA_WRONG, abs=1e-4
    )
    assert hour["momentum_shift"] == pytest.approx(1.0 + _LEARNING_DELTA_CORRECT, abs=1e-4)


def test_apply_rebase_guards_no_evidence_no_leverage():
    from internal.council.weights import apply_rebase_guards

    proposed = {"quant": 1.8, "hype": 1.5, "dark_horse": 1.0, "technical": 0.4}
    out = apply_rebase_guards(proposed, [])
    assert out["quant"] == 1.0
    assert out["hype"] == 1.0
    assert out["technical"] == 1.0


def test_weighted_blend_degraded_flag(monkeypatch):
    from internal.council.expert_display import weighted_expert_blend

    monkeypatch.setattr(
        "internal.council.weights.effective_weights",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("weights down")),
    )
    leader, blended = weighted_expert_blend({"quant": 0.8, "hype": 0.2})
    assert leader is None
    assert blended.get("_blend_degraded") is True
    assert blended.get("quant") == 0.8


def test_nudge_judge_capture_scale(tmp_path, monkeypatch):
    monkeypatch.setenv("GRADING_MODE", "capture")
    path = str(tmp_path / "soul_map.json")
    save_judge_weights({"oracle": 1.0, "echo": 1.0, "pulse": 1.0}, path=path)
    near = compute_capture(4.0, 1.0)
    after = nudge_judge("oracle", True, path=path, scale=near.capture_capped)
    assert after == pytest.approx(1.0 + 0.02 * near.capture_capped, abs=1e-4)


def test_judge_skips_pump_and_shadow(monkeypatch, tmp_path):
    from internal.judges import tracker
    from internal.judges.weights import DEFAULT_JUDGE_WEIGHTS

    path = str(tmp_path / "soul_map.json")
    save_judge_weights(dict(DEFAULT_JUDGE_WEIGHTS), path=path)
    monkeypatch.setattr("internal.judges.weights.SOUL_MAP_PATH", path)

    class _Closed(dict):
        pass

    class _FakeJudge:
        name = "oracle"

        def close_position(self, *_a, **_k):
            return {"pnl_pct": 1.0}

        def record_postmortem(self, *_a, **_k):
            return None

    monkeypatch.setattr(tracker, "all_judges", lambda: [_FakeJudge()])
    before = load_judge_weights(path)["oracle"]
    tracker.on_prediction_resolved(
        {"pick_source": "pump_lead", "correct": True, "actual_pct": 3.0, "id": "p"}
    )
    after = load_judge_weights(path)["oracle"]
    assert after == before


def test_weights_api_degraded_shape(monkeypatch):
    from fastapi.testclient import TestClient

    from server import app

    monkeypatch.setattr(
        "internal.learning.routes.load_weights_for_ui",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with TestClient(app) as client:
        resp = client.get("/api/council/weights")
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["data"] is None
    assert data["weights_degraded"] is True
    assert "error" in data
    assert data.get("data") != {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}


def test_load_weights_for_ui_proxy_except_is_degraded(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("DATA_DIR", "/nonexistent")

    def _boom():
        raise OSError("worker down")

    monkeypatch.setattr(
        "internal.worker_proxy.fetch_learning_stats_sync",
        _boom,
    )
    from internal.council.weights import load_weights_for_ui

    payload = load_weights_for_ui()
    assert payload.get("_proxy_degraded") is True
    assert set(payload.keys()) == {"_proxy_degraded"}


def test_score_subnet_exception_not_half(monkeypatch):
    from internal.judges import subnet_judges

    monkeypatch.setattr(
        subnet_judges.ORACLE,
        "evaluate",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("oracle down")),
    )
    result = subnet_judges.score_subnet(
        1, {"netuid": 1, "name": "X", "price": 1, "apy": 0.1, "price_change_24h": 2.0}
    )
    assert result["oracle"]["score"] is None
    assert result["oracle"]["oracle_degraded"] is True
    assert result["oracle"]["status"] == "degraded"
    assert 0.5 not in (result["oracle"]["score"], result["consensus"].get("score"))


def test_score_all_subnets_bulk_failure_not_half(monkeypatch):
    from internal.judges import subnet_judges

    monkeypatch.setattr(
        subnet_judges,
        "score_subnet",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("bulk")),
    )
    rows = subnet_judges.score_all_subnets(
        [{"netuid": 9, "name": "Z"}], use_chain=False
    )
    assert rows[0]["oracle"]["score"] is None
    assert rows[0]["consensus"]["score"] is None
    dumped = json.dumps(rows)
    assert '"score": 0.5' not in dumped


def test_streak_whisper_skips_pump(monkeypatch):
    from internal.learning.streaks import compute_streaks

    data = {
        "resolved": [
            {
                "correct": True,
                "expert": "quant",
                "resolved_at": "2026-07-01T01:00:00Z",
                "outcome": "hit",
                "pick_source": "pump_lead",
            },
            {
                "correct": True,
                "expert": "quant",
                "resolved_at": "2026-07-01T02:00:00Z",
                "outcome": "hit",
                "pick_source": "council",
            },
            {
                "correct": True,
                "expert": "quant",
                "resolved_at": "2026-07-01T03:00:00Z",
                "outcome": "hit",
                "pick_source": "council",
            },
            {
                "correct": True,
                "expert": "quant",
                "resolved_at": "2026-07-01T04:00:00Z",
                "outcome": "hit",
                "pick_source": "council",
            },
        ]
    }
    out = compute_streaks(data)
    assert out["council"]["length"] == 3
    assert "pump" not in (out.get("whisper") or "").lower()
