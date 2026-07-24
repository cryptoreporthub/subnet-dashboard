"""S1 dossier identity crumbs on K3 preview."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server import app


def test_k3_hold_preview_has_identity_crumbs():
    client = TestClient(app)
    resp = client.get("/preview/k3-hold")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="k3-claim-name"' in html
    assert 'id="k3-claim-desc"' in html
    assert 'id="k3-resolve-crumb"' in html
    assert "Overbought momentum" in html
    assert "Resolves in 4h 12m" in html
