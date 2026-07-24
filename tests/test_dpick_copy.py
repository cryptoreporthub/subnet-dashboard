"""K3-7 hero copy brief — trader voice, no audit-log phrasing."""

from __future__ import annotations

from internal.learning.dpick_copy import (
    _BANNED_IN_HERO,
    attach_brief_to_daily_pick,
    build_dpick_brief,
    hero_copy_is_clean,
)


def _hold_candidate_payload() -> dict:
    return {
        "action": "HOLD",
        "pick": None,
        "candidate": {
            "subnet": {"netuid": 99, "name": "SN99", "symbol": "T99"},
            "final_confidence": 0.23,
            "audit": {
                "concerns": [
                    "Subnet flagged as overvalued",
                    "Thin volume: $1,200 < $5k",
                ]
            },
        },
        "shortlist": [
            {"netuid": 64, "name": "SN64", "conviction": 19, "role": "Stronger momentum"},
            {"netuid": 12, "name": "SN12", "conviction": 21, "role": "Cleaner liquidity"},
        ],
    }


def test_hold_candidate_trader_voice():
    brief = build_dpick_brief(_hold_candidate_payload())
    assert brief["move"] == "HOLD · SN99"
    assert "closest long" in brief["thesis"].lower()
    assert "rich vs peers" in brief["thesis"].lower()
    assert brief["trigger"].startswith("Flip to LONG when conviction ≥ 45%")
    assert "valuation" in brief["trigger"].lower() or "45%" in brief["trigger"]
    assert "Beat SN64" in brief["vs"]
    assert brief["tone"] == "hold"
    assert hero_copy_is_clean(brief)


def test_audited_long_voice():
    brief = build_dpick_brief(
        {
            "action": "LONG",
            "pick": {
                "subnet": {"netuid": 7, "name": "Apex"},
                "final_confidence": 0.72,
                "audit": {"approved": True, "concerns": []},
            },
            "shortlist": [
                {"netuid": 77, "name": "SN77", "role": "hotter tape, thinner book"},
            ],
        }
    )
    assert brief["move"].startswith("LONG · Apex")
    assert "liquidity" in brief["thesis"].lower()
    assert "Passed SN77" in brief["vs"]
    assert brief["tone"] == "go"
    assert hero_copy_is_clean(brief)


def test_empty_hold_voice():
    brief = build_dpick_brief({"action": "HOLD", "pick": None, "candidate": None})
    assert brief["move"] == "HOLD · no long"
    assert "sitting out" in brief["thesis"].lower()
    assert hero_copy_is_clean(brief)


def test_evidence_drivers_includes_shortlist_role_social():
    brief = build_dpick_brief(
        {
            "action": "HOLD",
            "pick": None,
            "candidate": {
                "subnet": {"netuid": 99, "name": "SN99"},
                "final_confidence": 0.23,
            },
            "shortlist": [
                {"netuid": 118, "name": "Ditto", "conviction": 26, "role": "Social buzz", "stance": "LONG"},
            ],
        }
    )
    tags = [d["tag"] for d in brief["evidence_drivers"]]
    labels = " ".join(d["label"] for d in brief["evidence_drivers"]).lower()
    assert "social" in tags or "social" in labels


def test_social_crumb_empty_without_mentions():
    brief = build_dpick_brief(_hold_candidate_payload())
    assert brief.get("social_crumb") == ""


def test_social_crumb_from_registry_mentions(monkeypatch):
    monkeypatch.setattr(
        "internal.message_intel.context.lookup_social_sentiment_for_netuid",
        lambda *a, **k: None,
    )
    payload = _hold_candidate_payload()
    payload["candidate"]["subnet"]["social_mentions"] = 42
    payload["candidate"]["subnet"]["social_sentiment"] = 0.72
    brief = build_dpick_brief(payload)
    assert brief["social_crumb"].startswith("Social · bullish")
    assert "42 mentions" in brief["social_crumb"]
    social_drivers = [d for d in brief["evidence_drivers"] if d["tag"] == "social"]
    assert social_drivers
    assert "42 mentions" in social_drivers[0]["label"]


def test_attach_brief_on_payload():
    out = attach_brief_to_daily_pick(_hold_candidate_payload())
    assert "brief" in out
    assert out["brief"]["move"].startswith("HOLD ·")


def test_banned_substrings_not_in_hero_copy():
    payloads = [
        _hold_candidate_payload(),
        {
            "action": "LONG",
            "pick": {
                "subnet": {"netuid": 1, "name": "Test"},
                "final_confidence": 0.8,
            },
            "shortlist": [],
        },
        {"action": "HOLD", "pick": None, "candidate": None, "shortlist": []},
    ]
    for p in payloads:
        brief = build_dpick_brief(p)
        blob = f"{brief['move']} {brief['thesis']}".lower()
        for banned in _BANNED_IN_HERO:
            assert banned not in blob, f"found {banned!r} in {brief}"
