"""Echo Kin — pulse lookalikes that haven't moved yet."""

from __future__ import annotations

from internal.pump.echo_kin import (
    attach_echo_to_desk,
    find_echo_kin,
    lane_tag,
    pulse_distance,
    pulse_vector,
    signature_rarity,
)


def _entry(netuid, phase, score, buy=0.6, vol=0.3, mom=0.002, chg=-0.02, **extra):
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
            **extra,
        },
    }


def test_lane_tag_quiet_load():
    entry = _entry(1, "ACCUMULATING", 0.55, buy=0.58, vol=0.2, mom=0.001, chg=0.01)
    assert lane_tag(entry) in ("Quiet Load", "Pressure", "Coil", "Lift")


def test_find_echo_kin_prefers_quieter_peers():
    focus = _entry(10, "PUMPING", 0.85, buy=0.62, vol=0.4, mom=0.004, chg=-0.03)
    quiet = _entry(11, "STIRRING", 0.4, buy=0.6, vol=0.35, mom=0.003, chg=-0.025)
    louder = _entry(12, "PUMPING", 0.9, buy=0.61, vol=0.38, mom=0.004, chg=-0.028)
    state = {"subnets": {"10": focus, "11": quiet, "12": louder}}
    out = find_echo_kin(10, state, limit=3)
    assert out["lane"]
    assert out["rarity"] is not None
    ids = [k["netuid"] for k in out["kin"]]
    assert 11 in ids
    assert 12 not in ids  # not quieter
    assert "Echo Kin" in (out["why"] or "") or "Lane" in (out["why"] or "")


def test_signature_rarity_higher_when_unique():
    focus = pulse_vector(_entry(1, "STIRRING", 0.5, buy=0.7, vol=0.5, mom=-0.01, chg=-0.05))
    sameish = [pulse_vector(_entry(i, "STIRRING", 0.4, buy=0.55, vol=0.2, mom=0.0, chg=0.0)) for i in range(5)]
    rare = signature_rarity(focus, [focus] + sameish)
    crowded = signature_rarity(focus, [focus] * 8)
    assert rare >= crowded


def test_attach_echo_to_desk_hero():
    focus = _entry(23, "ACCUMULATING", 0.7, buy=0.6, vol=0.3, mom=0.001, chg=-0.02)
    kin = _entry(7, "STIRRING", 0.35, buy=0.58, vol=0.28, mom=0.001, chg=-0.018)
    state = {"subnets": {"23": focus, "7": kin}}
    payload = {
        "hero": {"netuid": 23, "name": "Trishool", "timing": "lead"},
        "alerts": [],
    }
    attach_echo_to_desk(payload, state)
    assert payload["hero"]["echo"]["lane"]
    assert payload["echo"]["focus_netuid"] == 23
    assert payload["hero"].get("signature_rarity") is not None


def test_pulse_distance_identical_is_zero():
    e = _entry(1, "STIRRING", 0.5)
    v = pulse_vector(e)
    assert pulse_distance(v, v) == 0.0
