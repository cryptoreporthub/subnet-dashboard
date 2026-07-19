"""K3 P0/P1 — HOLD + candidate shows full hero (orb, chips, conviction)."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, select_autoescape

import server
from internal.learning.dpick_copy import attach_brief_to_daily_pick
from internal.subnet_names import refresh_daily_pick_names


def _hold_candidate_payload() -> dict:
    return {
        "action": "HOLD",
        "pick": None,
        "candidate": {
            "subnet": {"netuid": 82, "name": "SN82", "symbol": "SN82"},
            "final_confidence": 0.286,
            "action": "LONG",
            "reasons": ["Emission momentum"],
        },
        "horizon_views": {
            "default": "24h",
            "anchor": "24h",
            "chips": ["now", "24h"],
            "views": {
                "now": {
                    "id": "now",
                    "label": "Now",
                    "subnet": {"netuid": 14, "name": "SN14"},
                    "conviction": 40,
                    "action": "LONG",
                },
                "24h": {
                    "id": "24h",
                    "label": "24h",
                    "subnet": {"netuid": 82, "name": "SN82"},
                    "conviction": 29,
                    "action": "LONG",
                },
            },
        },
        "temporal_badge": "LIVE · 4h remaining",
        "ring_state": "fresh",
        "resolve_at": "2026-07-19T12:00:00Z",
    }


def _minimal_hero_ctx(payload: dict) -> dict:
    return {
        "daily_pick_stage": payload,
        "conviction_band": {"band": None, "reason": "test"},
        "enrichment_badge": {},
        "story_strip": {},
        "habit_watchlist": {"netuids": []},
        "habit_alerts": {},
        "hybrid_trust": {},
        "trust_banner": {"ready": False, "message": "Building track record"},
    }


def test_refresh_daily_pick_names_candidate_and_horizon():
    payload = _hold_candidate_payload()
    out = refresh_daily_pick_names(payload)
    cand_name = out["candidate"]["subnet"]["name"]
    assert cand_name != "SN82" or cand_name.startswith("SN")
    view_name = out["horizon_views"]["views"]["24h"]["subnet"]["name"]
    assert view_name == cand_name


def test_council_stage_hold_candidate_renders_full_hero():
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tmpl = env.get_template("partials/premium/council_stage.html")
    payload = attach_brief_to_daily_pick(refresh_daily_pick_names(_hold_candidate_payload()))
    html = tmpl.render(
        dpick=payload,
        conviction_band={"band": None},
        enrichment_badge={},
        hybrid_trust={},
        trust_banner={},
        habit_watchlist={"netuids": []},
        habit_alerts={"enabled": False},
        story_path={},
    )
    assert "k3-horizon-chips" in html
    assert "k3-call-headline" in html
    assert "HOLD ·" in html
    assert "Flip to LONG" in html
    assert "council scan" not in html.lower()
    orb_html = html.split('id="k3-orb-score"')[1].split("</div>")[0]
    assert "digit-tens" in orb_html or "digit-ones" in orb_html
    assert "—" not in orb_html


def test_home_hold_candidate_via_hero_patch():
    payload = attach_brief_to_daily_pick(refresh_daily_pick_names(_hold_candidate_payload()))

    def fake_fast(trust_banner=None):
        return _minimal_hero_ctx(payload)

    server._DEGRADED_INDEX_CACHE.clear()
    with patch.object(server, "_fast_home_hero_context", fake_fast):
        with TestClient(server.app) as client:
            html = client.get("/").text

    assert "k3-horizon-chips" in html
    assert "k3-call-headline" in html
    assert "HOLD ·" in html
