"""K3-2b — dpick.shortlist deliberation wiring."""

from internal.learning.dpick_shortlist import (
    attach_shortlist_to_daily_pick,
    build_deliberation_shortlist,
    shortlist_cards_for_template,
)


def _sample_subnets():
    return [
        {
            "netuid": 1,
            "name": "Alpha",
            "price": 1.0,
            "volume": 10000,
            "price_change_24h": 2.0,
            "emission": 100,
            "apy": 12.0,
        },
        {
            "netuid": 2,
            "name": "Beta",
            "price": 0.5,
            "volume": 8000,
            "price_change_24h": 1.0,
            "emission": 80,
            "apy": 10.0,
        },
        {
            "netuid": 3,
            "name": "Gamma",
            "price": 0.2,
            "volume": 6000,
            "price_change_24h": -0.5,
            "emission": 60,
            "apy": 8.0,
        },
    ]


def test_build_deliberation_shortlist_returns_alternatives():
    payload = {
        "pick": {
            "subnet": {"netuid": 1, "name": "Alpha"},
            "final_confidence": 0.78,
            "expert_contributions": {"quant": 0.4, "hype": 0.2},
            "audit": {"concerns": []},
        }
    }
    out = build_deliberation_shortlist(_sample_subnets(), {}, payload)
    assert out["picked"]["netuid"] == 1
    assert len(out["alternatives"]) >= 2
    alt = out["alternatives"][0]
    assert isinstance(alt["netuid"], int)
    assert isinstance(alt["conviction"], int)


def test_attach_shortlist_honest_empty_when_thin():
    out = attach_shortlist_to_daily_pick({"pick": None}, [{"netuid": 1, "name": "Only"}], {})
    assert out["shortlist"] == []


def test_shortlist_cards_for_template_maps_role():
    cards = shortlist_cards_for_template(
        {
            "alternatives": [
                {"netuid": 2, "name": "Beta", "conviction": 62, "why_not": "Thin volume"}
            ]
        }
    )
    assert cards[0]["role"] == "Thin volume"
    assert cards[0]["stance"] == "LONG"


def test_mindmap_summary_includes_dpick_shortlist():
    from fastapi.testclient import TestClient

    from server import app

    with TestClient(app) as client:
        resp = client.get("/api/mindmap/summary")
    assert resp.status_code == 200
    data = resp.json().get("data") or {}
    dpick = data.get("dpick") or {}
    assert "shortlist" in dpick
    shortlist = dpick["shortlist"]
    if shortlist:
        assert isinstance(shortlist, dict)
        alts = shortlist.get("alternatives") or []
        assert isinstance(alts, list)
        for alt in alts:
            assert isinstance(alt.get("netuid"), int)
            assert isinstance(alt.get("conviction"), int)
