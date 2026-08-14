"""PR7 — proof-band evidence sub-panels."""

from __future__ import annotations

from pathlib import Path


def test_proof_band_has_evidence_subpanels():
    html = Path("templates/partials/premium_cockpit.html").read_text(encoding="utf-8")
    assert 'id="proof-band-subpanels"' in html
    assert 'id="proof-sub-council-val"' in html
    assert 'id="proof-sub-telegram-val"' in html


def test_cockpit_brands_beta_badges():
    header = Path("templates/partials/premium/header.html").read_text(encoding="utf-8")
    css = Path("static/css/ui.css").read_text(encoding="utf-8")
    assert 'class="beta-stamp"' in header
    assert 'aria-label="Beta"' in header
    assert '.section-label::after' in css
    assert 'content: "BETA"' in css
    assert '#22b8ff' in css


def test_hydrate_syncs_proof_evidence_panels():
    js = Path("static/js/cockpit_hydrate.js").read_text(encoding="utf-8")
    assert "function syncProofEvidencePanels" in js
    assert "Published grades ' + graded + '/' + minGraded" in js
    assert "No outcome-backed council learning yet" in js
    assert "PRIOR · " in js
