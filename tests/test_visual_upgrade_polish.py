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


_SENTINEL = object()


def _render_council_stage_confidence(
    *,
    final_confidence=_SENTINEL,
    confidence=_SENTINEL,
    conviction=_SENTINEL,
    netuid: int = 82,
) -> str:
    """Render council_stage with explicit confidence fields for H1 three-state SSR checks."""
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.globals["publish_gate_label"] = publish_gate_label
    cand = {"subnet": {"netuid": netuid, "name": f"SN{netuid}"}}
    if final_confidence is not _SENTINEL:
        cand["final_confidence"] = final_confidence
    if confidence is not _SENTINEL:
        cand["confidence"] = confidence
    if conviction is not _SENTINEL:
        cand["conviction"] = conviction
    return env.get_template("partials/premium/council_stage.html").render(
        dpick={"action": "HOLD", "pick": None, "candidate": cand},
        hybrid_trust={},
        trust_banner={},
        story_path={},
        habit_watchlist={"netuids": []},
        habit_alerts={"enabled": False},
    )


def test_council_stage_h1_resolving_conf_state_ssr():
    """H1: no confidence fields → resolving (not fabricated 0% conviction)."""
    html = _render_council_stage_confidence(
        final_confidence=None,
        confidence=None,
        conviction=None,
    )
    assert 'id="k3-dossier"' in html
    assert 'data-conf-state="resolving"' in html
    orb_html = html.split('id="k3-orb-score"')[1].split("</div>")[0]
    assert 'digit-ones">—' in orb_html
    assert ">0</span>" not in orb_html


def test_council_stage_h1_zero_conf_state_ssr():
    html = _render_council_stage_confidence(final_confidence=0)
    assert 'data-conf-state="zero"' in html
    orb_html = html.split('id="k3-orb-score"')[1].split("</div>")[0]
    assert ">0</span>" in orb_html


def test_council_stage_h1_value_conf_state_ssr():
    html = _render_council_stage_confidence(final_confidence=0.5)
    assert 'data-conf-state="value"' in html
    orb_html = html.split('id="k3-orb-score"')[1].split("</div>")[0]
    assert "digit-ones" in orb_html
    assert "—" not in orb_html


def _council_stage_style_block(html: str) -> str:
    start = html.index("<style>")
    end = html.index("</style>", start)
    return html[start:end]


def test_council_stage_h2_resolving_conf_state_visual_css():
    """H2: resolving uses animated muted ring sweep, not opacity-only placeholder."""
    html = _render_council_stage_confidence(
        final_confidence=None,
        confidence=None,
        conviction=None,
    )
    css = _council_stage_style_block(html)
    assert "[data-conf-state=\"resolving\"]" in css
    assert "k3-resolving-ring-sweep" in css
    assert "#k3-dossier[data-conf-state=\"resolving\"] .k3-orb .ring-fill" in css
    assert "animation: k3-resolving-ring-sweep" in css
    assert "#k3-dossier[data-conf-state=\"resolving\"] { opacity:" not in css


def test_council_stage_h2_zero_conf_state_visual_css():
    html = _render_council_stage_confidence(final_confidence=0)
    css = _council_stage_style_block(html)
    assert "#k3-dossier[data-conf-state=\"zero\"] .k3-orb .ring-fill" in css
    zero_ring = css.split("#k3-dossier[data-conf-state=\"zero\"] .k3-orb .ring-fill", 1)[1][:400]
    assert "stroke" in zero_ring
    assert "k3-muted" in zero_ring


def test_council_stage_h2_delayed_conf_state_visual_css():
    css = _council_stage_style_block(_render_council_stage(82))
    assert "k3-delayed-dot" in css
    assert "#k3-dossier[data-conf-state=\"delayed\"] .k3-orb-wrap::after" in css
    delayed_dot = css.split("#k3-dossier[data-conf-state=\"delayed\"] .k3-orb-wrap::after", 1)[1][:400]
    assert "k3-orange" in delayed_dot
    assert "animation" in delayed_dot


