"""Combined next-up + peer — experimental angles + ledger track."""

from __future__ import annotations

from internal.council.grading import is_pump_combined_exp, is_pump_desk_claim, is_pump_lead
from internal.pump.combined import (
    W_PEER,
    W_TIMING,
    attach_angles_to_desk,
    combined_points,
    rank_desk_angles,
    timing_points,
)
from internal.pump import combined_ledger


def _entry(netuid, phase, score, buy=0.6, vol=0.3, mom=0.002, chg=-0.02, price=1.0, **extra):
    return {
        "netuid": netuid,
        "name": f"Sub{netuid}",
        "phase": phase,
        "composite_score": score,
        "signal_snapshot": {
            "buy_ratio": buy,
            "volume_intensity": vol,
            "momentum_1h": mom,
            "price_change_24h": chg,
            "price": price,
            **extra,
        },
    }


def test_combined_weights_sum():
    assert abs(W_TIMING + W_PEER - 1.0) < 1e-9
    assert combined_points(100, 0) == round(W_TIMING * 100, 1)
    assert combined_points(0, 100) == round(W_PEER * 100, 1)


def test_timing_points_early_beats_cooling():
    early = _entry(1, "ACCUMULATING", 0.65)
    late = _entry(2, "COOLING", 0.65)
    assert timing_points(early) > timing_points(late)


def test_to_lead_pct_relative_to_hero():
    focus = _entry(23, "PUMPING", 0.80)
    half = _entry(11, "ACCUMULATING", 0.40)
    near = _entry(12, "ACCUMULATING", 0.72)
    from internal.pump.combined import _to_lead_pct

    assert _to_lead_pct(half, focus) == 50
    assert _to_lead_pct(near, focus) == 90
    assert _to_lead_pct(focus, focus) == 100


def test_rank_keeps_separate_next_up_and_combined():
    focus = _entry(23, "PUMPING", 0.85, buy=0.62, vol=0.4, mom=0.004)
    near = _entry(11, "ACCUMULATING", 0.68, buy=0.55, vol=0.25, mom=0.001)  # timing
    peerish = _entry(12, "STIRRING", 0.42, buy=0.61, vol=0.38, mom=0.0035)  # peer shape
    state = {"subnets": {"23": focus, "11": near, "12": peerish}}
    out = rank_desk_angles(23, state, track_limit=5)
    assert out["experimental"] is True
    assert out["next_up"]
    assert out["peers"]["lane"]
    # Tracked slate can be >1 even if UI shows one
    assert len(out["tracked"]) >= 1
    if out["combined"]:
        assert "timing_pts" in out["combined"]
        assert "peer_pts" in out["combined"]
        assert "experimental" in out["why"].lower() or "Combined" in out["why"]


def test_attach_angles_sets_hero_fields(tmp_path, monkeypatch):
    ledger = tmp_path / "combined_calls.json"
    monkeypatch.setattr(combined_ledger, "LEDGER_PATH", str(ledger))
    monkeypatch.setattr(
        combined_ledger,
        "_freeze_shown_prediction",
        lambda *a, **k: None,
    )
    focus = _entry(23, "ACCUMULATING", 0.7, buy=0.6, vol=0.3)
    quiet = _entry(7, "STIRRING", 0.45, buy=0.58, vol=0.28, mom=0.001)
    hot = _entry(9, "ACCUMULATING", 0.66, buy=0.52, vol=0.2)
    state = {"subnets": {"23": focus, "7": quiet, "9": hot}}
    payload = {"hero": {"netuid": 23, "name": "Trishool", "timing": "lead"}, "alerts": []}
    attach_angles_to_desk(payload, state)
    assert payload["hero"].get("next_up") is not None
    assert payload["hero"].get("peers")
    assert payload["combined"]["experimental"] is True


def test_ledger_tracks_more_than_shown(tmp_path, monkeypatch):
    ledger = tmp_path / "combined_calls.json"
    monkeypatch.setattr(combined_ledger, "LEDGER_PATH", str(ledger))
    monkeypatch.setattr(combined_ledger, "_freeze_shown_prediction", lambda *a, **k: "abc")
    angles = {
        "focus_netuid": 23,
        "weights": {"timing": 0.7, "peer": 0.3},
        "combined": {
            "netuid": 11,
            "name": "Sub11",
            "timing_pts": 80,
            "peer_pts": 40,
            "combined_pts": 68,
            "price": 1.2,
            "phase": "ACCUMULATING",
            "score": 0.6,
        },
        "tracked": [
            {"netuid": 11, "combined_pts": 68},
            {"netuid": 12, "combined_pts": 60},
            {"netuid": 13, "combined_pts": 55},
        ],
        "next_up": [{"netuid": 9}],
        "peers": {"matches": [{"netuid": 7}]},
    }
    call = combined_ledger.maybe_record_combined_call(angles)
    assert call is not None
    assert call["shown_netuid"] == 11
    assert len(call["tracked"]) == 3
    assert call["prediction_id"] == "abc"
    # Dedup same shown
    assert combined_ledger.maybe_record_combined_call(angles) is None


def test_grading_flags():
    lead = {"pick_source": "pump_lead"}
    exp = {"pick_source": "pump_combined_exp"}
    assert is_pump_lead(lead) and not is_pump_combined_exp(lead)
    assert is_pump_combined_exp(exp) and not is_pump_lead(exp)
    assert is_pump_desk_claim(lead) and is_pump_desk_claim(exp)
