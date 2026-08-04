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


def test_home_ssr_contains_tribunal_hero():
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert 'id="tribunal-hero"' in html
    assert html.count('data-judge="oracle"') == 1
    assert html.count('data-judge="echo"') == 1
    assert html.count('data-judge="pulse"') == 1
    assert "THE TRIBUNAL" not in html