def test_council_stage_h2_reduced_motion_disables_conf_state_animations():
    css = _council_stage_style_block(_render_council_stage(82))
    assert "prefers-reduced-motion" in css
    reduced = css.split("prefers-reduced-motion", 1)[1]
    assert "[data-conf-state=\"resolving\"]" in reduced
    assert "[data-conf-state=\"delayed\"]" in reduced
    assert "animation: none" in reduced


def test_cockpit_hydrate_h1_three_state_hooks_present():
    """Client-side patchK3DossierFromPayload three-state logic — no JS test runner in repo."""
    src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "_k3ConfResolvingTimer" in src
    assert "data-conf-state" in src
    assert "confState = 'resolving'" in src
    assert "confState = 'zero'" in src
    assert "confState = 'value'" in src


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


def test_hero_palette_maps_onto_site_accent_tokens():
    src = open("templates/partials/premium/council_stage.html", encoding="utf-8").read()
    assert "--k3-pink: var(--accent-violet" in src
    assert "--k3-green: var(--accent-primary" in src
    assert "#ff69b4" not in src
    assert 'stop-color="#9d8cff"' in src


def test_learning_loop_shows_quiet_empty_state_when_no_deltas():
    html = _render_council_stage(82)
    assert "No weight shift this window" in html
    src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "No weight shift this window" in src


def test_soul_map_hydrate_trend_matches_ssr_baseline():
    src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "soulTrendFromWeight" in src
    assert "SOUL_WEIGHT_BASELINE" in src
    # Must not derive orb trend from ephemeral deltas (SSR uses weight vs 1.0)
    assert "function soulTrendFromWeight" in src
    idx = src.index("function renderCouncilWeights")
    body = src[idx : idx + 1200]
    assert "soulTrendFromWeight(w)" in body
    assert "delta > 0.005 ? 'up'" not in body


def test_empty_hold_shell_emits_identity_band():
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    from internal.council.publish_gate import publish_gate_label

    env.globals["publish_gate_label"] = publish_gate_label
    html = env.get_template("partials/premium/council_stage.html").render(
        dpick={"action": "HOLD", "brief": {"move": "HOLD · no long", "tone": "hold"}},
        hybrid_trust={},
        trust_banner={},
        story_path={},
        habit_watchlist={"netuids": []},
        habit_alerts={"enabled": False},
    )
    assert 'data-band="0"' in html
    assert "k3-claim--band-0" in html


def test_mindmap_is_grouped_trail_not_node_link_graph():
    """Full replace: no SVG node-link graph — a subnet-grouped receipts list
    reuses the star-shaped data (subnet -> its signal/judge/prediction/
    scenario/disposition edges) instead of forcing it into a circle layout."""
    src = open("static/js/mindmap_graph.js", encoding="utf-8").read()
    assert "function buildTrailGroups" in src
    assert "function renderTrail" in src
    assert "KIND_ORDER" in src
    # No leftover SVG graph/orbit code from the old node-link renderer.
    assert "RING_RADIUS" not in src
    assert "layoutNodes" not in src
    assert "createElementNS" not in src


def test_mobile_soulmap_stays_two_by_two_not_stacked():
    """responsive.css forced 1-col grids at ≤768; soul orbs must stay 2×2."""
    responsive = open("static/css/responsive.css", encoding="utf-8").read()
    premium = open("static/css/premium.css", encoding="utf-8").read()
    assert "soulmap-constellation" in responsive
    assert "repeat(2, minmax(0, 1fr))" in responsive
    assert "soulmap-constellation" in premium
    assert "min(var(--orb-px" in premium


def test_mobile_telegram_touch_targets_and_week_top():
    css = open("static/css/council_first.css", encoding="utf-8").read()
    assert "message-intel__filter-chip" in css
    assert "min-height: 44px" in css
    assert "message-intel__week-top-meta" in css
    # week-top stacks author/stats on narrow phones
    assert ".message-intel__week-top-meta" in css
    assert "flex-direction: column" in css
    # Regression: a later ≤640px block once re-shrank the filter chip below the
    # 44px touch target set by the ≤390px block earlier in the cascade.
    chip_block = css.split(".message-intel--v2 .message-intel__filter-chip {")
    assert not any("min-height: 40px" in block.split("}", 1)[0] for block in chip_block[1:])
