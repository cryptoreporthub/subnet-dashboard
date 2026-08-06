"""Tribunal hero live-wired into homepage council_stage."""

from fastapi.testclient import TestClient

from internal.preview.tribunal_hero import (
    _format_judge_weight_pct,
    _judge_agreement_labels,
    build_tribunal_view,
    weighted_verdict_pct,
)
from server import app

client = TestClient(app)


def test_weighted_verdict_pct_gauge_math():
    weights = {"oracle": 0.40, "echo": 0.30, "pulse": 0.30}
    signals = {"oracle": 36.0, "echo": 32.0, "pulse": 32.0}
    assert weighted_verdict_pct(weights, signals) == 33.6


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


def test_tribunal_hero_template_sync_and_conviction_hooks():
    from jinja2 import Environment, FileSystemLoader, select_autoescape

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
    html = env.get_template("partials/premium/tribunal_hero.html").render(
        tribunal=build_tribunal_view(payload, {}),
    )
    assert "data-synced-at=\"2026-08-04T12:00:00Z\"" in html
    assert "data-hero-conviction=\"71\"" in html
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
    assert "judgeAgreementLabels" in src
    assert "setProperty('--p'" in src


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
    assert "Expert bench" in html
    assert "Alternatives" in html
    assert "k3-layer-teaser" in html
    assert "Council votes" not in html
    assert "Weighed against" not in html
    assert 'data-panel="accuracy-ledger"' in html
