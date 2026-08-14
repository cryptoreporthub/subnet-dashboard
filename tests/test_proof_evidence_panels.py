"""PR7 — proof-band evidence sub-panels."""

from __future__ import annotations

from pathlib import Path


def test_proof_band_has_evidence_subpanels():
    html = Path("templates/partials/premium_cockpit.html").read_text(encoding="utf-8")
    assert 'id="proof-band-subpanels"' in html
    assert 'id="proof-sub-council-val"' in html
    assert 'id="proof-sub-telegram-val"' in html


def test_hydrate_syncs_proof_evidence_panels():
    js = Path("static/js/cockpit_hydrate.js").read_text(encoding="utf-8")
    assert "function syncProofEvidencePanels" in js
    assert "Published grades ' + graded + '/' + minGraded" in js
    assert "No outcome-backed council learning yet" in js
    assert "PRIOR · " in js
