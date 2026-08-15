"""Tribunal hero live-wired into homepage council_stage."""

from fastapi.testclient import TestClient

from internal.preview.tribunal_hero import (
    _format_judge_weight_pct,
    _judge_agreement_labels,
    attach_judge_scores_to_daily_pick,
    build_tribunal_view,
    conviction_temp,
    verdict_kind,
    weighted_verdict_pct,
)
from datetime import datetime, timedelta, timezone
from server import app

client = TestClient(app)


def test_weighted_verdict_pct_gauge_math():
    weights = {"oracle": 0.40, "echo": 0.30, "pulse": 0.30}
    signals = {"oracle": 36.0, "echo": 32.0, "pulse": 32.0}
    assert weighted_verdict_pct(weights, signals) == 33.6


def test_conviction_temp_warm_above_threshold_cool_below():
    assert conviction_temp("gated", 71.6) == "warm"
    assert conviction_temp("gated", 70.0) == "warm"
    assert conviction_temp("gated", 69.9) == "cool"
    assert conviction_temp("gated", 33.6) == "cool"
    assert conviction_temp("sealed", 85.0) == "warm"
    assert conviction_temp("cold", None) == "cool"
    assert conviction_temp("forming", 50.0) == "cool"


def test_judge_weight_display_equal_vs_different():
    equal = {"oracle": 1 / 3, "echo": 1 / 3, "pulse": 1 / 3}
    assert _format_judge_weight_pct(equal, "oracle") == "Equal weight"
    mixed = {"oracle": 0.40, "echo": 0.30, "pulse": 0.30}
    assert _format_judge_weight_pct(mixed, "oracle") == "40%"
    assert _format_judge_weight_pct(mixed, "echo") == "30%"


def test_judge_agreement_from_signal_spread():
    labels = _judge_agreement_labels({"oracle": 85.9, "echo": 84.0, "pulse": 45.0})
    assert labels["consensus"] == "Low agreement"
    assert labels["dissent"] == "High dissent · 41 pts"


def test_attach_judge_scores_does_not_use_ambiguous_netuid_backfill(monkeypatch):
    scores = {
        "oracle": {"confidence": 0.859},
        "echo": {"confidence": 0.84},
        "pulse": {"confidence": 0.45},
    }
    monkeypatch.setattr(
        "internal.council.conviction_bands.judge_scores_for_netuid",
        lambda netuid: scores if int(netuid) == 29 else None,
    )
    payload = {
        "action": "long",
        "pick": {"subnet": {"netuid": 29, "name": "Coldint"}, "final_confidence": 0.72},
    }
    out = attach_judge_scores_to_daily_pick(payload)
    assert "judge_scores_at_creation" not in out["pick"]
    assert build_tribunal_view(out, {"judge_weights": {"oracle": 0.4, "echo": 0.3, "pulse": 0.3}})["conviction_pct"] == 72.0


def test_attach_judge_scores_preserves_exact_creation_scores():
    scores = {
        "oracle": {"confidence": 0.859},
        "echo": {"confidence": 0.84},
        "pulse": {"confidence": 0.45},
    }
    payload = {
        "action": "long",
        "pick": {
            "subnet": {"netuid": 29, "name": "Coldint"},
            "final_confidence": 0.72,
            "judge_scores_at_creation": scores,
        },
    }
    out = attach_judge_scores_to_daily_pick(payload)
    assert out["pick"]["judge_scores_at_creation"] == scores


def test_daily_pick_lite_enrich_attaches_matching_day_judge_scores(monkeypatch):
    import server as srv
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date().isoformat()
    scores = {"oracle": {"confidence": 0.8}, "echo": {"confidence": 0.7}, "pulse": {"confidence": 0.6}}

    def _fake_load():
        return {
            "predictions": [
                {
                    "netuid": 12,
                    "horizon_type": "day",
                    "created_at": f"{today}T12:00:00Z",
                    "judge_scores_at_creation": scores,
                }
            ],
            "resolved": [],
        }

    monkeypatch.setattr("internal.learning.predictions_store.load_predictions", _fake_load)
    out = srv._enrich_daily_pick_payload_lite(
        {
            "date": today,
            "action": "long",
            "pick": {
                "subnet": {"netuid": 12, "name": "SN12"},
                "final_confidence": 0.68,
            },
        }
    )
    assert out["pick"]["judge_scores_at_creation"] == scores


def test_daily_pick_lite_enrich_does_not_attach_unmatched_judge_scores(monkeypatch):
    import server as srv

    scores = {"oracle": {"confidence": 0.8}, "echo": {"confidence": 0.7}, "pulse": {"confidence": 0.6}}
    monkeypatch.setattr(
        "internal.council.conviction_bands.judge_scores_for_netuid",
        lambda netuid: scores,
    )
    out = srv._enrich_daily_pick_payload_lite(
        {
            "action": "long",
            "pick": {
                "subnet": {"netuid": 12, "name": "SN12"},
                "final_confidence": 0.68,
            },
        }
    )
    assert "judge_scores_at_creation" not in out["pick"]


def test_build_tribunal_view_decision_log_from_judge_scores():
    payload = {
        "status": "ok",
        "action": "LONG",
        "pick": {
            "subnet": {"netuid": 29, "name": "Coldint"},
            "final_confidence": 0.72,
            "judge_scores_at_creation": {
                "oracle": {"confidence": 0.859},
                "echo": {"confidence": 0.84},
                "pulse": {"confidence": 0.45},
            },
        },
    }
    view = build_tribunal_view(payload, {"judge_weights": {"oracle": 0.4, "echo": 0.3, "pulse": 0.3}})
    dl = view["panels"]["decision_log"]
    assert dl["consensus"] == "Low agreement"
    assert dl["dissent"] == "High dissent · 41 pts"


