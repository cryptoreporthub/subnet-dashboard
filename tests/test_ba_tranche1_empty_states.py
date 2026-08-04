"""B→A Tranche 1 — branded empty states, thumb dock IA, hero data hooks."""

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader, select_autoescape

from internal.council.publish_gate import publish_gate_label
from internal.preview.tribunal_hero import build_tribunal_view


def _tribunal_ctx(dpick: dict, trust_banner: dict | None = None) -> dict:
    return build_tribunal_view(
        dpick,
        {
            "judge_weights": {"oracle": 0.333, "echo": 0.333, "pulse": 0.334},
            "trust_banner": trust_banner or {},
        },
    )


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.globals["publish_gate_label"] = publish_gate_label
    return env


def test_build_desk_empty_state_js_helper():
    src = open("static/js/empty_state.js", encoding="utf-8").read()
    assert "buildDeskEmptyState" in src
    assert "Building sample" in src


def test_signals_template_uses_branded_empty_state():
    html = _env().get_template("partials/premium/signals.html").render(
        sig_sum=None,
        sig_list=[],
        top_signals=[],
    )
    assert "desk-empty-state" in html
    assert "Signal summary loading" in html
    assert "warming up" not in html.lower()


def test_proof_band_quiet_shows_sample_progress():
    html = _env().get_template("partials/premium_cockpit.html").render(
        subnets=[],
        trust_banner={"ready": False, "graded": 12, "min_graded": 30},
        daily_pick_stage={},
        simivision={},
        pump_alerts={},
        integrations_strip={},
        signals=[],
        alerts=[],
        signal_summary={},
        hour_picks=[],
        day_picks=[],
        mindmap_trail=[],
        predictions=[],
        message_intel=None,
        habit_alerts={"enabled": False},
        tribunal=_tribunal_ctx({"action": "HOLD", "candidate": {}}),
    )
    assert "proof-band-quiet" in html
    assert "Building sample — 12/30" in html
    assert "desk-empty-state--warming" in html


def test_thumb_dock_four_way_nav():
    html = _env().get_template("partials/premium/thumb_dock.html").render()
    assert "Council" in html
    assert "Radar" in html
    assert "Market" in html
    assert "Intel" in html
    assert "data-open-drawer=\"market-drawer\"" in html
    assert "section-message-intel" in html


def test_council_hero_data_hooks():
    dpick = {
        "action": "HOLD",
        "candidate": {
            "subnet": {"netuid": 82, "name": "Vanta"},
            "final_confidence": 0.34,
        },
    }
    html = _env().get_template("partials/premium/council_stage.html").render(
        dpick=dpick,
        daily_pick_stage=dpick,
        hybrid_trust={},
        trust_banner={},
        story_path={},
        habit_watchlist={"netuids": []},
        habit_alerts={"enabled": False},
        tribunal=_tribunal_ctx(dpick),
    )
    assert "data-testid=\"council-hero\"" in html
    assert "data-hero-phase=\"live\"" in html
    assert "data-hero-netuid=\"82\"" in html
    assert "data-hero-conviction=\"34\"" in html
