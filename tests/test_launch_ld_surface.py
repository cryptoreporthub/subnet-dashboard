"""Launch LD — surface honesty checks."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, select_autoescape

from internal.council.publish_gate import publish_gate_label
from server import app

client = TestClient(app)


def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )


def test_alert_button_hidden_when_disabled():
    env = _jinja_env()
    env.globals["publish_gate_label"] = publish_gate_label
    html = env.get_template("partials/premium/council_stage.html").render(
        dpick={"action": "HOLD", "pick": None, "candidate": None},
        hybrid_trust={"n": 0},
        trust_banner={"ready": False, "message": "Building"},
        story_path={},
        habit_watchlist={"netuids": [], "count": 0},
        habit_alerts={"enabled": False},
    )
    assert 'id="habit-alert-btn"' in html
    assert 'data-enabled="0"' in html
    assert "hidden" in html.split('id="habit-alert-btn"')[1].split(">")[0]
    assert "Conviction alerts off on this deploy" in html


def test_pick_card_hold_markup_ssr():
    env = _jinja_env()
    env.globals["publish_gate_label"] = publish_gate_label
    html = env.get_template("partials/premium/picks.html").render(
        hp=[
            {
                "netuid": 15,
                "name": "BitQuant",
                "score": 7.2,
                "confidence": 0.32,
                "action": "HOLD",
                "hold_reason": f"Confidence 32% below {publish_gate_label()}",
            }
        ],
        dyp=[],
    )
    assert "pick-degraded-note--hold" in html
    assert "HOLD" in html
    assert publish_gate_label() in html


def test_council_stage_hold_degraded_note():
    env = _jinja_env()
    env.globals["publish_gate_label"] = publish_gate_label
    gate = publish_gate_label()
    html = env.get_template("partials/premium/council_stage.html").render(
        dpick={
            "action": "HOLD",
            "pick": None,
            "candidate": {
                "subnet": {"netuid": 15, "name": "BitQuant"},
                "final_confidence": 0.32,
                "confidence": 0.32,
            },
            "hold_reason": f"Confidence 32% below {gate}",
        },
        hybrid_trust={"n": 100},
        trust_banner={"ready": True, "graded": 100, "accuracy": 0.31},
        story_path={},
        habit_watchlist={"netuids": [], "count": 0},
        habit_alerts={"enabled": False},
    )
    assert "k3-degraded-note" in html
    assert gate in html


def test_paper_portfolio_quiet_states_in_js():
    body = Path("static/js/paper_portfolio.js").read_text(encoding="utf-8")
    assert "empty--quiet" in body
    assert "Paper portfolio unavailable" in body


def test_chat_partial_context_copy():
    chat_js = Path("static/js/chat_stream.js").read_text(encoding="utf-8")
    assert "Partial context — council data loaded" in chat_js
    assert "chatReady" in chat_js

    from internal.simivision import chat_service

    src = Path(chat_service.__file__).read_text(encoding="utf-8")
    assert "Partial context — council data loaded" in src


def test_publish_gate_label_global():
    assert templates_has_gate_label()


def templates_has_gate_label() -> bool:
    from server import templates

    return callable(templates.env.globals.get("publish_gate_label"))


def test_watchlist_empty_vs_error_copy():
    body = Path("static/js/watchlist_alerts.js").read_text(encoding="utf-8")
    assert "No pinned subnets" in body
    assert "Watchlist unavailable" in body


def test_portfolio_status_endpoint():
    res = client.get("/api/portfolio/status")
    assert res.status_code == 200
