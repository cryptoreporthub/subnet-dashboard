"""Hero claim identity — 4 netuid bands (floor(n/32)%4)."""

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader, select_autoescape

from internal.council.publish_gate import publish_gate_label


def netuid_band(netuid: int) -> int:
    """Keep in sync with k3NetuidBand() in cockpit_hydrate.js + council_stage SSR."""
    n = int(netuid)
    if n < 0:
        return 0
    return (n // 32) % 4


def test_netuid_band_edges():
    assert netuid_band(0) == 0
    assert netuid_band(31) == 0
    assert netuid_band(32) == 1
    assert netuid_band(63) == 1
    assert netuid_band(64) == 2
    assert netuid_band(95) == 2
    assert netuid_band(96) == 3
    assert netuid_band(127) == 3
    assert netuid_band(128) == 0


def test_council_stage_emits_data_band_for_subnet():
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.globals["publish_gate_label"] = publish_gate_label
    html = env.get_template("partials/premium/council_stage.html").render(
        dpick={
            "action": "HOLD",
            "pick": None,
            "candidate": {
                "subnet": {"netuid": 82, "name": "SN82"},
                "final_confidence": 0.5,
            },
        },
        hybrid_trust={},
        trust_banner={},
        story_path={},
        habit_watchlist={"netuids": []},
        habit_alerts={"enabled": False},
    )
    assert 'data-band="2"' in html  # 82 // 32 == 2
    assert "k3-claim--band-2" in html
    assert 'data-netuid="82"' in html
    assert "--sn-accent" in html
    assert '.k3-claim[data-band="1"]' in html


def test_hydrate_exposes_band_sync():
    src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "function k3NetuidBand" in src
    assert "function syncK3NetuidBand" in src
    assert "syncK3NetuidBand(sn.netuid)" in src
    assert "Math.floor(n / 32) % 4" in src
