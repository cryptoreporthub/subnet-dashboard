"""Visual upgrade — subnet identity bands, soul-map orbs, weight-shift viz.

One runnable check per non-trivial piece of new logic (ponytail rule): the
netuid->band hash, and that the SSR templates emit the tribunal-hero v4 markup
hooks the JS/CSS depend on (legacy k3-orb digit markup retired).
"""

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader, select_autoescape

from internal.council.publish_gate import publish_gate_label
from internal.preview.tribunal_hero import build_tribunal_view


def _tribunal_for(dpick: dict, trust_banner: dict | None = None) -> dict:
    return build_tribunal_view(
        dpick,
        {
            "judge_weights": {"oracle": 0.333, "echo": 0.333, "pulse": 0.334},
            "trust_banner": trust_banner or {},
        },
    )


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
    dpick = {
        "action": "HOLD",
        "pick": None,
        "candidate": {
            "subnet": {"netuid": netuid, "name": f"SN{netuid}"},
            "final_confidence": 0.5,
        },
    }
    return env.get_template("partials/premium/council_stage.html").render(
        dpick=dpick,
        daily_pick_stage=dpick,
        hybrid_trust={},
        trust_banner={},
        story_path={},
        habit_watchlist={"netuids": []},
        habit_alerts={"enabled": False},
        tribunal=_tribunal_for(dpick),
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
    dpick = {"action": "HOLD", "pick": None, "candidate": cand}
    return env.get_template("partials/premium/council_stage.html").render(
        dpick=dpick,
        daily_pick_stage=dpick,
        hybrid_trust={},
        trust_banner={},
        story_path={},
        habit_watchlist={"netuids": []},
        habit_alerts={"enabled": False},
        tribunal=_tribunal_for(dpick),
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
    assert 'id="tribunal-hero"' in html
    gauge = _gauge_score_html(html)
    assert "data-gauge-value" in gauge
    assert "—" in gauge
    assert "0%" not in gauge


def test_council_stage_h1_zero_conf_state_ssr():
    html = _render_council_stage_confidence(final_confidence=0)
    assert 'data-conf-state="zero"' in html
    gauge = _gauge_score_html(html)
    assert "0%" in gauge


def test_council_stage_h1_value_conf_state_ssr():
    html = _render_council_stage_confidence(final_confidence=0.5)
    assert 'data-conf-state="value"' in html
    gauge = _gauge_score_html(html)
    assert "50%" in gauge
    assert "—" not in gauge


def _gauge_score_html(html: str) -> str:
    """Tribunal hero gauge value span (replaces legacy digit-ones orb markup)."""
    return html.split('id="k3-orb-score"')[1].split("</span>", 1)[0]


def _read_ui_css() -> str:
    return open("static/css/ui.css", encoding="utf-8").read()


def _read_ui_legacy_css() -> str:
    return open("static/css/ui-legacy.css", encoding="utf-8").read()


def test_council_stage_h2_tribunal_gauge_css_in_ui_stylesheet():
    """H2: tribunal gauge + motion live in ui.css (no inline council_stage styles)."""
    css = _read_ui_css()
    assert ".tribunal-hero__gauge-fill" in css
    assert ".tribunal-hero__gauge-track" in css
    assert "tribunal-puff-1" in css
    assert "tribunal-glow-drift" in css
    assert '.tribunal-hero[data-verdict-kind="forming"]' in css


def test_council_stage_h2_conf_state_hooks_in_ui_css():
    """Tribunal v4 conf-state visuals live in ui.css (legacy k3-orb rules retired)."""
    css = _read_ui_css()
    assert '#k3-dossier[data-conf-state="resolving"]' in css
    assert '#k3-dossier[data-conf-state="zero"]' in css
    assert '#k3-dossier[data-conf-state="delayed"]' in css
    assert ".tribunal-hero__gauge-fill" in css


def test_council_stage_h2_tribunal_reduced_motion_disables_animations():
    css = _read_ui_css()
    assert "prefers-reduced-motion" in css
    reduced = css.split("prefers-reduced-motion", 1)[1]
    assert ".tribunal-hero__puff" in reduced
    assert "animation: none" in reduced


def test_cockpit_hydrate_h1_three_state_hooks_present():
    """Client-side patchK3DossierFromPayload three-state logic — no JS test runner in repo."""
    src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "_k3ConfResolvingTimer" in src
    assert "data-conf-state" in src
    assert "confState = 'resolving'" in src
    assert "confState = 'zero'" in src
    assert "confState = 'value'" in src


def test_council_stage_h1_resolving_gauge_distinct_from_zero():
    resolving = _render_council_stage_confidence(
        final_confidence=None, confidence=None, conviction=None
    )
    zero = _render_council_stage_confidence(final_confidence=0)
    assert "—" in _gauge_score_html(resolving)
    assert "0%" in _gauge_score_html(zero)
    assert "GATED" in resolving or "HOLD" in resolving
    assert 'id="k3-action-badge"' in resolving
    assert 'id="k3-action-badge"' in zero


def test_council_stage_horizon_badge_ssr_hidden_hydrate_unhides():
    """Horizon badge ships hidden in SSR; hydrate reveals on live payload."""
    html = _render_council_stage(82)
    assert 'id="k3-horizon-badge"' in html
    assert 'class="k3-horizon-badge"' in html
    badge = html.split('id="k3-horizon-badge"', 1)[1].split("</span>", 1)[0]
    assert "24h" in badge
    assert " hidden" in badge
    src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "k3-horizon-badge" in src
    assert "horizonBadge.hidden = false" in src


def test_council_stage_accuracy_building_sample_size_when_trust_not_ready():
    """AC5: trust_banner.ready false → building sample size, not a fake accuracy %."""
    html = _render_council_stage(82)
    assert 'id="k3-learning-acc-label">building sample size<' in html
    assert "Building sample size" in html
    acc = html.split('id="k3-learning-acc"', 1)[1].split("</div>", 1)[0]
    assert "%" not in acc


def test_cockpit_hydrate_horizon_badge_and_conf_label_hooks():
    src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "k3-horizon-badge" in src
    assert "syncK3GlowTier(fc.conf, payload.action, confState)" in src
    assert "label.textContent = 'resolving'" in src or "delayed' : 'resolving'" in src
    assert "label.textContent = 'zero'" in src


def test_council_stage_emits_netuid_hook_and_keeps_action_badge_separate():
    html = _render_council_stage(82)
    assert 'data-hero-netuid="82"' in html
    assert 'data-conf-state=' in html
    stage_src = open("templates/partials/premium/council_stage.html", encoding="utf-8").read()
    assert "function k3SyncNetuidBand" in stage_src
    assert "k3-claim--band-' + band" in stage_src
    # action badge markup untouched by identity color (still its own element)
    assert 'id="k3-action-badge"' in html
    assert 'id="tribunal-hero"' in html


def test_tribunal_hero_keeps_motion_layers_in_ui_css():
    css = _read_ui_css()
    for anim in ("tribunal-puff-1", "tribunal-puff-2", "tribunal-puff-3", "tribunal-glow-drift", "tribunal-ray-flow"):
        assert anim in css
    html = _render_council_stage(82)
    assert "tribunal-hero__puffs" in html
    assert "tribunal-hero__gauge-fill" in html


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


def test_tribunal_palette_uses_site_tokens_not_hardcoded_hex():
    css = _read_ui_css()
    assert ".tribunal-hero" in css
    assert "#ff69b4" not in css
    stage = open("templates/partials/premium/council_stage.html", encoding="utf-8").read()
    assert "#ff69b4" not in stage
    assert 'stop-color="#9d8cff"' not in stage


def test_learning_loop_shows_quiet_empty_state_when_no_deltas():
    html = _render_council_stage(82)
    assert "No weight shift this window" in html
    src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "No weight shift this window" in src


def test_soul_map_hydrate_trend_uses_delta_first_then_weight_baseline():
    src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "soulTrendFromWeight" in src
    assert "soulTrendFromDelta" in src
    assert "SOUL_WEIGHT_BASELINE" in src
    idx = src.index("function renderCouncilWeights")
    body = src[idx : idx + 1200]
    assert "soulTrendFromDelta(deltaMap[name], w)" in body
    assert "delta > 0.005 ? 'up'" not in body


def test_empty_hold_shell_emits_warming_tribunal_without_netuid_band():
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    from internal.council.publish_gate import publish_gate_label

    env.globals["publish_gate_label"] = publish_gate_label
    dpick = {"action": "HOLD", "brief": {"move": "HOLD · no long", "tone": "hold"}}
    html = env.get_template("partials/premium/council_stage.html").render(
        dpick=dpick,
        hybrid_trust={},
        trust_banner={},
        story_path={},
        habit_watchlist={"netuids": []},
        habit_alerts={"enabled": False},
        tribunal=_tribunal_for(dpick),
    )
    assert 'data-hero-phase="warming"' in html
    assert 'id="tribunal-hero"' in html
    assert 'data-band=' not in html


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
    """ui-legacy.css must keep soul orbs 2×2 at ≤768, not force 1-col grids."""
    legacy = open("static/css/ui-legacy.css", encoding="utf-8").read()
    assert "soulmap-constellation" in legacy
    assert "repeat(2, minmax(0, 1fr))" in legacy
    assert "min(var(--orb-px" in legacy


def test_mobile_telegram_touch_targets_and_week_top():
    css = open("static/css/ui-legacy.css", encoding="utf-8").read()
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


def test_hero_a_tier_stale_badge_markup_and_hydrate_hook():
    html = _render_council_stage(82)
    assert 'id="k3-stale-badge"' in html
    assert "k3-stale-badge" in html
    assert 'data-generated-at=' in html
    src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "patchK3StaleBadge" in src
    assert "k3StaleBadgeState" in src


def test_tribunal_hero_mobile_typography_at_390px():
    css = _read_ui_css()
    mobile = css.split("@media (max-width: 390px)", 1)[1].split("@media", 1)[0]
    assert ".tribunal-hero__stage" in mobile
    assert ".tribunal-hero__pct" in mobile


def test_council_stage_touch_targets_at_390px():
    css = _read_ui_css()
    assert ".council-stage .k3-layer-header" in css
    header_block = css.split(".council-stage .k3-layer-header", 1)[1][:300]
    assert "min-height: 44px" in header_block


def test_hero_a_tier_empty_evidence_honesty_ssr_and_hydrate():
    html = _render_council_stage(82)
    assert 'id="k3-evidence-empty"' in html
    assert "No evidence drivers on this call yet." in html
    src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "No evidence drivers on this call yet." in src
    assert "Reasons appear when the call carries signal notes." in src
    evidence_idx = src.index("function patchK3Evidence")
    evidence_body = src[evidence_idx : evidence_idx + 1400]
    assert "Reasons appear when the call carries signal notes." in evidence_body


def test_hero_a_tier_canonical_dossier_writer_documented():
    src = open("static/js/cockpit_hydrate.js", encoding="utf-8").read()
    assert "Canonical K3 dossier writer" in src
    assert "patchK3DossierFromPayload" in src
    live = open("static/js/home_live_refresh.js", encoding="utf-8").read()
    assert "__cockpitHome.renderDailyPick" in live


def test_k3_dossier_utilities_live_in_ui_css():
    css = _read_ui_css()
    for selector in (
        "--k3-green:",
        ".k3-temporal-badge",
        ".k3-stale-badge",
        ".k3-evidence-empty",
        ".k3-horizon-badge",
        ".k3-evidence-drivers",
        ".k3-brief-thesis",
        ".pick-degraded-note",
        ".k3-pump-chip",
        ".k3-horizon-chip",
        ".k3-brief-trigger",
    ):
        assert selector in css


def test_legacy_no_k3_orb_shell_styles():
    """Tribunal v4 retired the k3-orb / k3-claim layout shell."""
    legacy = _read_ui_legacy_css()
    for dead in (
        ".k3-orb-wrap",
        ".k3-orb-halo",
        "@keyframes k3-spin",
        "k3-resolving-ring-sweep",
        ".k3-claim-main",
    ):
        assert dead not in legacy


def test_k3_claim_identity_and_badge_live_in_ui_css():
    css = _read_ui_css()
    assert ".k3-claim-identity" in css
    assert ".k3-badge.hold" in css
    assert '.council-stage:has(#k3-dossier)' in css


def test_council_pick_card_uses_pewter_smoke_background():
    css = open("static/css/ui.css", encoding="utf-8").read()
    assert ".council-stage .home-job__call-host .k3-dossier" in css
    assert "var(--card-smoke)" in css.split(".council-stage .home-job__call-host .k3-dossier", 1)[1][:400]
