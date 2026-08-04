"""Tribunal hero live-wired into homepage council_stage."""

from fastapi.testclient import TestClient

from internal.preview.tribunal_hero import build_tribunal_view
from server import app

client = TestClient(app)


def test_build_tribunal_view_gated_hold():
    payload = {
        "status": "ok",
        "action": "HOLD",
        "pick": None,
        "candidate": {
            "subnet": {"netuid": 99, "name": "SN99"},
            "final_confidence": 0.34,
            "action": "LONG",
        },
        "timestamp_utc": "2026-08-04T12:00:00Z",
    }
    view = build_tribunal_view(
        payload,
        {
            "judge_weights": {"oracle": 0.333, "echo": 0.333, "pulse": 0.334},
            "trust_banner": {"ready": False, "graded": 12},
        },
    )
    assert view["center_label"] == "GATED · HOLD"
    assert view["verdict_kind"] == "gated"
    assert view["subnet_label"] == "SN99"
    assert view["synced_at"] == "2026-08-04T12:00:00Z"


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
    assert "style=\"--p: 71;\"" in html
    assert "id=\"tribunal-hero-sync\"" in html
    assert "tribunal-hero__sync" in html


def test_cockpit_hydrate_tribunal_sync_helpers():
    src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "patchTribunalSyncStamp" in src
    assert "formatSyncedAge" in src
    assert "setProperty('--p'" in src


def test_home_ssr_contains_tribunal_hero():
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
