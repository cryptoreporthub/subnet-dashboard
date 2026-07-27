"""W0-A — Proof band RF-2 honesty (trust_banner.ready gate)."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from internal.learning.trust_stats import build_trust_banner


def test_proof_band_template_gates_on_ready():
    html = Path("templates/partials/premium_cockpit.html").read_text(encoding="utf-8")
    assert "tb_ready" in html
    assert "Building trust gate" in html or "tb.message" in html
    assert "data-brain-state=\"{{ 'live' if tb_ready else 'building' }}\"" in html


def test_trust_banner_not_ssr_hidden_when_blocked():
    stage = Path("templates/partials/premium/council_stage.html").read_text(encoding="utf-8")
    assert "trust-banner--blocked" in stage
    assert "{% if not tb.ready %}hidden{% endif %}" not in stage


def test_hydrate_syncs_proof_from_trust():
    js = Path("static/js/cockpit_hydrate.js").read_text(encoding="utf-8")
    assert "syncProofBandFromTrust" in js
    assert "RF-2" in js
    tb = Path("static/js/trust_banner_ui.js").read_text(encoding="utf-8")
    assert 'removeAttribute("hidden")' in tb


def test_home_proof_band_quiet_when_trust_not_ready():
    """SSR: graded>0 but ready=false must not show big accuracy % in proof band."""
    banner = build_trust_banner({"correct": 10, "wrong": 5, "expired": 0, "total": 15})
    assert banner["ready"] is False
    assert banner["graded"] == 15

    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tmpl = env.from_string(
        "{% set tb = trust_banner %}"
        "{% set cal_n = tb.graded|default(0) %}"
        "{% set tb_ready = tb.ready|default(false) %}"
        "{% if tb_ready and tb.accuracy is not none and cal_n|int > 0 %}"
        "{% set cal_acc = (tb.accuracy|float * 100)|round(1) %}"
        "{% else %}{% set cal_acc = none %}{% endif %}"
        "{% if tb_ready and cal_acc is not none %}"
        '<div class="proof-band__pct">{{ cal_acc|round(0) }}%</div>'
        "{% else %}"
        '<p class="proof-band__quiet">{% if tb.message %}{{ tb.message }}{% else %}Building{% endif %}</p>'
        "{% endif %}"
    )
    html = tmpl.render(trust_banner=banner)
    assert "proof-band__pct" not in html
    assert "proof-band__quiet" in html
    assert "Not enough graded" in html


def test_council_stage_accuracy_gated_on_ready():
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tmpl = env.get_template("partials/premium/council_stage.html")
    html = tmpl.render(
        dpick={"action": "HOLD", "pick": None, "candidate": None},
        hybrid_trust={"n": 15},
        trust_banner={
            "graded": 15,
            "correct": 10,
            "wrong": 5,
            "accuracy": 0.667,
            "ready": False,
            "message": "Not enough graded picks yet (15/30)",
            "min_graded": 30,
        },
        story_path={},
        habit_watchlist={},
        habit_alerts={"enabled": False},
    )
    assert "67%" not in html
    assert "66.7%" not in html
    html_ready = tmpl.render(
        dpick={"action": "HOLD", "pick": None, "candidate": None},
        hybrid_trust={"n": 454},
        trust_banner={
            "graded": 454,
            "correct": 143,
            "wrong": 311,
            "accuracy": 0.315,
            "ready": True,
            "headline": "Last 454 graded: 32% directionally right",
            "min_graded": 30,
        },
        story_path={},
        habit_watchlist={},
        habit_alerts={"enabled": False},
    )
    assert "31.5%" in html_ready or "32%" in html_ready
