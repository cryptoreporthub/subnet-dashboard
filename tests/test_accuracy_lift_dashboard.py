"""Slice 7a — accuracy lift panel on proof band (read-only)."""

from __future__ import annotations

from pathlib import Path


def test_proof_band_has_accuracy_lift_panel():
    html = Path("templates/partials/premium_cockpit.html").read_text(encoding="utf-8")
    assert 'id="accuracy-lift-panel"' in html
    assert 'id="accuracy-lift-summary"' in html
    assert 'id="accuracy-lift-experts"' in html
    assert "Measurement ledger (30d)" in html


def test_hydrate_syncs_accuracy_lift_panel():
    js = Path("static/js/cockpit_hydrate.js").read_text(encoding="utf-8")
    assert "function syncAccuracyLiftPanel" in js
    assert "function ledgerMetricsPublic" in js
    assert "LEDGER_HIT_RATE_PUBLIC_MIN" in js
    assert "published_only" in js
    assert "published council graded" in js
    assert "hit rates hidden until sample clears" in js
    assert "/api/ops/evidence" in js
    assert "accuracy_lift" in js


def test_trust_banner_hides_ledger_hit_rate_on_homepage():
    js = Path("static/js/trust_banner_ui.js").read_text(encoding="utf-8")
    assert "ledger_graded_30d" in js
    assert "ledger_hit_rate_30d" not in js


def test_accuracy_lift_panel_styles_present():
    css = Path("static/css/ui.css").read_text(encoding="utf-8")
    assert ".accuracy-lift-panel" in css
    assert ".accuracy-lift-panel__experts" in css