def _publishable_pick(*, approved=True, timestamp=None, stale=False):
    return {
        "status": "ok",
        "action": "LONG",
        "generated_at": timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "_meta": {"stale": stale},
        "pick": {
            "subnet": {"netuid": 29, "name": "Coldint"},
            "final_confidence": 0.72,
            "audit": {"approved": approved},
        },
    }


def test_tribunal_seals_only_current_approved_pick():
    assert verdict_kind(_publishable_pick()) == "sealed"
    assert verdict_kind(_publishable_pick(approved=False)) == "gated"
    stale = datetime.now(timezone.utc) - timedelta(hours=26)
    assert verdict_kind(_publishable_pick(timestamp=stale.isoformat())) == "gated"
    assert verdict_kind(_publishable_pick(stale=True)) == "gated"
    assert verdict_kind({"status": "ok", "action": "LONG", "pick": None}) == "cold"


def test_unapproved_or_stale_pick_never_has_sealed_hero_copy():
    for payload in (
        _publishable_pick(approved=False),
        _publishable_pick(timestamp=(datetime.now(timezone.utc) - timedelta(hours=26)).isoformat()),
    ):
        view = build_tribunal_view(payload, {})
        assert view["verdict_kind"] == "gated"
        assert view["center_label"] == "GATED · HOLD"
        assert "SEALED" not in view["headline"]


def test_build_tribunal_view_gated_hold():
    payload = {
        "status": "ok",
        "action": "HOLD",
        "pick": None,
        "candidate": {
            "subnet": {"netuid": 99, "name": "SN99"},
            "final_confidence": 0.34,
            "action": "LONG",
            "judge_scores_at_creation": {
                "oracle": {"confidence": 0.36},
                "echo": {"confidence": 0.32},
                "pulse": {"confidence": 0.32},
            },
        },
        "timestamp_utc": "2026-08-04T12:00:00Z",
    }
    view = build_tribunal_view(
        payload,
        {
            "judge_weights": {"oracle": 0.40, "echo": 0.30, "pulse": 0.30},
            "trust_banner": {"ready": False, "graded": 12},
        },
    )
    assert view["center_label"] == "GATED · HOLD"
    assert view["verdict_kind"] == "gated"
    assert view["subnet_label"] == "SN99"
    assert view["synced_at"] == "2026-08-04T12:00:00Z"
    assert view["gauge_display"] == "33.6%"
    assert view["conviction_pct"] == 33.6
    assert view["conviction_temp"] == "cool"


def test_build_tribunal_view_gated_warm_when_high_conviction():
    payload = {
        "action": "HOLD",
        "candidate": {
            "subnet": {"netuid": 15, "name": "ORO"},
            "final_confidence": 0.716,
        },
        "judge_scores": {
            "oracle": {"confidence": 0.859},
            "echo": {"confidence": 0.84},
            "pulse": {"confidence": 0.45},
        },
    }
    view = build_tribunal_view(
        payload,
        {"judge_weights": {"oracle": 0.40, "echo": 0.30, "pulse": 0.30}},
    )
    assert view["conviction_temp"] == "warm"


def test_tribunal_hero_template_sync_and_conviction_hooks():
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    from internal.council.publish_gate import publish_gate_label

    payload = {
        "action": "HOLD",
        "timestamp_utc": "2026-08-04T12:00:00Z",
        "candidate": {
            "subnet": {"netuid": 14, "name": "TaoHash"},
            "final_confidence": 0.71,
        },
    }
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.globals["publish_gate_label"] = publish_gate_label
    html = env.get_template("partials/premium/tribunal_hero.html").render(
        tribunal=build_tribunal_view(payload, {}),
    )
    assert "data-synced-at=\"2026-08-04T12:00:00Z\"" in html
    assert "data-hero-conviction=\"71\"" in html
    assert 'data-temp="warm"' in html
    assert "style=\"--p: 71.0;\"" in html or "style=\"--p: 71;\"" in html
    assert "id=\"tribunal-hero-sync\"" in html
    assert "tribunal-hero__sync" in html
    assert 'data-panel="decision-log"' in html


def test_cockpit_hydrate_tribunal_sync_helpers():
    src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "patchTribunalSyncStamp" in src
    assert "formatSyncedAge" in src
    assert "weightedVerdictPct" in src
    assert "patchTribunalPanels" in src
    assert "patchTribunalInstrument" in src
    assert "judgeAgreementLabels" in src
    assert "judgeSignalsFromDom" in src
    assert "convictionTemp" in src
    assert "syncCouncilTemp" in src
    assert "pickIsPublishable" in src
    hero = open("templates/partials/premium/tribunal_hero.html", encoding="utf-8").read()
    assert "var hero = document.getElementById('tribunal-hero')" in hero
    assert "hero.querySelector('[data-metric=\"' + k + '\"]')" in hero


def test_home_ssr_contains_tribunal_hero():
    from server import _warm_homepage_cache

    _warm_homepage_cache()
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert 'id="tribunal-hero"' in html
    assert html.count('data-judge="oracle"') == 1
    assert html.count('data-judge="echo"') == 1
    assert html.count('data-judge="pulse"') == 1
    assert "THE TRIBUNAL" not in html
    assert 'data-panel="accuracy-ledger"' in html
    assert "Loading council desk" not in html
    assert "Council votes" not in html
    assert "Weighed against" not in html
    assert 'data-panel="decision-log"' in html


def test_legacy_pump_route_redirects_to_canonical_path():
    response = client.get("/Pump", follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"] == "/pump"
