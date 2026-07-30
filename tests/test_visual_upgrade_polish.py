"""Visual upgrade — subnet identity bands, soul-map orbs, weight-shift viz.

One runnable check per non-trivial piece of new logic (ponytail rule): the
netuid->band hash, and that the SSR templates actually emit the new markup
hooks the JS/CSS depend on.
"""

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader, select_autoescape

from internal.council.publish_gate import publish_gate_label


def netuid_band(netuid: int) -> int:
    """Mirror of the Jinja `sn_band` formula and JS k3NetuidBand()."""
    n = int(netuid)
    if n < 0:
        return 0
    return ((n * 47) + 11) % 6


def test_netuid_band_is_stable_and_spans_all_six_bands():
    seen = {netuid_band(n) for n in range(0, 300)}
    assert seen == {0, 1, 2, 3, 4, 5}
    # deterministic — same netuid always the same band
    assert netuid_band(82) == netuid_band(82)


def _render_council_stage(netuid: int) -> str:
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.globals["publish_gate_label"] = publish_gate_label
    return env.get_template("partials/premium/council_stage.html").render(
        dpick={
            "action": "HOLD",
            "pick": None,
            "candidate": {
                "subnet": {"netuid": netuid, "name": f"SN{netuid}"},
                "final_confidence": 0.5,
            },
        },
        hybrid_trust={},
        trust_banner={},
        story_path={},
        habit_watchlist={"netuids": []},
        habit_alerts={"enabled": False},
    )


def test_council_stage_emits_identity_band_and_keeps_action_badge_separate():
    html = _render_council_stage(82)
    expected_band = netuid_band(82)
    assert f'data-band="{expected_band}"' in html
    assert f"k3-claim--band-{expected_band}" in html
    assert 'data-netuid="82"' in html
    assert "--sn-accent" in html
    # 6 identity hues declared, not the old flat 4-color quartet
    for band in range(6):
        assert f'.k3-claim[data-band="{band}"]' in html
    # action badge markup untouched by identity color (still its own element)
    assert 'id="k3-action-badge"' in html


def test_hero_keeps_every_existing_animation_and_adds_new_layers():
    html = _render_council_stage(82)
    for anim in ("k3-spin", "k3-pulse", "k3-particle-drift", "k3-ring-fill"):
        assert anim in html
    # additive-only layers
    assert "k3-orb-halo" in html
    assert "k3-spin-reverse" in html
    assert "k3-score-pop" in html


def test_hydrate_js_mirrors_band_formula():
    src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "k3SyncNetuidBand(sn.netuid)" in src


def test_council_stage_js_band_formula_matches_jinja():
    src = open("templates/partials/premium/council_stage.html", encoding="utf-8").read()
    assert "function k3NetuidBand" in src
    assert "((n * 47) + 11) % 6" in src


def test_soul_map_renders_orb_constellation_not_flat_bars():
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    html = env.get_template("partials/premium/council.html").render(
        council_weights=[
            {"expert": "quant", "weight": 1.2, "trend": "up"},
            {"expert": "hype", "weight": 0.8, "trend": "down"},
            {"expert": "dark_horse", "weight": 1.0, "trend": "even"},
            {"expert": "technical", "weight": 1.0, "trend": "even"},
        ]
    )
    assert "soul-orb" in html
    assert "soul-orb--up" in html
    assert "soul-orb--down" in html
    assert "wbar" not in html
    assert "wfill" not in html


def test_council_weights_hydrate_js_builds_orb_markup():
    src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "soul-orb-card" in src
    assert "SOUL_ORB_COLORS" in src


def test_learning_loop_weight_nudge_viz_hook_present():
    html = _render_council_stage(82)
    assert 'id="k3-weight-nudge-viz"' in html
    src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "k3-weight-nudge-viz" in src
    assert "k3-weight-bar-fill" in src


def test_mindmap_uses_concentric_brain_layout_not_flat_circle():
    src = open("static/js/mindmap_graph.js", encoding="utf-8").read()
    assert "RING_RADIUS" in src
    assert "mindmap-core" in src
    # judges/disposition sit closer to the core than raw subnet/signal evidence
    assert "disposition: 0.24" in src
    assert "subnet: 1.0" in src
    assert "function ringRadiusFraction" in src
